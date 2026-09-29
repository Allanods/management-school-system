from django import forms

from core.models import (
    ClassStream,
    SchoolClass,
    Stream,
    Subject,
    Teacher,
    TeacherAssignment,
)


def _apply_bootstrap(fields):
    for field in fields.values():
        widget = field.widget
        if isinstance(widget, forms.Select):
            widget.attrs.setdefault('class', 'form-select')
        elif isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault('class', 'form-check-input')
        else:
            widget.attrs.setdefault('class', 'form-control')


class ClassForm(forms.ModelForm):
    class Meta:
        model = SchoolClass
        fields = ['name', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)


class StreamForm(forms.ModelForm):
    class Meta:
        model = Stream
        fields = ['name']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)


class ClassStreamForm(forms.ModelForm):
    class Meta:
        model = ClassStream
        fields = ['school_class', 'stream', 'class_teacher', 'subjects']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)
        self.fields['school_class'].queryset = SchoolClass.objects.filter(
            is_active=True
        )
        self.fields['class_teacher'].queryset = Teacher.objects.filter(
            is_active=True
        )
        self.fields['subjects'].queryset = Subject.objects.filter(is_active=True)


class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ['name', 'code', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)


class TeacherAssignmentForm(forms.ModelForm):
    class Meta:
        model = TeacherAssignment
        fields = ['teacher', 'class_stream', 'subject']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)
        self.fields['teacher'].queryset = Teacher.objects.filter(is_active=True)
        self.fields['class_stream'].queryset = ClassStream.objects.filter(
            school_class__is_active=True
        )
        self.fields['subject'].queryset = Subject.objects.filter(is_active=True)