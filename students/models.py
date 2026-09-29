from datetime import date

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models


class Parent(models.Model):
    user = models.OneToOneField(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='parent',
    )
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    occupation = models.CharField(max_length=100, blank=True)
    address = models.TextField(blank=True)

    class Meta:
        ordering = ['first_name', 'last_name']

    @property
    def full_name(self):
        return f'{self.first_name} {self.last_name}'

    def __str__(self):
        return self.full_name


class Student(models.Model):
    class Gender(models.TextChoices):
        MALE = 'M', 'Male'
        FEMALE = 'F', 'Female'

    class Status(models.TextChoices):
        ACTIVE = 'ACTIVE', 'Active'
        INACTIVE = 'INACTIVE', 'Inactive'
        GRADUATED = 'GRADUATED', 'Graduated'
        TRANSFERRED = 'TRANSFERRED', 'Transferred'
        SUSPENDED = 'SUSPENDED', 'Suspended'

    user = models.OneToOneField(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='student',
    )
    admission_no = models.CharField(max_length=20, unique=True)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    gender = models.CharField(max_length=1, choices=Gender.choices)
    date_of_birth = models.DateField()
    class_stream = models.ForeignKey(
        'core.ClassStream', on_delete=models.PROTECT, related_name='students',
    )
    parents = models.ManyToManyField(
        Parent, through='StudentParent', related_name='children',
    )
    date_admitted = models.DateField()
    status = models.CharField(
        max_length=12, choices=Status.choices, default=Status.ACTIVE,
    )
    contact_name = models.CharField(max_length=100, blank=True)
    contact_phone = models.CharField(max_length=20, blank=True)

    class Meta:
        ordering = ['admission_no']

    @property
    def full_name(self):
        middle = f' {self.middle_name}' if self.middle_name else ''
        return f'{self.first_name}{middle} {self.last_name}'

    def __str__(self):
        return f'{self.admission_no} - {self.full_name}'


class EnrollmentReason(models.TextChoices):
    ADMISSION = 'ADMISSION', 'Admission'
    PROMOTION = 'PROMOTION', 'Promotion'
    REASSIGNMENT = 'REASSIGNMENT', 'Class reassignment'
    TRANSFER_IN = 'TRANSFER_IN', 'Transfer in'
    GRADUATION = 'GRADUATION', 'Graduation'


class StudentEnrollment(models.Model):
    """A student's membership window in a class stream.

    Windows are half-open intervals [start_date, end_date): the student is a
    member of ``class_stream`` on every date ``d`` where
    ``start_date <= d < end_date``. A null ``end_date`` means the membership
    is currently open. Chronological validity (end > start, no overlapping
    windows per student) is enforced in ``clean()``.
    """

    student = models.ForeignKey(
        Student, on_delete=models.PROTECT, related_name='enrollments',
    )
    class_stream = models.ForeignKey(
        'core.ClassStream', on_delete=models.PROTECT, related_name='enrollments',
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    reason = models.CharField(
        max_length=20, choices=EnrollmentReason.choices,
        default=EnrollmentReason.ADMISSION,
    )
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='created_enrollments',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['student', '-start_date', '-id']
        constraints = [
            models.UniqueConstraint(
                fields=['student'],
                condition=models.Q(end_date__isnull=True),
                name='unique_open_enrollment_per_student',
            ),
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(end_date__gt=models.F('start_date')),
                name='enrollment_end_after_or_open',
            ),
        ]
        indexes = [
            models.Index(
                fields=['student', 'start_date'],
                name='enrollment_student_start_idx',
            ),
            models.Index(
                fields=['class_stream', 'start_date'],
                name='enrollment_class_start_idx',
            ),
        ]

    @property
    def is_current(self):
        return self.end_date is None

    def clean(self):
        errors = {}
        if self.end_date is not None and self.end_date <= self.start_date:
            errors['end_date'] = 'End date must be after the start date.'
        if self.student_id:
            others = StudentEnrollment.objects.filter(
                student_id=self.student_id,
            ).exclude(pk=self.pk)
            start = self.start_date
            end = self.end_date or date.max
            for other in others:
                if start < (other.end_date or date.max) and end > other.start_date:
                    errors['end_date'] = (
                        'Overlaps with the enrollment for '
                        f'{other.class_stream} (from {other.start_date}).'
                    )
                    break
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        end = self.end_date or 'present'
        return f'{self.student} in {self.class_stream} [{self.start_date} - {end}]'


class StudentParent(models.Model):
    class Relationship(models.TextChoices):
        FATHER = 'FATHER', 'Father'
        MOTHER = 'MOTHER', 'Mother'
        GUARDIAN = 'GUARDIAN', 'Guardian'
        OTHER = 'OTHER', 'Other'

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='guardian_links')
    parent = models.ForeignKey(Parent, on_delete=models.CASCADE, related_name='children_links')
    relationship = models.CharField(
        max_length=10, choices=Relationship.choices, default=Relationship.GUARDIAN,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'parent'],
                name='unique_student_parent',
            ),
        ]

    def __str__(self):
        return f'{self.parent.full_name} - {self.student.full_name}'