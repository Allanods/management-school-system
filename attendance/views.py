from datetime import datetime

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils.timezone import localdate
from django.views import View

from accounts.access import (
    ADMIN,
    AdminRequiredMixin,
    ParentRequiredMixin,
    get_role,
)
from core.models import ClassStream, Term
from core.services import teacher_authorized_attendance_streams
from students.models import Parent, Student
from students.services import get_class_roster
from .forms import AttendanceFormSet
from .models import Attendance
from .services import status_counts


class _PageTitleMixin:
    page_title = ''

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['page_title'] = self.page_title
        return context


def _teacher_of(user):
    return getattr(user, 'teacher', None)


def _parse_date(value):
    if not value:
        return localdate()
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return localdate()


class AttendanceHomeView(AdminRequiredMixin, _PageTitleMixin, View):
    template_name = 'attendance/attendance_home.html'
    page_title = 'Attendance Overview'

    def get(self, request, *args, **kwargs):
        today = localdate()
        today_records = Attendance.objects.filter(date=today).select_related(
            'class_stream__school_class', 'class_stream__stream'
        )
        streams = {}
        for record in today_records:
            streams.setdefault(record.class_stream_id, {
                'class_stream': record.class_stream,
                'count': 0,
            })['count'] += 1
        context = {
            'page_title': self.page_title,
            'today': today,
            'today_records': today_records,
            'today_summary': status_counts(today_records),
            'today_streams': sorted(
                streams.values(), key=lambda s: s['count'], reverse=True
            ),
            'recent_dates': Attendance.objects.values('date').order_by('-date')[:7],
        }
        return render(request, self.template_name, context)


class TakeAttendanceView(LoginRequiredMixin, _PageTitleMixin, View):
    template_name = 'attendance/take.html'
    page_title = 'Take Attendance'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        role = get_role(request.user)
        if role not in (ADMIN, 'TEACHER'):
            raise PermissionDenied('You do not have permission to take attendance.')
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        role = get_role(request.user)
        if role == ADMIN:
            streams = ClassStream.objects.select_related(
                'school_class', 'stream'
            ).order_by('school_class__name', 'stream__name')
        else:
            teacher = _teacher_of(request.user)
            streams = teacher_authorized_attendance_streams(teacher).select_related(
                'school_class', 'stream'
            ).order_by('school_class__name', 'stream__name')
        context = {
            'page_title': self.page_title,
            'streams': streams,
            'today': localdate(),
        }
        return render(request, self.template_name, context)


class AttendanceSheetView(LoginRequiredMixin, _PageTitleMixin, View):
    template_name = 'attendance/sheet.html'
    page_title = 'Attendance Sheet'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        class_stream_id = request.GET.get('class_stream')
        if not class_stream_id:
            messages.error(request, 'Select a class stream first.')
            return HttpResponseRedirect(reverse('attendance:take'))
        self.class_stream = get_object_or_404(ClassStream, pk=class_stream_id)
        self.date = _parse_date(request.GET.get('date'))
        self.future = self.date > localdate()
        role = get_role(request.user)
        self.is_admin = role == ADMIN
        if not self.is_admin:
            teacher = _teacher_of(request.user)
            if role != 'TEACHER' or teacher is None or not (
                teacher_authorized_attendance_streams(teacher)
                .filter(pk=self.class_stream.pk).exists()
            ):
                raise PermissionDenied(
                    'You do not have permission to manage attendance for this class stream.'
                )
        return super().dispatch(request, *args, **kwargs)

    def _roster(self):
        eligible = get_class_roster(self.class_stream, when=self.date)
        existing_records = list(
            Attendance.objects.filter(
                class_stream=self.class_stream, date=self.date
            ).select_related('student')
        )
        existing = {record.student_id: record for record in existing_records}
        pool = {student.pk: student for student in eligible}
        for record in existing_records:
            pool.setdefault(record.student_id, record.student)
        roster = sorted(pool.values(), key=lambda s: s.admission_no)
        return roster, existing

    def _formset(self, data=None):
        roster, existing = self._roster()
        initial = [
            {
                'student': student.pk,
                'status': (
                    existing[student.pk].status
                    if student.pk in existing
                    else Attendance.Status.PRESENT
                ),
            }
            for student in roster
        ]
        students = Student.objects.filter(pk__in=[s.pk for s in roster])
        return roster, AttendanceFormSet(
            data, initial=initial, form_kwargs={'students': students}
        )

    def _render(self, formset):
        roster, _ = self._roster()
        context = {
            'page_title': self.page_title,
            'class_stream': self.class_stream,
            'date': self.date,
            'future': self.future,
            'rows': list(zip(roster, formset)),
            'formset': formset,
            'summary': status_counts(
                Attendance.objects.filter(
                    class_stream=self.class_stream, date=self.date
                )
            ),
        }
        return render(self.request, self.template_name, context)

    def get(self, request, *args, **kwargs):
        roster, formset = self._formset()
        return self._render(formset)

    def post(self, request, *args, **kwargs):
        roster, formset = self._formset(data=request.POST)
        if self.future:
            messages.error(
                request, 'Attendance for future dates cannot be recorded.'
            )
            return self._render(formset)
        if not formset.is_valid():
            return self._render(formset)
        with transaction.atomic():
            saved = 0
            for form in formset.forms:
                student = form.cleaned_data['student']
                Attendance.objects.update_or_create(
                    student=student,
                    class_stream=self.class_stream,
                    date=self.date,
                    defaults={'status': form.cleaned_data['status'], 'recorded_by': request.user},
                )
                saved += 1
        messages.success(
            self.request,
            f'Attendance saved for {saved} student' + ('' if saved == 1 else 's') + '.',
        )
        return HttpResponseRedirect(
            reverse('attendance:sheet')
            + f'?class_stream={self.class_stream.pk}&date={self.date.isoformat()}'
        )


class AttendanceHistoryView(LoginRequiredMixin, _PageTitleMixin, View):
    template_name = 'attendance/history.html'
    page_title = 'Attendance History'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        role = get_role(request.user)
        self.is_admin = role == ADMIN
        self.teacher = None
        if role == 'TEACHER':
            self.teacher = _teacher_of(request.user)
            if self.teacher is None:
                raise PermissionDenied('You do not have permission to view records.')
        elif not self.is_admin:
            raise PermissionDenied('You do not have permission to view records.')
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        queryset = Attendance.objects.select_related(
            'student', 'class_stream__school_class', 'class_stream__stream'
        )
        if not self.is_admin:
            queryset = queryset.filter(
                class_stream__in=teacher_authorized_attendance_streams(self.teacher)
            )
        params = self.request.GET
        if params.get('class_stream'):
            queryset = queryset.filter(class_stream_id=params['class_stream'])
        if params.get('status'):
            queryset = queryset.filter(status=params['status'])
        if params.get('q'):
            queryset = queryset.filter(
                Q(student__first_name__icontains=params['q'])
                | Q(student__last_name__icontains=params['q'])
                | Q(student__admission_no__icontains=params['q'])
            )
        if params.get('date_from'):
            queryset = queryset.filter(date__gte=params['date_from'])
        if params.get('date_to'):
            queryset = queryset.filter(date__lte=params['date_to'])
        term_id = params.get('term')
        if term_id:
            term = get_object_or_404(Term, pk=term_id)
            queryset = queryset.filter(
                date__range=(term.start_date, term.end_date)
            )
        return queryset.order_by('-date', 'student__admission_no')

    def get(self, request, *args, **kwargs):
        filtered = self.get_queryset()
        summary = status_counts(filtered)
        paginator = Paginator(filtered, 25)
        page_obj = paginator.get_page(request.GET.get('page'))
        page_params = request.GET.copy()
        page_params.pop('page', None)
        class_stream_options = (
            ClassStream.objects.select_related('school_class', 'stream')
            if self.is_admin
            else teacher_authorized_attendance_streams(self.teacher).select_related(
                'school_class', 'stream'
            )
        )
        context = {
            'page_title': self.page_title,
            'page_obj': page_obj,
            'is_paginated': page_obj.has_other_pages(),
            'page_qs': page_params.urlencode(),
            'summary': summary,
            'filters': request.GET,
            'class_stream_options': class_stream_options.order_by(
                'school_class__name', 'stream__name'
            ),
            'term_options': Term.objects.select_related('year'),
            'status_totals': [
                {'value': value, 'label': label, 'count': summary['counts'][value]}
                for value, label in Attendance.Status.choices
            ],
        }
        return render(request, self.template_name, context)


class ParentChildrenAttendanceView(ParentRequiredMixin, _PageTitleMixin, View):
    template_name = 'attendance/my_children.html'
    page_title = 'Attendance — My Children'

    def get(self, request, *args, **kwargs):
        parent = Parent.objects.filter(user=request.user).first()
        children = (
            parent.children.select_related('class_stream__school_class', 'class_stream__stream')
            if parent
            else Student.objects.none()
        )
        children = children.order_by('admission_no')
        for child in children:
            child.attendance_summary = status_counts(
                Attendance.objects.filter(student=child)
            )
        context = {
            'page_title': self.page_title,
            'students': children,
        }
        return render(request, self.template_name, context)


class StudentAttendanceView(LoginRequiredMixin, _PageTitleMixin, View):
    template_name = 'attendance/student_attendance.html'
    page_title = 'Student Attendance'

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        self.student = get_object_or_404(
            Student.objects.select_related(
                'class_stream__school_class', 'class_stream__stream'
            ),
            pk=kwargs['pk'],
        )
        role = get_role(request.user)
        if role == ADMIN:
            return super().dispatch(request, *args, **kwargs)
        if role == 'PARENT' and self.student.parents.filter(
            user=request.user
        ).exists():
            return super().dispatch(request, *args, **kwargs)
        if role == 'TEACHER':
            teacher = _teacher_of(request.user)
            if teacher is not None and teacher_authorized_attendance_streams(
                teacher
            ).filter(pk=self.student.class_stream_id).exists():
                return super().dispatch(request, *args, **kwargs)
        raise PermissionDenied('You do not have permission to view this student.')

    def get(self, request, *args, **kwargs):
        queryset = self.student.attendance.order_by('-date')
        params = request.GET
        if params.get('date_from'):
            queryset = queryset.filter(date__gte=params['date_from'])
        if params.get('date_to'):
            queryset = queryset.filter(date__lte=params['date_to'])
        paginator = Paginator(queryset, 20)
        page_obj = paginator.get_page(request.GET.get('page'))
        page_params = request.GET.copy()
        page_params.pop('page', None)
        context = {
            'page_title': self.page_title,
            'student': self.student,
            'page_obj': page_obj,
            'is_paginated': page_obj.has_other_pages(),
            'page_qs': page_params.urlencode(),
            'summary': status_counts(queryset),
            'filters': request.GET,
        }
        return render(request, self.template_name, context)