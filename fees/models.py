from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class FeeCharge(models.Model):
    class_stream = models.ForeignKey(
        'core.ClassStream', on_delete=models.PROTECT, related_name='fee_charges',
    )
    term = models.ForeignKey(
        'core.Term', on_delete=models.PROTECT, related_name='fee_charges',
    )
    description = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['class_stream', 'description']
        constraints = [
            models.UniqueConstraint(
                fields=['class_stream', 'term', 'description'],
                name='unique_fee_charge',
            ),
        ]

    def clean(self):
        if self.amount <= 0:
            raise ValidationError({'amount': 'Amount must be greater than zero.'})

    def __str__(self):
        return f'{self.class_stream} - {self.description}'


class StudentFeeAccount(models.Model):
    student = models.ForeignKey(
        'students.Student', on_delete=models.PROTECT, related_name='fee_accounts',
    )
    term = models.ForeignKey(
        'core.Term', on_delete=models.PROTECT, related_name='fee_accounts',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['student', 'term']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'term'],
                name='unique_student_term_account',
            ),
        ]

    @property
    def total_charged(self):
        """Total of the student's actual charges for this term."""
        total = StudentCharge.objects.filter(
            student=self.student, term=self.term
        ).aggregate(total=Sum('amount'))['total']
        return total or 0

    @property
    def total_paid(self):
        """Total of non-voided payments recorded against this account."""
        total = self.payments.filter(voided=False).aggregate(
            total=Sum('amount')
        )['total']
        return total or 0

    @property
    def balance(self):
        return self.total_charged - self.total_paid

    @property
    def in_credit(self):
        return self.balance < 0

    def __str__(self):
        return f'{self.student} - {self.term}'


class StudentCharge(models.Model):
    student = models.ForeignKey(
        'students.Student', on_delete=models.PROTECT, related_name='student_charges',
    )
    term = models.ForeignKey(
        'core.Term', on_delete=models.PROTECT, related_name='student_charges',
    )
    fee_structure = models.ForeignKey(
        'FeeCharge', null=True, blank=True, on_delete=models.PROTECT,
        related_name='student_charges',
    )
    description = models.CharField(max_length=100)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    date = models.DateField(default=timezone.localdate)
    created_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='recorded_charges',
    )
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['date', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'term', 'fee_structure'],
                name='unique_generated_charge',
            ),
            models.CheckConstraint(
                condition=models.Q(amount__gt=0),
                name='charge_amount_positive',
            ),
        ]

    def clean(self):
        errors = {}
        if self.amount <= 0:
            errors['amount'] = 'Amount must be greater than zero.'
        if self.date and self.date > timezone.localdate():
            errors['date'] = 'Charge date cannot be in the future.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.student} - {self.description}'


class FeePayment(models.Model):
    class Method(models.TextChoices):
        CASH = 'CASH', 'Cash'
        MPESA = 'MPESA', 'M-Pesa'
        BANK = 'BANK', 'Bank Transfer'
        CHEQUE = 'CHEQUE', 'Cheque'
        OTHER = 'OTHER', 'Other'

    account = models.ForeignKey(
        StudentFeeAccount, on_delete=models.PROTECT, related_name='payments',
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(
        max_length=10, choices=Method.choices, default=Method.CASH,
    )
    receipt_no = models.CharField(max_length=30, unique=True, null=True, blank=True)
    recorded_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='recorded_payments',
    )
    date = models.DateField(default=timezone.localdate)
    notes = models.TextField(blank=True)
    voided = models.BooleanField(default=False)
    void_reason = models.TextField(blank=True)
    voided_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='voided_payments',
    )

    class Meta:
        ordering = ['-date', '-id']

    def clean(self):
        errors = {}
        if self.amount <= 0:
            errors['amount'] = 'Amount must be greater than zero.'
        if self.date > timezone.localdate():
            errors['date'] = 'Payment date cannot be in the future.'
        if self.voided and not self.void_reason.strip():
            errors['void_reason'] = 'A reason is required to void a payment.'
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.account.student} - {self.amount}'