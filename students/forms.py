from django import forms
from django.forms import inlineformset_factory
from django.utils.timezone import localdate

from core.models import ClassStream, SchoolClass, Stream
from .models import EnrollmentReason, Parent, Student, StudentParent


def _apply_bootstrap(fields):
    for field in fields.values():
        widget = field.widget
        if isinstance(widget, forms.Select):
            widget.attrs.setdefault('class', 'form-select')
        elif isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault('class', 'form-check-input')
        else:
            widget.attrs.setdefault('class', 'form-control')


class StudentForm(forms.ModelForm):
    class Meta:
        model = Student
        fields = [
            'admission_no', 'first_name', 'middle_name', 'last_name', 'gender',
            'date_of_birth', 'class_stream', 'date_admitted', 'status',
            'contact_name', 'contact_phone',
        ]
        widgets = {
            'date_of_birth': forms.DateInput(attrs={'type': 'date'}),
            'date_admitted': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)


class StudentParentForm(forms.ModelForm):
    class Meta:
        model = StudentParent
        fields = ['parent', 'relationship']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)


StudentParentFormSet = inlineformset_factory(
    Student,
    StudentParent,
    form=StudentParentForm,
    extra=2,
    can_delete=True,
)


class ParentCreateForm(forms.ModelForm):
    class Meta:
        model = Parent
        fields = ['first_name', 'last_name', 'phone', 'email', 'occupation']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)


class ParentForm(forms.ModelForm):
    class Meta:
        model = Parent
        fields = ['first_name', 'last_name', 'phone', 'email', 'occupation', 'address']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)


class StudentFilterForm(forms.Form):
    q = forms.CharField(
        required=False,
        label='Search',
        widget=forms.TextInput(attrs={
            'placeholder': 'Search by name or admission no.',
            'class': 'form-control',
        }),
    )
    school_class = forms.ModelChoiceField(
        queryset=SchoolClass.objects.all(),
        required=False,
        label='Class',
        empty_label='All classes',
    )
    stream = forms.ModelChoiceField(
        queryset=Stream.objects.all(),
        required=False,
        label='Stream',
        empty_label='All streams',
    )
    status = forms.ChoiceField(
        choices=[('', 'All statuses')] + Student.Status.choices,
        required=False,
        label='Status',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)


class PromoteForm(forms.Form):
    """Admin-only batch promotion form.

    ``students`` can be pre-filtered via the ``class_stream`` querystring so
    the checkbox list stays manageable.
    """

    target_class_stream = forms.ModelChoiceField(
        queryset=ClassStream.objects.filter(
            school_class__is_active=True,
        ).select_related('school_class', 'stream').order_by(
            'school_class__name', 'stream__name'
        ),
        label='Promote to class',
    )
    effective_date = forms.DateField(
        initial=localdate,
        label='Effective date',
        widget=forms.DateInput(attrs={'type': 'date'}),
    )
    reason = forms.ChoiceField(
        choices=EnrollmentReason.choices,
        initial=EnrollmentReason.PROMOTION,
        label='Reason',
        help_text='Defaults to Promotion; e.g. Reassignment covers same-level stream moves.',
    )
    note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'rows': 3}),
        help_text='Optional note recorded on every new enrollment window.',
    )
    students = forms.ModelMultipleChoiceField(
        queryset=Student.objects.filter(status=Student.Status.ACTIVE)
        .select_related('class_stream__school_class', 'class_stream__stream')
        .order_by('admission_no'),
        widget=forms.CheckboxSelectMultiple,
        label='Students to promote',
    )

    def __init__(self, *args, class_stream=None, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)
        if class_stream:
            self.fields['students'].queryset = Student.objects.filter(
                class_stream=class_stream,
                status=Student.Status.ACTIVE,
            ).select_related(
                'class_stream__school_class', 'class_stream__stream'
            ).order_by('admission_no')