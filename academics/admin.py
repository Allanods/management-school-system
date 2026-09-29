from django.contrib import admin

from .models import Assessment, GradeBand, Mark


@admin.register(Assessment)
class AssessmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'term', 'class_stream', 'subject', 'assessment_type', 'max_marks', 'status')
    list_filter = ('term', 'class_stream', 'subject', 'status')


@admin.register(Mark)
class MarkAdmin(admin.ModelAdmin):
    list_display = ('student', 'assessment', 'subject', 'scored')
    list_filter = ('assessment', 'subject')
    search_fields = ('student__admission_no', 'student__first_name', 'student__last_name')


@admin.register(GradeBand)
class GradeBandAdmin(admin.ModelAdmin):
    list_display = ('label', 'min_percent', 'max_percent', 'points', 'comment')