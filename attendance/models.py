from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models

from students.services import student_in_class


class Attendance(models.Model):
    class Status(models.TextChoices):
        PRESENT = 'PRESENT', 'Present'
        ABSENT = 'ABSENT', 'Absent'
        LATE = 'LATE', 'Late'
        EXCUSED = 'EXCUSED', 'Excused'

    student = models.ForeignKey(
        'students.Student', on_delete=models.PROTECT, related_name='attendance',
    )
    class_stream = models.ForeignKey(
        'core.ClassStream', on_delete=models.PROTECT, related_name='attendance_records',
    )
    date = models.DateField()
    status = models.CharField(
        max_length=10, choices=Status.choices, default=Status.PRESENT,
    )
    notes = models.TextField(blank=True)
    recorded_by = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='recorded_attendance',
    )
    recorded_at = models.DateTimeField(auto_now=True)

    def clean(self):
        if (
            self.student_id
            and self.class_stream_id
            and not student_in_class(self.student, self.class_stream_id, when=self.date)
        ):
            raise ValidationError({
                'student': 'Student was not enrolled in this class stream on this date.',
            })

    class Meta:
        ordering = ['-date']
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'class_stream', 'date'],
                name='unique_daily_attendance',
            ),
        ]

    def __str__(self):
        return f'{self.student} - {self.date} - {self.get_status_display()}'