from django.contrib import admin

from .models import Parent, Student, StudentParent


class StudentParentInline(admin.TabularInline):
    model = StudentParent
    extra = 0


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('admission_no', 'full_name', 'gender', 'class_stream', 'status')
    list_filter = ('status', 'gender', 'class_stream')
    search_fields = ('admission_no', 'first_name', 'last_name')
    inlines = (StudentParentInline,)


@admin.register(Parent)
class ParentAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'phone', 'email')
    search_fields = ('first_name', 'last_name', 'phone', 'email')
    inlines = (StudentParentInline,)


@admin.register(StudentParent)
class StudentParentAdmin(admin.ModelAdmin):
    list_display = ('student', 'parent', 'relationship')
    list_filter = ('relationship',)
    search_fields = ('student__first_name', 'student__last_name', 'parent__first_name', 'parent__last_name')