from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from accounts.access import AdminRequiredMixin, ParentRequiredMixin, StaffRequiredMixin
from core.models import ClassStream
from core.services import teacher_authorized_class_streams
from .forms import (
    ParentCreateForm,
    ParentForm,
    PromoteForm,
    StudentFilterForm,
    StudentForm,
    StudentParentFormSet,
)
from .models import Parent, Student
from .services import (
    promote_students,
    record_admission,
    record_class_change,
    suggest_admission_no,
)


def _role(request):
    return getattr(request.user, 'profile', None)


class GuardianFormsetMixin:
    """Shared guardian-editing behaviour for create and edit views."""

    def get_formset(self):
        if self.request.method == 'POST':
            if 'guardians-TOTAL_FORMS' in self.request.POST:
                return StudentParentFormSet(
                    self.request.POST, instance=self.object, prefix='guardians'
                )
            return None
        return StudentParentFormSet(instance=self.object, prefix='guardians')

    def post(self, request, *args, **kwargs):
        if request.POST.get('parent_submit'):
            return self._save_new_parent(request)
        return super().post(request, *args, **kwargs)

    def _save_new_parent(self, request):
        form = ParentCreateForm(request.POST, prefix='parent')
        if form.is_valid():
            parent = form.save()
            messages.success(
                request,
                f'Guardian "{parent.full_name}" created — select them in the list below.',
            )
        else:
            messages.error(request, 'Guardian could not be created. Check the details.')
        return HttpResponseRedirect(request.path)


class StudentListView(StaffRequiredMixin, ListView):
    model = Student
    template_name = 'students/student_list.html'
    context_object_name = 'students'
    paginate_by = 20

    def get_queryset(self):
        profile = _role(self.request)
        queryset = super().get_queryset().prefetch_related('parents')

        if profile.is_teacher:
            teacher = getattr(self.request.user, 'teacher', None)
            if teacher is None:
                return Student.objects.none()
            queryset = queryset.filter(
                class_stream__in=teacher_authorized_class_streams(teacher)
            )

        filter_form = StudentFilterForm(self.request.GET)
        if filter_form.is_valid():
            data = filter_form.cleaned_data
            if data['q']:
                queryset = queryset.filter(
                    Q(first_name__icontains=data['q'])
                    | Q(middle_name__icontains=data['q'])
                    | Q(last_name__icontains=data['q'])
                    | Q(admission_no__icontains=data['q'])
                )
            if data['school_class']:
                queryset = queryset.filter(class_stream__school_class=data['school_class'])
            if data['stream']:
                queryset = queryset.filter(class_stream__stream=data['stream'])
            if data['status']:
                queryset = queryset.filter(status=data['status'])

        return queryset.select_related('class_stream__school_class', 'class_stream__stream')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop('page', None)
        context['filter_form'] = StudentFilterForm(self.request.GET)
        context['page_qs'] = params.urlencode()
        context['page_title'] = 'Students'
        return context


class StudentDetailView(LoginRequiredMixin, DetailView):
    model = Student
    template_name = 'students/student_detail.html'
    context_object_name = 'student'

    def get_object(self, queryset=None):
        student = super().get_object(queryset=queryset)
        profile = _role(self.request)
        if profile is None:
            raise PermissionDenied('You do not have permission to access this page.')

        if profile.is_admin:
            return student

        if profile.is_teacher:
            teacher = getattr(self.request.user, 'teacher', None)
            authorized = teacher is not None and teacher_authorized_class_streams(
                teacher
            ).filter(pk=student.class_stream_id).exists()
            if not authorized:
                raise PermissionDenied(
                    'You do not have permission to view this student.'
                )
            return student

        if profile.is_parent:
            if not student.parents.filter(user=self.request.user).exists():
                raise PermissionDenied(
                    'You do not have permission to view this student.'
                )
            return student

        raise PermissionDenied('You do not have permission to access this page.')


class StudentCreateView(GuardianFormsetMixin, AdminRequiredMixin, CreateView):
    model = Student
    form_class = StudentForm
    template_name = 'students/student_form.html'
    page_title = 'Register Student'

    def get_initial(self):
        return {
            'admission_no': suggest_admission_no(),
            'date_admitted': timezone.localdate(),
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = self.page_title
        context['is_create'] = True
        context['parent_formset'] = self.get_formset()
        context['parent_create_form'] = ParentCreateForm(prefix='parent')
        return context

    def form_valid(self, form):
        self.object = form.save()
        record_admission(
            self.object, user=self.request.user,
            start_date=self.object.date_admitted,
        )
        formset = self.get_formset()
        if formset is not None and not formset.is_valid():
            return self.render_to_response(
                self.get_context_data(form=form, object=self.object)
            )
        if formset is not None:
            formset.save()
        messages.success(
            self.request,
            f'{self.object.full_name} (Adm. {self.object.admission_no}) registered.',
        )
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('students:detail', args=[self.object.pk])


class StudentUpdateView(GuardianFormsetMixin, AdminRequiredMixin, UpdateView):
    model = Student
    form_class = StudentForm
    template_name = 'students/student_form.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = f'Edit {self.object.full_name}'
        context['is_create'] = False
        context['parent_formset'] = self.get_formset()
        context['parent_create_form'] = ParentCreateForm(prefix='parent')
        return context

    def form_valid(self, form):
        previous_class_id = self.get_object().class_stream_id
        self.object = form.save()
        if self.object.class_stream_id != previous_class_id:
            try:
                record_class_change(
                    self.object, self.object.class_stream,
                    user=self.request.user,
                )
            except Exception:
                messages.warning(
                    self.request,
                    'The class was changed but the enrollment window could not '
                    'be updated automatically. Review the enrollment history.',
                )
        formset = self.get_formset()
        if formset is not None and not formset.is_valid():
            return self.render_to_response(
                self.get_context_data(form=form, object=self.object)
            )
        if formset is not None:
            formset.save()
        messages.success(self.request, 'Student details updated.')
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('students:detail', args=[self.object.pk])


class PromoteView(AdminRequiredMixin, View):
    template_name = 'students/promote.html'
    page_title = 'Promote Students'

    def _context(self, form):
        return {
            'page_title': self.page_title,
            'form': form,
        }

    def get(self, request, *args, **kwargs):
        class_stream = None
        if request.GET.get('class_stream'):
            class_stream = get_object_or_404(
                ClassStream, pk=request.GET['class_stream']
            )
        form = PromoteForm(class_stream=class_stream)
        return render(request, self.template_name, self._context(form))

    def post(self, request, *args, **kwargs):
        form = PromoteForm(request.POST)
        if not form.is_valid():
            return render(request, self.template_name, self._context(form))
        try:
            promoted = promote_students(
                actor=request.user,
                students=list(form.cleaned_data['students']),
                target_class_stream=form.cleaned_data['target_class_stream'],
                effective_date=form.cleaned_data['effective_date'],
                reason=form.cleaned_data['reason'],
                note=form.cleaned_data['note'],
            )
        except ValidationError as exc:
            for message in exc.messages:
                messages.error(request, message)
            return render(request, self.template_name, self._context(form))
        target = form.cleaned_data['target_class_stream']
        messages.success(
            request,
            f'{len(promoted)} student(s) promoted to {target} effective '
            f'{form.cleaned_data["effective_date"]}.',
        )
        return HttpResponseRedirect(
            reverse('students:promote') + f'?class_stream={target.pk}'
        )


class ParentChildrenView(LoginRequiredMixin, ParentRequiredMixin, ListView):
    model = Student
    template_name = 'students/my_children.html'
    context_object_name = 'students'

    def get_queryset(self):
        parent = Parent.objects.filter(user=self.request.user).first()
        if parent is None:
            return Student.objects.none()
        return parent.children.select_related(
            'class_stream__school_class', 'class_stream__stream'
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'My Children'
        return context


class ParentListView(AdminRequiredMixin, ListView):
    model = Parent
    template_name = 'students/parent_list.html'
    context_object_name = 'parents'
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset().prefetch_related('children_links')
        q = self.request.GET.get('q', '').strip()
        linked = self.request.GET.get('linked', '')
        if q:
            queryset = queryset.filter(
                Q(first_name__icontains=q) | Q(last_name__icontains=q)
            )
        if linked == 'linked':
            queryset = queryset.filter(user__isnull=False)
        elif linked == 'unlinked':
            queryset = queryset.filter(user__isnull=True)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop('page', None)
        context['page_qs'] = params.urlencode()
        context['filter_q'] = self.request.GET.get('q', '')
        context['filter_linked'] = self.request.GET.get('linked', '')
        context['unlinked_parent_count'] = (
            Parent.objects.filter(user__isnull=True).count()
            if self.request.GET.get('linked') != 'unlinked'
            else None
        )
        context['page_title'] = 'Parents'
        return context


class ParentCreateView(AdminRequiredMixin, CreateView):
    model = Parent
    form_class = ParentForm
    template_name = 'students/parent_form.html'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(
            self.request, f'Parent "{self.object.full_name}" created.'
        )
        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'Add Parent'
        context['is_create'] = True
        return context

    def get_success_url(self):
        return reverse('students:parent_detail', args=[self.object.pk])


class ParentDetailView(LoginRequiredMixin, DetailView):
    model = Parent
    template_name = 'students/parent_detail.html'
    context_object_name = 'parent'

    def get_object(self, queryset=None):
        parent = super().get_object(queryset=queryset)
        profile = _role(self.request)
        if profile is None:
            raise PermissionDenied('You do not have permission to access this page.')
        if profile.is_admin:
            return parent
        if profile.is_parent:
            own = Parent.objects.filter(user=self.request.user).first()
            if own is not None and own.pk == parent.pk:
                return parent
            raise PermissionDenied('You do not have permission to view this parent.')
        raise PermissionDenied('You do not have permission to access this page.')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = self.object.full_name
        context['is_profile'] = False
        if self.request.user.is_authenticated:
            profile = _role(self.request)
            context['is_profile'] = bool(
                profile and profile.is_parent
                and Parent.objects.filter(user=self.request.user, pk=self.object.pk).exists()
            )
        context['children_links'] = self.object.children_links.select_related(
            'student__class_stream__school_class', 'student__class_stream__stream'
        )
        return context


class ParentUpdateView(AdminRequiredMixin, UpdateView):
    model = Parent
    form_class = ParentForm
    template_name = 'students/parent_form.html'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, 'Parent details updated.')
        return HttpResponseRedirect(self.get_success_url())

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = f'Edit {self.object.full_name}'
        context['is_create'] = False
        return context

    def get_success_url(self):
        return reverse('students:parent_detail', args=[self.object.pk])