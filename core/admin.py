from django.contrib import admin

from .models import (
    AcademicYear,
    ClassStream,
    Department,
    SchoolClass,
    SchoolProfile,
    Stream,
    Subject,
    Teacher,
    TeacherAssignment,
    Term,
)


@admin.register(SchoolProfile)
class SchoolProfileAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'email')


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'code')
    search_fields = ('name', 'code')


@admin.register(AcademicYear)
class AcademicYearAdmin(admin.ModelAdmin):
    list_display = ('name', 'start_date', 'end_date', 'is_current')
    list_filter = ('is_current',)


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ('name', 'year', 'start_date', 'end_date', 'is_current')
    list_filter = ('year', 'is_current')


@admin.register(SchoolClass)
class SchoolClassAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Stream)
class StreamAdmin(admin.ModelAdmin):
    list_display = ('name',)
    search_fields = ('name',)


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ('name', 'code')
    search_fields = ('name', 'code')


@admin.register(Teacher)
class TeacherAdmin(admin.ModelAdmin):
    list_display = ('employee_no', 'full_name', 'department', 'gender', 'is_active')
    list_filter = ('department', 'is_active', 'gender')
    search_fields = ('employee_no', 'first_name', 'last_name', 'email')
    filter_horizontal = ('classes',)


@admin.register(ClassStream)
class ClassStreamAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'class_teacher', 'students_count')
    list_filter = ('school_class',)
    search_fields = ('school_class__name', 'stream__name', 'class_teacher__first_name')
    filter_horizontal = ('subjects',)


@admin.register(TeacherAssignment)
class TeacherAssignmentAdmin(admin.ModelAdmin):
    list_display = ('teacher', 'class_stream', 'subject')
    list_filter = ('class_stream', 'subject')
    search_fields = ('teacher__first_name', 'teacher__last_name', 'subject__name')