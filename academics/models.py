from django.core.exceptions import ValidationError
from django.db import models

from students.services import student_in_class


class Assessment(models.Model):
    class AssessmentType(models.TextChoices):
        CAT = 'CAT', 'CAT'
        MID_TERM = 'MID_TERM', 'Mid-Term'
        END_TERM = 'END_TERM', 'End-Term'
        OTHER = 'OTHER', 'Other'

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        PUBLISHED = 'PUBLISHED', 'Published'

    name = models.CharField(max_length=30)
    term = models.ForeignKey(
        'core.Term', on_delete=models.PROTECT, related_name='assessments',
    )
    class_stream = models.ForeignKey(
        'core.ClassStream', on_delete=models.PROTECT,
        related_name='academic_assessments',
    )
    subject = models.ForeignKey(
        'core.Subject', on_delete=models.PROTECT,
        related_name='academic_assessments',
    )
    assessment_type = models.CharField(
        max_length=15, choices=AssessmentType.choices, default=AssessmentType.CAT,
    )
    date = models.DateField(blank=True, null=True)
    max_marks = models.DecimalField(max_digits=6, decimal_places=2, default=100)
    weighting_percent = models.PositiveSmallIntegerField(default=100)
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.DRAFT,
    )

    class Meta:
        ordering = ['term', 'class_stream', 'subject', 'name']
        constraints = [
            models.UniqueConstraint(
                fields=['term', 'class_stream', 'subject', 'name'],
                name='unique_assessment_per_class_subject',
            ),
        ]

    def clean(self):
        if self.max_marks <= 0:
            raise ValidationError({'max_marks': 'Maximum marks must be greater than zero.'})

    def __str__(self):
        return f'{self.name} ({self.class_stream} - {self.subject})'


class Mark(models.Model):
    student = models.ForeignKey(
        'students.Student', on_delete=models.PROTECT, related_name='marks',
    )
    assessment = models.ForeignKey(
        Assessment, on_delete=models.PROTECT, related_name='marks',
    )
    subject = models.ForeignKey(
        'core.Subject', on_delete=models.PROTECT, related_name='marks',
    )
    scored = models.DecimalField(max_digits=6, decimal_places=2)

    class Meta:
        ordering = ['student__admission_no']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'assessment', 'subject'],
                name='unique_mark',
            ),
        ]

    def clean(self):
        errors = {}
        if self.scored < 0 or self.scored > self.assessment.max_marks:
            errors['scored'] = (
                f'Marks must be between 0 and {self.assessment.max_marks}.'
            )
        if self.subject_id and self.assessment_id:
            if self.subject_id != self.assessment.subject_id:
                errors['subject'] = (
                    'Subject must match the assessment subject '
                    f'({self.assessment.subject.name}).'
                )
        if self.student_id and self.assessment_id:
            when = self.assessment.date or self.assessment.term.start_date
            if not student_in_class(self.student, self.assessment.class_stream_id, when=when):
                errors['student'] = (
                    'Student was not enrolled in the class stream this assessment '
                    f'belongs to ({self.assessment.class_stream}) on {when}.'
                )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.student} - {self.subject.name}: {self.scored}'


class GradeBand(models.Model):
    label = models.CharField(max_length=2, unique=True)
    min_percent = models.DecimalField(max_digits=5, decimal_places=2)
    max_percent = models.DecimalField(max_digits=5, decimal_places=2)
    points = models.PositiveSmallIntegerField()
    comment = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ['min_percent']

    def clean(self):
        errors = {}
        if self.min_percent >= self.max_percent:
            errors['min_percent'] = 'Minimum percentage must be less than the maximum.'
        overlap = GradeBand.objects.exclude(pk=self.pk).filter(
            min_percent__lt=self.max_percent,
            max_percent__gt=self.min_percent,
        )
        if overlap.exists():
            errors['min_percent'] = (
                'Grade band overlaps with an existing band. Bands must not share '
                'any percentage range.'
            )
        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f'{self.label} ({self.min_percent}-{self.max_percent})'