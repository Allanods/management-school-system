from django.contrib import messages
from django.db.models import Count, Q
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.generic import CreateView, DeleteView, DetailView, ListView, UpdateView

from accounts.access import AdminRequiredMixin
from core.models import ClassStream, SchoolClass, Stream, Subject, TeacherAssignment
from .forms import (
    ClassForm,
    ClassStreamForm,
    StreamForm,
    SubjectForm,
    TeacherAssignmentForm,
)


class _AdminContextMixin:
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = self.header_title
        return context


class ClassListView(AdminRequiredMixin, _AdminContextMixin, ListView):
    model = SchoolClass
    template_name = 'structure/class_list.html'
    context_object_name = 'classes'
    paginate_by = 20
    header_title = 'Classes'

    def get_queryset(self):
        queryset = super().get_queryset().annotate(
            stream_count=Count('class_streams', distinct=True),
            student_count=Count('class_streams__students', distinct=True),
        )
        q = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('is_active', '')
        if q:
            queryset = queryset.filter(name__icontains=q)
        if status == '1':
            queryset = queryset.filter(is_active=True)
        elif status == '0':
            queryset = queryset.filter(is_active=False)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop('page', None)
        context['page_qs'] = params.urlencode()
        context['filter_q'] = self.request.GET.get('q', '')
        context['filter_status'] = self.request.GET.get('is_active', '')
        return context


class ClassCreateView(AdminRequiredMixin, _AdminContextMixin, CreateView):
    model = SchoolClass
    form_class = ClassForm
    template_name = 'structure/class_form.html'
    header_title = 'Add Class'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, f'Class "{self.object.name}" created.')
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('structure:class_detail', args=[self.object.pk])


class ClassDetailView(AdminRequiredMixin, _AdminContextMixin, DetailView):
    model = SchoolClass
    template_name = 'structure/class_detail.html'
    context_object_name = 'school_class'
    header_title = 'Class Details'

    def get_queryset(self):
        return super().get_queryset().annotate(
            student_count=Count('class_streams__students', distinct=True)
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['class_streams'] = self.object.class_streams.prefetch_related(
            'assignments'
        ).annotate(
            student_count=Count('students', distinct=True)
        )
        return context


class ClassUpdateView(AdminRequiredMixin, _AdminContextMixin, UpdateView):
    model = SchoolClass
    form_class = ClassForm
    template_name = 'structure/class_form.html'
    header_title = 'Edit Class'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, 'Class updated.')
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('structure:class_detail', args=[self.object.pk])


class StreamListView(AdminRequiredMixin, _AdminContextMixin, ListView):
    model = Stream
    template_name = 'structure/stream_list.html'
    context_object_name = 'streams'
    paginate_by = 20
    header_title = 'Streams'

    def get_queryset(self):
        queryset = super().get_queryset().annotate(
            usage_count=Count('class_streams', distinct=True)
        )
        q = self.request.GET.get('q', '').strip()
        if q:
            queryset = queryset.filter(name__icontains=q)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop('page', None)
        context['page_qs'] = params.urlencode()
        context['filter_q'] = self.request.GET.get('q', '')
        return context


class StreamCreateView(AdminRequiredMixin, _AdminContextMixin, CreateView):
    model = Stream
    form_class = StreamForm
    template_name = 'structure/stream_form.html'
    header_title = 'Add Stream'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, f'Stream "{self.object.name}" created.')
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('structure:stream_list')


class StreamUpdateView(AdminRequiredMixin, _AdminContextMixin, UpdateView):
    model = Stream
    form_class = StreamForm
    template_name = 'structure/stream_form.html'
    header_title = 'Edit Stream'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, 'Stream updated.')
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('structure:stream_list')


class ClassStreamListView(AdminRequiredMixin, _AdminContextMixin, ListView):
    model = ClassStream
    template_name = 'structure/classstream_list.html'
    context_object_name = 'class_streams'
    paginate_by = 20
    header_title = 'Class Streams'

    def get_queryset(self):
        queryset = super().get_queryset().select_related(
            'school_class', 'stream', 'class_teacher'
        ).annotate(
            student_count=Count('students', distinct=True),
            subject_count=Count('subjects', distinct=True),
        )
        school_class = self.request.GET.get('school_class', '')
        stream = self.request.GET.get('stream', '')
        teacher = self.request.GET.get('class_teacher', '')
        if school_class:
            queryset = queryset.filter(school_class_id=school_class)
        if stream:
            queryset = queryset.filter(stream_id=stream)
        if teacher:
            queryset = queryset.filter(class_teacher_id=teacher)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop('page', None)
        context['page_qs'] = params.urlencode()
        from core.models import SchoolClass as SC, Stream as ST, Teacher as TT
        context['class_options'] = SC.objects.filter(is_active=True)
        context['stream_options'] = ST.objects.all()
        context['teacher_options'] = TT.objects.filter(is_active=True)
        context['filters'] = self.request.GET
        return context


class ClassStreamCreateView(AdminRequiredMixin, _AdminContextMixin, CreateView):
    model = ClassStream
    form_class = ClassStreamForm
    template_name = 'structure/classstream_form.html'
    header_title = 'Add Class Stream'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, f'Class stream "{self.object}" created.')
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('structure:classstream_detail', args=[self.object.pk])


class ClassStreamDetailView(AdminRequiredMixin, _AdminContextMixin, DetailView):
    model = ClassStream
    template_name = 'structure/classstream_detail.html'
    context_object_name = 'class_stream'
    header_title = 'Class Stream Details'

    def get_queryset(self):
        return super().get_queryset().select_related(
            'school_class', 'stream', 'class_teacher',
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['students'] = self.object.students.select_related(
            'class_stream'
        ).prefetch_related('parents')
        context['subjects'] = self.object.subjects.all()
        context['assignments'] = self.object.assignments.select_related(
            'teacher', 'subject'
        )
        return context


class ClassStreamUpdateView(AdminRequiredMixin, _AdminContextMixin, UpdateView):
    model = ClassStream
    form_class = ClassStreamForm
    template_name = 'structure/classstream_form.html'
    header_title = 'Edit Class Stream'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, 'Class stream updated.')
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('structure:classstream_detail', args=[self.object.pk])


class SubjectListView(AdminRequiredMixin, _AdminContextMixin, ListView):
    model = Subject
    template_name = 'structure/subject_list.html'
    context_object_name = 'subjects'
    paginate_by = 20
    header_title = 'Subjects'

    def get_queryset(self):
        queryset = super().get_queryset().annotate(
            assignment_count=Count('assignments', distinct=True)
        )
        q = self.request.GET.get('q', '').strip()
        status = self.request.GET.get('is_active', '')
        if q:
            queryset = queryset.filter(
                Q(name__icontains=q) | Q(code__icontains=q)
            )
        if status == '1':
            queryset = queryset.filter(is_active=True)
        elif status == '0':
            queryset = queryset.filter(is_active=False)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop('page', None)
        context['page_qs'] = params.urlencode()
        context['filter_q'] = self.request.GET.get('q', '')
        context['filter_status'] = self.request.GET.get('is_active', '')
        return context


class SubjectCreateView(AdminRequiredMixin, _AdminContextMixin, CreateView):
    model = Subject
    form_class = SubjectForm
    template_name = 'structure/subject_form.html'
    header_title = 'Add Subject'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(
            self.request, f'Subject "{self.object.name}" created.'
        )
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('structure:subject_list')


class SubjectUpdateView(AdminRequiredMixin, _AdminContextMixin, UpdateView):
    model = Subject
    form_class = SubjectForm
    template_name = 'structure/subject_form.html'
    header_title = 'Edit Subject'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, 'Subject updated.')
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('structure:subject_list')


class AssignmentListView(AdminRequiredMixin, _AdminContextMixin, ListView):
    model = TeacherAssignment
    template_name = 'structure/assignment_list.html'
    context_object_name = 'assignments'
    paginate_by = 20
    header_title = 'Teacher Assignments'

    def get_queryset(self):
        queryset = super().get_queryset().select_related(
            'teacher', 'class_stream', 'subject'
        )
        teacher = self.request.GET.get('teacher', '')
        school_class = self.request.GET.get('school_class', '')
        subject = self.request.GET.get('subject', '')
        if teacher:
            queryset = queryset.filter(teacher_id=teacher)
        if school_class:
            queryset = queryset.filter(class_stream__school_class_id=school_class)
        if subject:
            queryset = queryset.filter(subject_id=subject)
        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        params = self.request.GET.copy()
        params.pop('page', None)
        context['page_qs'] = params.urlencode()
        from core.models import SchoolClass as SC, Subject as SU, Teacher as TT
        context['teacher_options'] = TT.objects.filter(is_active=True)
        context['class_options'] = SC.objects.filter(is_active=True)
        context['subject_options'] = SU.objects.filter(is_active=True)
        context['filters'] = self.request.GET
        return context


class AssignmentCreateView(AdminRequiredMixin, _AdminContextMixin, CreateView):
    model = TeacherAssignment
    form_class = TeacherAssignmentForm
    template_name = 'structure/assignment_form.html'
    header_title = 'Add Assignment'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(
            self.request,
            f'{self.object.teacher.full_name} assigned to '
            f'{self.object.class_stream} - {self.object.subject.name}.',
        )
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('structure:assignment_list')


class AssignmentUpdateView(AdminRequiredMixin, _AdminContextMixin, UpdateView):
    model = TeacherAssignment
    form_class = TeacherAssignmentForm
    template_name = 'structure/assignment_form.html'
    header_title = 'Edit Assignment'

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, 'Assignment updated.')
        return HttpResponseRedirect(self.get_success_url())

    def get_success_url(self):
        return reverse('structure:assignment_list')


class AssignmentDeleteView(AdminRequiredMixin, _AdminContextMixin, DeleteView):
    model = TeacherAssignment
    template_name = 'structure/assignment_confirm_delete.html'
    context_object_name = 'assignment'
    header_title = 'Remove Assignment'

    def form_valid(self, form):
        self.object = self.get_object()
        messages.success(
            self.request,
            f'Assignment removed: {self.object.teacher.full_name} - '
            f'{self.object.class_stream} - {self.object.subject.name}.',
        )
        return super().form_valid(form)

    def get_success_url(self):
        return reverse('structure:assignment_list')