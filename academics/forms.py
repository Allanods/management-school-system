from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator

from core.models import (
    AcademicYear,
    ClassStream,
    SchoolClass,
    Subject,
    TeacherAssignment,
    Term,
)
from students.models import Student
from .models import Assessment, GradeBand


def _apply_bootstrap(fields):
    for field in fields.values():
        widget = field.widget
        if isinstance(widget, forms.Select):
            widget.attrs.setdefault('class', 'form-select')
        elif isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault('class', 'form-check-input')
        else:
            widget.attrs.setdefault('class', 'form-control')


class AcademicYearForm(forms.ModelForm):
    class Meta:
        model = AcademicYear
        fields = ['name', 'start_date', 'end_date', 'is_current']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)

    def save(self, commit=True):
        obj = super().save(commit=False)
        if obj.is_current:
            AcademicYear.objects.exclude(pk=obj.pk).update(is_current=False)
        if commit:
            obj.save()
        return obj


class TermForm(forms.ModelForm):
    class Meta:
        model = Term
        fields = ['name', 'year', 'start_date', 'end_date', 'is_current']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)

    def save(self, commit=True):
        obj = super().save(commit=False)
        if obj.is_current:
            Term.objects.exclude(pk=obj.pk).update(is_current=False)
        if commit:
            obj.save()
        return obj


class AssessmentForm(forms.ModelForm):
    class Meta:
        model = Assessment
        fields = [
            'name',
            'class_stream',
            'subject',
            'term',
            'assessment_type',
            'date',
            'max_marks',
            'weighting_percent',
            'status',
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)
        self.fields['class_stream'].queryset = ClassStream.objects.filter(
            school_class__is_active=True
        )
        self.fields['subject'].queryset = Subject.objects.filter(is_active=True)
        self.fields['term'].queryset = Term.objects.select_related('year').all()

    def clean(self):
        cleaned_data = super().clean()
        class_stream = cleaned_data.get('class_stream')
        subject = cleaned_data.get('subject')
        if class_stream and subject:
            if not TeacherAssignment.objects.filter(
                class_stream=class_stream, subject=subject
            ).exists():
                raise ValidationError(
                    f'No teacher is assigned to teach {subject.name} in {class_stream}. '
                    'Add a subject assignment to a teacher before creating an '
                    'assessment for this class and subject.'
                )
        return cleaned_data


class MarkEntryForm(forms.Form):
    student = forms.ModelChoiceField(
        queryset=Student.objects.none(), widget=forms.HiddenInput,
    )
    scored = forms.DecimalField(
        max_digits=6, decimal_places=2, required=False,
    )

    def __init__(self, *args, **kwargs):
        self.students = kwargs.pop('students', None)
        self.assessment = kwargs.pop('assessment', None)
        super().__init__(*args, **kwargs)
        if self.students is not None:
            self.fields['student'].queryset = self.students
        min_value = 0
        max_value = None
        if self.assessment is not None:
            max_value = self.assessment.max_marks
        validators = [MinValueValidator(min_value)]
        if max_value is not None:
            validators.append(MaxValueValidator(max_value))
        self.fields['scored'].validators = validators
        self.fields['scored'].widget.attrs.update(
            {'class': 'form-control', 'type': 'number', 'step': 'any', 'placeholder': 'Score'}
        )

    def clean_scored(self):
        scored = self.cleaned_data.get('scored')
        if scored is None:
            return None
        if self.assessment is not None and scored > self.assessment.max_marks:
            raise ValidationError(
                f'Marks must be between 0 and {self.assessment.max_marks}.'
            )
        return scored


class GradeBandForm(forms.ModelForm):
    class Meta:
        model = GradeBand
        fields = ['label', 'min_percent', 'max_percent', 'points', 'comment']
        widgets = {
            'min_percent': forms.NumberInput(attrs={'step': '0.01'}),
            'max_percent': forms.NumberInput(attrs={'step': '0.01'}),
            'points': forms.NumberInput(attrs={'step': '1'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)