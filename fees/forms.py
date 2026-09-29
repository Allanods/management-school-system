from django import forms

from core.models import ClassStream, Term
from students.models import Student
from .models import FeeCharge, FeePayment, StudentCharge, StudentFeeAccount


def _apply_bootstrap(fields):
    for field in fields.values():
        widget = field.widget
        if isinstance(widget, forms.Select):
            widget.attrs.setdefault('class', 'form-select')
        elif isinstance(widget, forms.CheckboxInput):
            widget.attrs.setdefault('class', 'form-check-input')
        else:
            widget.attrs.setdefault('class', 'form-control')


class FeeStructureForm(forms.ModelForm):
    class Meta:
        model = FeeCharge
        fields = ['class_stream', 'term', 'description', 'amount', 'is_active']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)
        self.fields['class_stream'].queryset = ClassStream.objects.select_related(
            'school_class', 'stream'
        ).order_by('school_class__name', 'stream__name')
        self.fields['term'].queryset = Term.objects.select_related('year')


class StudentChargeForm(forms.ModelForm):
    class Meta:
        model = StudentCharge
        fields = ['description', 'amount', 'date', 'notes']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)


class PaymentForm(forms.ModelForm):
    class Meta:
        model = FeePayment
        fields = ['amount', 'method', 'receipt_no', 'date', 'notes']

    def __init__(self, *args, **kwargs):
        self._account = kwargs.pop('account', None)
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)

    def clean(self):
        cleaned = super().clean()
        if self.errors:
            return cleaned
        receipt_no = cleaned.get('receipt_no')
        if receipt_no and self.instance.pk is None:
            if FeePayment.objects.filter(receipt_no=receipt_no).exists():
                self.add_error(
                    'receipt_no',
                    'A payment with this receipt number already exists.',
                )
        return cleaned


class PaymentVoidForm(forms.Form):
    void_reason = forms.CharField(
        widget=forms.Textarea(attrs={
            'rows': 3, 'class': 'form-control',
            'placeholder': 'Explain why this payment is being voided',
        }),
        label='Void reason',
    )


class GenerateChargesForm(forms.Form):
    class_stream = forms.ModelChoiceField(
        queryset=ClassStream.objects.select_related(
            'school_class', 'stream'
        ).order_by('school_class__name', 'stream__name'),
        label='Class stream',
        empty_label='Select a class stream',
    )
    term = forms.ModelChoiceField(
        queryset=Term.objects.select_related('year'),
        label='Term',
        empty_label='Select a term',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _apply_bootstrap(self.fields)