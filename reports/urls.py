from django.urls import path

from .views import (
    AttendanceCsvView,
    AttendanceReportView,
    ChildAttendanceReportView,
    ClassPerformanceCsvView,
    ClassPerformanceView,
    FinanceCsvView,
    FinanceReportView,
    ParentAttendanceReportView,
    ReportsHomeView,
    StudentReportCardCsvView,
    StudentReportCardView,
)

app_name = 'reports'

urlpatterns = [
    path('', ReportsHomeView.as_view(), name='home'),
    path(
        'class-performance/',
        ClassPerformanceView.as_view(), name='class_performance',
    ),
    path(
        'class-performance.csv',
        ClassPerformanceCsvView.as_view(), name='class_performance_csv',
    ),
    path(
        'students/<int:pk>/report/',
        StudentReportCardView.as_view(), name='student_report',
    ),
    path(
        'students/<int:pk>/report.csv',
        StudentReportCardCsvView.as_view(), name='student_report_csv',
    ),
    path('attendance/', AttendanceReportView.as_view(), name='attendance'),
    path('attendance.csv', AttendanceCsvView.as_view(), name='attendance_csv'),
    path(
        'attendance/my-children/',
        ParentAttendanceReportView.as_view(), name='attendance_my_children',
    ),
    path(
        'attendance/children/<int:pk>/',
        ChildAttendanceReportView.as_view(), name='attendance_child',
    ),
    path('finance/', FinanceReportView.as_view(), name='finance'),
    path('finance.csv', FinanceCsvView.as_view(), name='finance_csv'),
]