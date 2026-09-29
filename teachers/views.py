from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import CreateView, DetailView, ListView, UpdateView

from accounts.access import AdminRequiredMixin, StaffRequiredMixin, TeacherRequiredMixin
from core.models import ClassStream, Teacher
from .forms import TeacherAssignmentFormSet, TeacherFilterForm, TeacherForm


class AssignmentFormsetMixin:
    def get_formset(self):
        if self.request.method == 'POST':
            if 'assignments-TOTAL_FORMS' in self.request.POST:
                return TeacherAssignmentFormSet(
                    self.request.POST, instance=self.object, prefix='assignments'
                )
            return None
        return TeacherAssignmentFormSet(instance=self.object, prefix='assignments')


class TeacherListView(AdminRequiredMixin, ListView):
    model = Teacher
    template_name = 'teachers/teacher_list.html'
    context_object_name = 'teachers'
    paginate_by = 20

    def get_queryset(self):
        queryset = super().get_queryset().prefetch_related(
            'assignments', 'classes'
        )

        filter_form = TeacherFilterForm(self.request.GET)
        if filter_form.is_valid():
            data = filter_form.cleaned_data
            if data['q']:
                queryset = queryset.filter(
                    Q(first_name__icontains=data['q'])
                    | Q(middle_name__icontains=data['q'])
                    | Q(last_name__icontains=data['q'])
                    | Q(employee_no__icontains=data['q'])
                )
            if data['department']:
                queryset = queryset.filter(department=data['department'])
            if data['is_active'] in ('1', '0'):
                queryset = queryset.filter(is_active=data['is_active'] == '1')

        return queryset.select_related('department')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop('page', None)
        context['filter_form'] = TeacherFilterForm(self.request.GET)
        context['page_qs'] = params.urlencode()
        context['page_title'] = 'Teachers'
        return context


class TeacherDetailView(StaffRequiredMixin, DetailView):
    model = Teacher
    template_name = 'teachers/teacher_detail.html'
    context_object_name = 'teacher'

    def get_object(self, queryset=None):
        teacher = super().get_object(queryset=queryset)
        profile = getattr(self.request.user, 'profile', None)

        if profile.is_admin:
            return teacher

        own = getattr(self.request.user, 'teacher', None)
        if own is not None and own.pk == teacher.pk:
            return teacher
        raise PermissionDenied('You do not have permission to view this teacher.')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = self.object.full_name
        context['is_profile'] = False
        context['headed_stream'] = ClassStream.objects.filter(
            class_teacher=self.object
        ).first()
        return context


class TeacherCreateView(AssignmentFormsetMixin, AdminRequiredMixin, CreateView):
    model = Teacher
    form_class = TeacherForm
    template_name = 'teachers/teacher_form.html'
    page_title = 'Register Teacher'

    def get_initial(self):
        return {'date_joined': timezone.localdate()}

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = self.page_title
        context['is_create'] = True
        context['assignment_formset'] = self.get_formset()
        return context

    def form_valid(self, form):
        self.object = form.save()
        formset = self.get_formset()
        if formset is not None and not formset.is_valid():
            return self.render_to_response(
                self.get_context_data(form=form, object=self.object)
            )
        if formset is not None:
            formset.save()
        messages.success(
            self.request,
            f'{self.object.full_name} (Emp. {self.object.employee_no}) registered.',
        )
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('teachers:detail', args=[self.object.pk])


class TeacherUpdateView(AssignmentFormsetMixin, AdminRequiredMixin, UpdateView):
    model = Teacher
    form_class = TeacherForm
    template_name = 'teachers/teacher_form.html'

    def get_initial(self):
        initial = super().get_initial()
        if self.object and self.object.pk:
            head = ClassStream.objects.filter(
                class_teacher=self.object
            ).first()
            if head:
                initial['class_teacher_for'] = head.pk
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = f'Edit {self.object.full_name}'
        context['is_create'] = False
        context['assignment_formset'] = self.get_formset()
        return context

    def form_valid(self, form):
        self.object = form.save()
        formset = self.get_formset()
        if formset is not None and not formset.is_valid():
            return self.render_to_response(
                self.get_context_data(form=form, object=self.object)
            )
        if formset is not None:
            formset.save()
        messages.success(self.request, 'Teacher details updated.')
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('teachers:detail', args=[self.object.pk])


class MyTeacherProfileView(TeacherRequiredMixin, DetailView):
    model = Teacher
    template_name = 'teachers/teacher_detail.html'
    context_object_name = 'teacher'

    def get_object(self, queryset=None):
        teacher = getattr(self.request.user, 'teacher', None)
        if teacher is None:
            raise PermissionDenied('No teacher profile is linked to your account.')
        return teacher

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = 'My Profile'
        context['is_profile'] = True
        context['headed_stream'] = ClassStream.objects.filter(
            class_teacher=self.object
        ).first()
        return context