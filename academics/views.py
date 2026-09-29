from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.forms import formset_factory
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views import View
from django.views.generic import CreateView, DeleteView, DetailView, ListView, TemplateView, UpdateView

from accounts.access import (
    ADMIN,
    AdminRequiredMixin,
    ParentRequiredMixin,
    TeacherRequiredMixin,
    get_role,
)
from core.models import AcademicYear, ClassStream, Term
from core.services import (
    teacher_authorized_attendance_streams,
    teacher_authorized_class_streams,
    teacher_mark_streams,
)
from students.models import Parent, Student
from students.services import get_class_roster_for_term
from .forms import AcademicYearForm, AssessmentForm, GradeBandForm, MarkEntryForm, TermForm
from .models import Assessment, GradeBand
from .services import (
    assessment_results,
    can_manage_assessment,
    save_mark,
    student_term_results,
    teacher_authorized_assessments,
)

MarkEntryFormSet = formset_factory(MarkEntryForm, extra=0)


class _PageTitleMixin:
    page_title = ''

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = self.page_title
        return context


def _teacher_of(user):
    return getattr(user, 'teacher', None)


class AcademicsHomeView(AdminRequiredMixin, _PageTitleMixin, TemplateView):
    template_name = 'academics/academics_home.html'
    page_title = 'Academics Overview'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['current_year'] = AcademicYear.objects.filter(is_current=True).first()
        context['current_term'] = Term.objects.filter(is_current=True).first()
        context['year_count'] = AcademicYear.objects.count()
        context['term_count'] = Term.objects.count()
        context['assessment_count'] = Assessment.objects.count()
        context['published_count'] = Assessment.objects.filter(
            status=Assessment.Status.PUBLISHED
        ).count()
        context['recent_assessments'] = Assessment.objects.select_related(
            'term', 'class_stream', 'subject'
        )[:6]
        context['years'] = AcademicYear.objects.order_by('-start_date')[:5]
        return context


class YearListView(AdminRequiredMixin, _PageTitleMixin, ListView):
    model = AcademicYear
    template_name = 'academics/year_list.html'
    context_object_name = 'years'
    paginate_by = 12
    page_title = 'Academic Years'

    def get_queryset(self):
        return super().get_queryset().annotate(
            term_count=Count('terms')
        ).order_by('-start_date')

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        year_ids = [year.pk for year in self.object_list]
        terms = Term.objects.filter(year_id__in=year_ids).select_related('year')
        context['terms'] = {pk: [] for pk in year_ids}
        for term in terms:
            context['terms'][term.year_id].append(term)
        return context


class YearCreateView(AdminRequiredMixin, _PageTitleMixin, CreateView):
    model = AcademicYear
    form_class = AcademicYearForm
    template_name = 'academics/year_form.html'
    page_title = 'Add Academic Year'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, f'Academic year "{self.object.name}" created.')
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('academics:year_list')


class YearUpdateView(AdminRequiredMixin, _PageTitleMixin, UpdateView):
    model = AcademicYear
    form_class = AcademicYearForm
    template_name = 'academics/year_form.html'
    page_title = 'Edit Academic Year'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, 'Academic year updated.')
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('academics:year_list')


class YearSetCurrentView(AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        year = get_object_or_404(AcademicYear, pk=kwargs['pk'])
        AcademicYear.objects.exclude(pk=year.pk).update(is_current=False)
        year.is_current = True
        year.save(update_fields=['is_current'])
        messages.success(self.request, f'"{year.name}" is now the current year.')
        return HttpResponseRedirect(reverse('academics:year_list'))


class TermCreateView(AdminRequiredMixin, _PageTitleMixin, CreateView):
    model = Term
    form_class = TermForm
    template_name = 'academics/term_form.html'
    page_title = 'Add Term'

    def get_initial(self):
        year_id = self.request.GET.get('year')
        if year_id:
            return {'year': year_id}
        return {}

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, f'Term "{self.object}" created.')
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('academics:year_list')


class TermUpdateView(AdminRequiredMixin, _PageTitleMixin, UpdateView):
    model = Term
    form_class = TermForm
    template_name = 'academics/term_form.html'
    page_title = 'Edit Term'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, 'Term updated.')
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('academics:year_list')


class TermSetCurrentView(AdminRequiredMixin, View):
    def post(self, request, *args, **kwargs):
        term = get_object_or_404(Term, pk=kwargs['pk'])
        Term.objects.exclude(pk=term.pk).update(is_current=False)
        term.is_current = True
        term.save(update_fields=['is_current'])
        messages.success(self.request, f'"{term}" is now the current term.')
        return HttpResponseRedirect(reverse('academics:year_list'))


class AssessmentListView(AdminRequiredMixin, _PageTitleMixin, ListView):
    model = Assessment
    template_name = 'academics/assessment_list.html'
    context_object_name = 'assessments'
    paginate_by = 20
    page_title = 'Assessments'

    def get_queryset(self):
        queryset = super().get_queryset().select_related(
            'term', 'class_stream', 'subject'
        ).annotate(
            marks_count=Count('marks')
        )
        params = self.request.GET
        if params.get('term'):
            queryset = queryset.filter(term_id=params.get('term'))
        if params.get('class_stream'):
            queryset = queryset.filter(class_stream_id=params.get('class_stream'))
        if params.get('subject'):
            queryset = queryset.filter(subject_id=params.get('subject'))
        if params.get('status'):
            queryset = queryset.filter(status=params.get('status'))
        if params.get('q'):
            queryset = queryset.filter(name__icontains=params.get('q'))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop('page', None)
        context['page_qs'] = params.urlencode()
        context['filters'] = self.request.GET
        context['term_options'] = Term.objects.select_related('year')
        context['class_stream_options'] = ClassStream.objects.select_related(
            'school_class', 'stream'
        )
        from core.models import Subject as SubjectOption
        context['subject_options'] = SubjectOption.objects.filter(is_active=True)
        return context


class AssessmentCreateView(AdminRequiredMixin, _PageTitleMixin, CreateView):
    model = Assessment
    form_class = AssessmentForm
    template_name = 'academics/assessment_form.html'
    page_title = 'Create Assessment'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(
            self.request,
            f'Assessment "{self.object.name}" created for '
            f'{self.object.class_stream} - {self.object.subject.name}.',
        )
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('academics:assessment_detail', args=[self.object.pk])


class AssessmentUpdateView(AdminRequiredMixin, _PageTitleMixin, UpdateView):
    model = Assessment
    form_class = AssessmentForm
    template_name = 'academics/assessment_form.html'
    page_title = 'Edit Assessment'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, 'Assessment updated.')
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('academics:assessment_detail', args=[self.object.pk])


class AssessmentResultsMixin:
    """Shared access: admin anywhere, teacher only for own assignments."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        self.assessment = get_object_or_404(Assessment, pk=kwargs['pk'])
        role = get_role(request.user)
        self.is_admin = role == ADMIN
        if self.is_admin:
            return super().dispatch(request, *args, **kwargs)
        teacher = _teacher_of(request.user)
        if role != 'TEACHER' or teacher is None or not can_manage_assessment(
            teacher, self.assessment
        ):
            raise PermissionDenied('You do not have permission to view this assessment.')
        return super().dispatch(request, *args, **kwargs)


class AssessmentDetailView(AssessmentResultsMixin, _PageTitleMixin, DetailView):
    model = Assessment
    template_name = 'academics/assessment_detail.html'
    context_object_name = 'assessment'
    page_title = 'Assessment Results'

    def get_object(self, queryset=None):
        return self.assessment

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['results'] = assessment_results(self.assessment)
        teacher = _teacher_of(self.request.user)
        context['can_enter_marks'] = self.is_admin or (
            teacher is not None
            and can_manage_assessment(teacher, self.assessment)
            and self.assessment.status != Assessment.Status.PUBLISHED
        )
        return context


class TeacherClassesView(TeacherRequiredMixin, _PageTitleMixin, TemplateView):
    template_name = 'academics/teacher_classes.html'
    page_title = 'My Classes'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        teacher = _teacher_of(self.request.user)
        if teacher is None:
            context['combos'] = []
            context['teacher'] = None
            return context

        streams = teacher_authorized_class_streams(teacher).select_related(
            'school_class', 'stream'
        ).order_by('school_class', 'stream')
        assignments = teacher.assignments.select_related(
            'class_stream__school_class',
            'class_stream__stream',
            'subject',
        ).order_by('class_stream', 'subject')
        by_stream = {}
        for assignment in assignments:
            by_stream.setdefault(assignment.class_stream_id, []).append(assignment)
        headed_ids = set(
            teacher_authorized_attendance_streams(teacher).values_list(
                'pk', flat=True
            )
        )
        whole_ids = set(
            ClassStream.objects.filter(
                school_class__in=teacher.classes.all()
            ).values_list('pk', flat=True)
        )

        combos = []
        for stream in streams:
            combo = {
                'class_stream': stream,
                'subject_assignments': by_stream.get(stream.pk, []),
                'is_class_teacher': stream.pk in headed_ids,
                'is_whole_class': stream.pk in whole_ids,
            }
            subjects = {
                a.subject_id: a.subject for a in combo['subject_assignments']
            }
            processed = []
            for subject_id in subjects:
                processed.append({
                    'subject': subjects[subject_id],
                    'assessment_count': Assessment.objects.filter(
                        class_stream=stream, subject_id=subject_id
                    ).count(),
                })
            combo['subjects'] = processed
            combos.append(combo)
        context['combos'] = combos
        context['teacher'] = teacher
        return context


class TeacherMarksView(TeacherRequiredMixin, _PageTitleMixin, ListView):
    template_name = 'academics/teacher_marks.html'
    context_object_name = 'assessments'
    paginate_by = 20
    page_title = 'My Assessments & Marks'

    def get_queryset(self):
        teacher = _teacher_of(self.request.user)
        queryset = teacher_authorized_assessments(teacher).annotate(
            marks_count=Count('marks')
        ).order_by('term', 'class_stream', 'subject', 'name')
        params = self.request.GET
        if params.get('class_stream'):
            queryset = queryset.filter(class_stream_id=params.get('class_stream'))
        if params.get('subject'):
            queryset = queryset.filter(subject_id=params.get('subject'))
        if params.get('status'):
            queryset = queryset.filter(status=params.get('status'))
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop('page', None)
        context['page_qs'] = params.urlencode()
        context['filters'] = self.request.GET
        teacher = _teacher_of(self.request.user)
        context['class_stream_options'] = teacher_mark_streams(teacher).select_related(
            'school_class', 'stream'
        )
        from core.models import Subject as SubjectOption
        context['subject_list'] = SubjectOption.objects.filter(
            assignments__teacher=teacher
        ).distinct()
        return context


class GradeBandListView(AdminRequiredMixin, _PageTitleMixin, ListView):
    model = GradeBand
    template_name = 'academics/gradeband_list.html'
    context_object_name = 'bands'
    page_title = 'Grade Bands'

    def get_queryset(self):
        return super().get_queryset().order_by('min_percent')


class GradeBandCreateView(AdminRequiredMixin, _PageTitleMixin, CreateView):
    model = GradeBand
    form_class = GradeBandForm
    template_name = 'academics/gradeband_form.html'
    page_title = 'Add Grade Band'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(
            self.request, f'Grade band "{self.object.label}" created.'
        )
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('academics:gradeband_list')


class GradeBandUpdateView(AdminRequiredMixin, _PageTitleMixin, UpdateView):
    model = GradeBand
    form_class = GradeBandForm
    template_name = 'academics/gradeband_form.html'
    page_title = 'Edit Grade Band'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, 'Grade band updated.')
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('academics:gradeband_list')


class GradeBandDeleteView(AdminRequiredMixin, _PageTitleMixin, DeleteView):
    model = GradeBand
    template_name = 'academics/gradeband_confirm_delete.html'
    context_object_name = 'band'
    page_title = 'Delete Grade Band'

    def form_valid(self, form):
        self.object = self.get_object()
        messages.success(
            self.request,
            f'Grade band "{self.object.label}" deleted. '
            'Grades for that range are no longer computed until replaced.',
        )
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('academics:gradeband_list')


class MarkEntryView(AssessmentResultsMixin, _PageTitleMixin, View):
    template_name = 'academics/mark_entry.html'
    page_title = 'Enter Marks'

    def _eligible_students(self):
        return get_class_roster_for_term(
            self.assessment.class_stream, self.assessment.term,
        )

    def _formset(self, data=None):
        students = self._eligible_students()
        existing = {
            mark.student_id: mark.scored for mark in self.assessment.marks.all()
        }
        initial = [
            {'student': student.pk, 'scored': existing.get(student.pk)}
            for student in students
        ]
        return MarkEntryFormSet(
            data,
            initial=initial,
            form_kwargs={
                'students': students,
                'assessment': self.assessment,
            },
        )

    def _published_lock(self):
        if not self.is_admin and self.assessment.status == Assessment.Status.PUBLISHED:
            messages.warning(
                self.request,
                'This assessment is published and its marks are locked. '
                'Only an administrator can change published marks.',
            )
            return HttpResponseRedirect(
                reverse('academics:assessment_detail', args=[self.assessment.pk])
            )
        return None

    def get(self, request, *args, **kwargs):
        blocked = self._published_lock()
        if blocked:
            return blocked
        formset = self._formset()
        return self._render(formset)

    def post(self, request, *args, **kwargs):
        blocked = self._published_lock()
        if blocked:
            return blocked
        formset = self._formset(data=request.POST)
        if not formset.is_valid():
            return self._render(formset)
        saved = 0
        for form in formset.forms:
            scored = form.cleaned_data['scored']
            if scored is None:
                continue
            save_mark(form.cleaned_data['student'], self.assessment, scored)
            saved += 1
        if saved:
            messages.success(
                self.request, f'Marks saved for {saved} student'
                + ('' if saved == 1 else 's') + '.'
            )
        else:
            messages.warning(self.request, 'No scores were entered.')
        return HttpResponseRedirect(
            reverse('academics:assessment_detail', args=[self.assessment.pk])
        )

    def _render(self, formset):
        students = list(self._eligible_students())
        rows = list(zip(students, formset))
        context = {
            'assessment': self.assessment,
            'formset': formset,
            'rows': rows,
            'page_title': self.page_title,
            'existing_count': self.assessment.marks.count(),
            'student_count': len(students),
        }
        return self.render_to_response(context)

    def render_to_response(self, context, **response_kwargs):
        from django.template.loader import render_to_string
        from django.http import HttpResponse
        return HttpResponse(
            render_to_string(self.template_name, context, request=self.request)
        )


class ParentPerformanceView(ParentRequiredMixin, _PageTitleMixin, ListView):
    model = Student
    template_name = 'academics/parent_performance.html'
    context_object_name = 'students'
    page_title = 'Performance'

    def get_queryset(self):
        parent = Parent.objects.filter(user=self.request.user).first()
        if parent is None:
            return Student.objects.none()
        return parent.children.select_related(
            'class_stream__school_class', 'class_stream__stream'
        ).order_by('admission_no')


class ChildResultsView(LoginRequiredMixin, _PageTitleMixin, DetailView):
    model = Student
    template_name = 'academics/child_results.html'
    context_object_name = 'student'
    page_title = 'Term Results'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        student = get_object_or_404(Student, pk=kwargs['pk'])
        role = get_role(request.user)
        if role == ADMIN:
            self.student = student
            return super().dispatch(request, *args, **kwargs)
        if role == 'PARENT' and student.parents.filter(
            user=request.user
        ).exists():
            self.student = student
            return super().dispatch(request, *args, **kwargs)
        raise PermissionDenied('You do not have permission to view this student result.')

    def get_object(self, queryset=None):
        return self.student

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        student = self.student
        term_options = Term.objects.filter(
            assessments__status=Assessment.Status.PUBLISHED,
            assessments__marks__student=student,
        ).distinct().order_by('-start_date')
        term_id = self.request.GET.get('term')
        term = None
        if term_id:
            term = term_options.filter(pk=term_id).first()
        if term is None:
            term = Term.objects.filter(is_current=True).first()
            if term is None:
                term = term_options.first()
        context['term'] = term
        context['term_options'] = term_options
        context['results'] = student_term_results(student, term) if term else None
        return context