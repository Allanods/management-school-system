from django import forms

from students.models import Student
from .models import Attendance


class AttendanceStatusForm(forms.Form):
    student = forms.ModelChoiceField(
        queryset=Student.objects.none(),
        widget=forms.HiddenInput,
    )
    status = forms.ChoiceField(
        choices=Attendance.Status.choices,
        label='Status',
    )

    def __init__(self, *args, **kwargs):
        self.students = kwargs.pop('students', None)
        super().__init__(*args, **kwargs)
        if self.students is not None:
            self.fields['student'].queryset = self.students
        self.fields['status'].widget.attrs.update({'class': 'form-select'})

    def has_changed(self):
        """Every submitted row must be validated and re-saved, so never allow
        the formset's empty_permitted short-circuit to skip per-form cleaning."""
        return True


AttendanceFormSet = forms.formset_factory(AttendanceStatusForm, extra=0)