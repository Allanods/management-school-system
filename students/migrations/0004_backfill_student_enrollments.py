"""Idempotent, reversible backfill of StudentEnrollment.

Every student with no enrollment history gets a single open ADMISSION
enrollment starting on ``Student.date_admitted``. The reverse operation
deletes exactly those imported rows, leaving real enrollments untouched.
"""

from django.db import migrations

IMPORT_NOTE = 'Imported from legacy records'


def backfill(apps, schema_editor):
    Student = apps.get_model('students', 'Student')
    StudentEnrollment = apps.get_model('students', 'StudentEnrollment')

    for student in Student.objects.order_by('pk'):
        if StudentEnrollment.objects.filter(student_id=student.pk).exists():
            continue
        StudentEnrollment.objects.create(
            student_id=student.pk,
            class_stream_id=student.class_stream_id,
            start_date=student.date_admitted,
            end_date=None,
            reason='ADMISSION',
            note=IMPORT_NOTE,
        )


def reverse_backfill(apps, schema_editor):
    StudentEnrollment = apps.get_model('students', 'StudentEnrollment')
    StudentEnrollment.objects.filter(
        reason='ADMISSION',
        note=IMPORT_NOTE,
        created_by__isnull=True,
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('students', '0003_studentenrollment'),
    ]

    operations = [
        migrations.RunPython(backfill, reverse_backfill),
    ]