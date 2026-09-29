from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from accounts.access import ADMIN, PARENT, TEACHER, get_role
from core.models import ClassStream
from core.services import (
    teacher_authorized_attendance_streams,
    teacher_authorized_class_streams,
)
from students.models import Student

from .services import student_in_teacher_result_scope, student_term_choice


def _teacher_of(user):
    return getattr(user, 'teacher', None)


class ReportAccessMixin:
    """Staff-only report pages. Admins may see every class stream; teachers
    are scoped to the streams granted by the concrete subclass. CSV endpoints
    reuse the same dispatch, so an export never contains rows the matching
    HTML page may not show."""

    scoped_streams = None

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        role = get_role(request.user)
        if role == ADMIN:
            self.scoped_streams = ClassStream.objects.select_related(
                'school_class', 'stream'
            )
            return super().dispatch(request, *args, **kwargs)
        if role == TEACHER:
            teacher = _teacher_of(request.user)
            if teacher is not None:
                self.scoped_streams = self.teacher_streams(teacher)
                return super().dispatch(request, *args, **kwargs)
        raise PermissionDenied('You do not have permission to view this report.')

    def teacher_streams(self, teacher):
        raise NotImplementedError

    def class_stream_choices(self):
        return self.scoped_streams.order_by('school_class__name', 'stream__name')


class ResultsReportAccessMixin(ReportAccessMixin):
    """Result reports: teachers may view results for the streams they teach
    (subject assignments, class teachorship, and whole-class coverage)."""

    def teacher_streams(self, teacher):
        return teacher_authorized_class_streams(teacher).select_related(
            'school_class', 'stream'
        )


class AttendanceReportAccessMixin(ReportAccessMixin):
    """Attendance reports: teachers may view attendance only for streams they
    are class teacher of — independent of marks permissions."""

    def teacher_streams(self, teacher):
        return teacher_authorized_attendance_streams(teacher).select_related(
            'school_class', 'stream'
        )


class StudentReportAccessMixin:
    """Scoped access to a single student's report card.

    - ADMIN may open any student.
    - PARENT may open only students linked to their own account.
    - TEACHER may open a student who belongs to one of their result streams
      for the requested term (historical enrollment membership respected).
    """

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
        if role == PARENT:
            if self.student.parents.filter(user=request.user).exists():
                return super().dispatch(request, *args, **kwargs)
            raise PermissionDenied(
                'You do not have permission to view this student report.'
            )
        if role == TEACHER:
            teacher = _teacher_of(request.user)
            if teacher is not None:
                term = student_term_choice(
                    self.student, request.GET.get('term')
                )
                if student_in_teacher_result_scope(teacher, self.student, term):
                    return super().dispatch(request, *args, **kwargs)
            raise PermissionDenied(
                'You do not have permission to view this student report.'
            )
        raise PermissionDenied('You do not have permission to view this student report.')