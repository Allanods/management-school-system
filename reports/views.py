from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, render
from django.views import View

from academics.models import Assessment
from accounts.access import AdminRequiredMixin, ParentRequiredMixin
from attendance.models import Attendance
from core.models import ClassStream, SchoolProfile, Term
from students.models import Parent, Student

from .access import (
    AttendanceReportAccessMixin,
    ResultsReportAccessMixin,
    StudentReportAccessMixin,
)
from .csv_export import (
    attendance_csv,
    class_performance_csv,
    csv_response,
    finance_csv,
    student_report_csv,
)
from .services import (
    class_attendance_report,
    class_finance_report,
    class_term_report,
    student_attendance_summary,
    student_report,
    student_term_choice,
)


def _school_profile():
    return SchoolProfile.objects.first()


def _resolve_term(request):
    """Term selector: explicit choice, else the current term, else the most
    recent term on record."""
    term_id = request.GET.get('term')
    if term_id:
        return get_object_or_404(Term, pk=term_id)
    current = Term.objects.filter(is_current=True).first()
    if current:
        return current
    return Term.objects.order_by('-start_date').first()


def _resolve_class_stream(request, scope, term, prefer_records=False):
    """Class selector restricted to the caller's report scope. Requesting a
    class outside the scope raises PermissionDenied, so teachers cannot probe
    other classes through the report."""
    cs_id = request.GET.get('class_stream')
    if cs_id:
        stream = scope.filter(pk=cs_id).first()
        if stream is None:
            raise PermissionDenied(
                'Class stream is outside your report scope.'
            )
        return stream
    if prefer_records and term is not None:
        with_records = scope.filter(
            attendance_records__date__gte=term.start_date,
            attendance_records__date__lte=term.end_date,
        ).distinct()[0:1]
        if with_records:
            return with_records[0]
    if term is not None:
        with_results = scope.filter(
            academic_assessments__term=term,
            academic_assessments__status=Assessment.Status.PUBLISHED,
        ).distinct()[0:1]
        if with_results:
            return with_results[0]
    return scope.first()


def _term_options():
    return Term.objects.select_related('year').order_by('-start_date')


def _student_term_options(student):
    return Term.objects.filter(
        assessments__status=Assessment.Status.PUBLISHED,
        assessments__marks__student=student,
    ).distinct().order_by('-start_date')


class ReportsHomeView(AdminRequiredMixin, View):
    template_name = 'reports/home.html'
    page_title = 'Reports'

    def get(self, request, *args, **kwargs):
        return render(request, self.template_name, {
            'page_title': self.page_title,
            'school': _school_profile(),
            'class_stream_count': ClassStream.objects.count(),
            'term_count': Term.objects.count(),
        })


class ClassPerformanceView(ResultsReportAccessMixin, View):
    template_name = 'reports/class_performance.html'
    page_title = 'Class Performance'

    def get(self, request, *args, **kwargs):
        term = _resolve_term(request)
        class_stream = _resolve_class_stream(
            request, self.scoped_streams, term
        )
        return render(request, self.template_name, {
            'page_title': self.page_title,
            'school': _school_profile(),
            'term': term,
            'class_stream': class_stream,
            'report': (
                class_term_report(class_stream, term)
                if term and class_stream else None
            ),
            'filters': request.GET,
            'term_options': _term_options(),
            'class_stream_options': self.class_stream_choices(),
        })


class ClassPerformanceCsvView(ResultsReportAccessMixin, View):
    def get(self, request, *args, **kwargs):
        term = _resolve_term(request)
        class_stream = _resolve_class_stream(
            request, self.scoped_streams, term
        )
        if term is None or class_stream is None:
            return csv_response('class-performance.csv', ['No data'], [])
        headers, rows = class_performance_csv(
            class_term_report(class_stream, term)
        )
        return csv_response(
            f'class-performance-{term.pk}.csv', headers, rows
        )


class StudentReportCardView(StudentReportAccessMixin, View):
    template_name = 'reports/student_report.html'
    page_title = 'Student Report Card'

    def get(self, request, *args, **kwargs):
        term = student_term_choice(
            self.student, request.GET.get('term')
        )
        return render(request, self.template_name, {
            'page_title': self.page_title,
            'school': _school_profile(),
            'student': self.student,
            'term': term,
            'report': student_report(term, self.student) if term else None,
            'term_options': _student_term_options(self.student),
            'filters': request.GET,
        })


class StudentReportCardCsvView(StudentReportAccessMixin, View):
    def get(self, request, *args, **kwargs):
        term = student_term_choice(
            self.student, request.GET.get('term')
        )
        if term is None:
            return csv_response(
                f'student-report-{self.student.pk}.csv', ['No data'], []
            )
        headers, rows = student_report_csv(
            student_report(term, self.student)
        )
        return csv_response(
            f'student-report-{self.student.pk}-{term.pk}.csv',
            headers, rows,
        )


class AttendanceReportView(AttendanceReportAccessMixin, View):
    template_name = 'reports/attendance.html'
    page_title = 'Attendance Report'

    def get(self, request, *args, **kwargs):
        term = _resolve_term(request)
        class_stream = _resolve_class_stream(
            request, self.scoped_streams, term, prefer_records=True
        )
        return render(request, self.template_name, {
            'page_title': self.page_title,
            'school': _school_profile(),
            'term': term,
            'class_stream': class_stream,
            'report': (
                class_attendance_report(class_stream, term)
                if term and class_stream else None
            ),
            'filters': request.GET,
            'term_options': _term_options(),
            'class_stream_options': self.class_stream_choices(),
        })


class AttendanceCsvView(AttendanceReportAccessMixin, View):
    def get(self, request, *args, **kwargs):
        term = _resolve_term(request)
        class_stream = _resolve_class_stream(
            request, self.scoped_streams, term, prefer_records=True
        )
        if term is None or class_stream is None:
            return csv_response('attendance.csv', ['No data'], [])
        headers, rows = attendance_csv(
            class_attendance_report(class_stream, term)
        )
        return csv_response(f'attendance-{term.pk}.csv', headers, rows)


class ParentAttendanceReportView(ParentRequiredMixin, View):
    template_name = 'reports/attendance_my_children.html'
    page_title = 'Attendance — My Children'

    def get(self, request, *args, **kwargs):
        parent = Parent.objects.filter(user=request.user).first()
        children = (
            parent.children.select_related(
                'class_stream__school_class', 'class_stream__stream'
            ).order_by('admission_no')
            if parent else Student.objects.none()
        )
        term = _resolve_term(request)
        rows = [
            {
                'student': child,
                'summary': (
                    student_attendance_summary(child, term)
                    if term is not None else None
                ),
            }
            for child in children
        ]
        return render(request, self.template_name, {
            'page_title': self.page_title,
            'rows': rows,
            'term': term,
            'filters': request.GET,
            'term_options': _term_options(),
        })


class ChildAttendanceReportView(ParentRequiredMixin, View):
    template_name = 'reports/attendance_student.html'
    page_title = 'Student Attendance'

    def get(self, request, *args, **kwargs):
        self.student = get_object_or_404(
            Student.objects.select_related(
                'class_stream__school_class', 'class_stream__stream'
            ),
            pk=kwargs['pk'],
        )
        if not self.student.parents.filter(user=request.user).exists():
            raise PermissionDenied(
                'You do not have permission to view this student report.'
            )
        term = _resolve_term(request)
        records = []
        if term is not None:
            records = Attendance.objects.filter(
                student=self.student,
                date__gte=term.start_date,
                date__lte=term.end_date,
            ).select_related('class_stream__school_class', 'class_stream__stream').order_by('date')
        summary = (
            student_attendance_summary(self.student, term)
            if term is not None else None
        )
        return render(request, self.template_name, {
            'page_title': self.page_title,
            'student': self.student,
            'term': term,
            'records': records,
            'summary': summary,
            'filters': request.GET,
            'term_options': _term_options(),
        })


class FinanceReportView(AdminRequiredMixin, View):
    template_name = 'reports/finance.html'
    page_title = 'Finance Report'

    def get(self, request, *args, **kwargs):
        term = _resolve_term(request)
        scope = ClassStream.objects.select_related('school_class', 'stream')
        class_stream = _resolve_class_stream(request, scope, term)
        return render(request, self.template_name, {
            'page_title': self.page_title,
            'school': _school_profile(),
            'term': term,
            'class_stream': class_stream,
            'report': (
                class_finance_report(term, class_stream)
                if term and class_stream else None
            ),
            'filters': request.GET,
            'term_options': _term_options(),
            'class_stream_options': scope.order_by(
                'school_class__name', 'stream__name'
            ),
        })


class FinanceCsvView(AdminRequiredMixin, View):
    def get(self, request, *args, **kwargs):
        term = _resolve_term(request)
        scope = ClassStream.objects.select_related('school_class', 'stream')
        class_stream = _resolve_class_stream(request, scope, term)
        if term is None or class_stream is None:
            return csv_response('finance.csv', ['No data'], [])
        headers, rows = finance_csv(
            class_finance_report(term, class_stream)
        )
        return csv_response(f'finance-{term.pk}.csv', headers, rows)