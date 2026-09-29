from django.contrib import admin

from .models import Attendance


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('student', 'class_stream', 'date', 'status', 'recorded_by')
    list_filter = ('status', 'date', 'class_stream')
    search_fields = ('student__admission_no', 'student__first_name', 'student__last_name')