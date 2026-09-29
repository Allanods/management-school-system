from django.urls import path

from .views import (
    AttendanceHistoryView,
    AttendanceHomeView,
    AttendanceSheetView,
    ParentChildrenAttendanceView,
    StudentAttendanceView,
    TakeAttendanceView,
)

app_name = 'attendance'

urlpatterns = [
    path('', AttendanceHomeView.as_view(), name='home'),
    path('take/', TakeAttendanceView.as_view(), name='take'),
    path('sheet/', AttendanceSheetView.as_view(), name='sheet'),
    path('history/', AttendanceHistoryView.as_view(), name='history'),
    path('my-children/', ParentChildrenAttendanceView.as_view(), name='my_children'),
    path('student/<int:pk>/', StudentAttendanceView.as_view(), name='student'),
]