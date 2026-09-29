import re
from datetime import date

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils.timezone import localdate

from core.models import ClassStream
from .models import EnrollmentReason, Student, StudentEnrollment


def suggest_admission_no(admission_date=None):
    """Next admission number for the year, e.g. '2026/001'.

    Sequence is derived from the highest existing number (max + 1), never
    from gaps, so a number previously used is never re-proposed. Final
    uniqueness is still enforced by the database on Student.admission_no.
    """
    admission_date = admission_date or date.today()
    prefix = f'{admission_date.year}/'
    pattern = re.compile(r'^\d{4}/(\d+)$')
    last_seq = 0
    for value in Student.objects.filter(admission_no__startswith=prefix).values_list('admission_no', flat=True):
        match = pattern.match(value)
        if match:
            last_seq = max(last_seq, int(match.group(1)))
    return f'{prefix}{last_seq + 1:03d}'


def has_enrollment_history(student):
    return student.enrollments.exists()


def enrollment_on(student, when=None):
    """The enrollment window covering ``when`` (default: today), or None."""
    when = when or localdate()
    return (
        student.enrollments
        .filter(start_date__lte=when)
        .filter(Q(end_date__isnull=True) | Q(end_date__gt=when))
        .order_by('-start_date', '-id')
        .first()
    )


def get_class_roster(class_stream, when=None, include_inactive=False):
    """ACTIVE students who are members of ``class_stream`` on ``when``.

    Membership is enrollment-backed. Students with no enrollment history fall
    back to the legacy rule: they belong to their current Student.class_stream.
    Inactive students are always excluded unless ``include_inactive`` is True.
    """
    when = when or localdate()
    cs_id = class_stream.pk if isinstance(class_stream, ClassStream) else class_stream
    member_ids = set(
        StudentEnrollment.objects.filter(
            class_stream_id=cs_id,
            start_date__lte=when,
        )
        .filter(Q(end_date__isnull=True) | Q(end_date__gt=when))
        .values_list('student_id', flat=True)
    )
    member_ids |= set(
        Student.objects.filter(class_stream_id=cs_id)
        .exclude(pk__in=StudentEnrollment.objects.values_list('student_id', flat=True))
        .values_list('pk', flat=True)
    )
    students = Student.objects.filter(pk__in=member_ids).order_by('admission_no')
    if not include_inactive:
        students = students.filter(status=Student.Status.ACTIVE)
    return students


def get_class_roster_for_term(class_stream, term, include_inactive=False):
    """ACTIVE students whose enrollment window overlaps ``term``.

    Windows are half-open, so every term date is covered. A student promoted
    mid-term is reported for both classes whose windows overlap the term.
    Enrollment-less students use the legacy current-class rule.
    """
    cs_id = class_stream.pk if isinstance(class_stream, ClassStream) else class_stream
    member_ids = set(
        StudentEnrollment.objects.filter(class_stream_id=cs_id)
        .filter(Q(end_date__isnull=True) | Q(end_date__gt=term.start_date))
        .filter(start_date__lt=term.end_date)
        .values_list('student_id', flat=True)
    )
    member_ids |= set(
        Student.objects.filter(class_stream_id=cs_id)
        .exclude(pk__in=StudentEnrollment.objects.values_list('student_id', flat=True))
        .values_list('pk', flat=True)
    )
    students = Student.objects.filter(pk__in=member_ids).order_by('admission_no')
    if not include_inactive:
        students = students.filter(status=Student.Status.ACTIVE)
    return students


def student_in_class(student, class_stream, when=None):
    """Membership predicate for validators (no status filtering).

    Enrollment-backed when the student has history; otherwise the legacy
    current-class rule for backward compatibility.
    """
    when = when or localdate()
    cs_id = class_stream.pk if isinstance(class_stream, ClassStream) else class_stream
    enrollment = enrollment_on(student, when)
    if enrollment is None:
        if has_enrollment_history(student):
            return False
        return student.class_stream_id == cs_id
    return enrollment.class_stream_id == cs_id


def _as_date(value):
    """Coerce to a date. Freshly created model instances keep the raw value
    passed to ``objects.create`` until re-fetched, so helpers must normalize
    before date arithmetic."""
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def validate_promotion(*, target_class_stream, students, effective_date=None, actor=None):
    """Validate a batch promotion, returning [(student, message)] problems.

    An empty list means the promotion is valid. The effective date must fall
    inside the student's current open enrollment so the promotion only splits
    the active window into two contiguous half-open intervals.
    """
    effective = _as_date(effective_date or localdate())
    problems = []
    for student in students:
        if student.status != Student.Status.ACTIVE:
            problems.append((student, 'Only active students can be promoted.'))
            continue
        if student.class_stream_id == target_class_stream.pk:
            problems.append((student, 'Already a member of the target class.'))
            continue
        if effective < _as_date(student.date_admitted):
            problems.append((student, 'Effective date is before the admission date.'))
            continue
        current = enrollment_on(student, effective)
        if current is None or current.end_date is not None:
            problems.append(
                (student, 'No open enrollment covers the effective date.'),
            )
            continue
    return problems


def promote_student(*, actor, student, target_class_stream, effective_date=None,
                    reason=EnrollmentReason.PROMOTION, note=''):
    """Promote one student, closing the old window and opening the new one.

    Run in its own transaction with a row lock on the student. The existing
    window is closed *before* the new one opens so the half-open invariants
    hold at every step.
    """
    effective = _as_date(effective_date or localdate())
    problems = validate_promotion(
        target_class_stream=target_class_stream,
        students=[student],
        effective_date=effective,
    )
    if problems:
        raise ValidationError(
            [f'{problems[0][0].admission_no}: {problems[0][1]}'],
        )
    with transaction.atomic():
        locked = Student.objects.select_for_update().get(pk=student.pk)
        current = enrollment_on(locked, effective)
        if current is not None:
            current.end_date = effective
            current.save(update_fields=['end_date', 'updated_at'])
        new_enrollment = StudentEnrollment.objects.create(
            student=locked,
            class_stream=target_class_stream,
            start_date=effective,
            end_date=None,
            reason=reason,
            note=note,
            created_by=actor,
        )
        locked.class_stream = target_class_stream
        locked.save(update_fields=['class_stream'])
    return new_enrollment


def promote_students(*, actor, students, target_class_stream, effective_date=None,
                     reason=EnrollmentReason.PROMOTION, note=''):
    """Promote a batch of students atomically (all-or-nothing)."""
    students = list(students)
    effective = _as_date(effective_date or localdate())
    problems = validate_promotion(
        target_class_stream=target_class_stream,
        students=students,
        effective_date=effective,
    )
    if problems:
        raise ValidationError(
            [f'{s.admission_no}: {msg}' for s, msg in problems],
        )
    with transaction.atomic():
        created = [
            promote_student(
                actor=actor, student=student,
                target_class_stream=target_class_stream,
                effective_date=effective, reason=reason, note=note,
            )
            for student in students
        ]
    return created


def correct_enrollment(*, actor, enrollment, **edits):
    """Admins-only correction of a (typically closed) enrollment.

    Allowed edits: ``end_date``, ``reason``, ``note``, ``class_stream``.
    ``created_by`` and timestamps are preserved for audit trail.
    """
    allowed = {'end_date', 'reason', 'note', 'class_stream'}
    payload = {key: value for key, value in edits.items() if key in allowed}
    if 'end_date' in payload and payload['end_date'] is not None:
        if payload['end_date'] <= enrollment.start_date:
            raise ValidationError('End date must be after the start date.')
    for key, value in payload.items():
        setattr(enrollment, key, value)
    enrollment.save()
    return enrollment


def record_admission(student, user=None, start_date=None):
    """Open an ADMISSION enrollment for a newly admitted student.

    Idempotent: does nothing when the student already has enrollment history.
    """
    if student.enrollments.exists():
        return None
    return StudentEnrollment.objects.create(
        student=student,
        class_stream=student.class_stream,
        start_date=start_date or student.date_admitted,
        end_date=None,
        reason=EnrollmentReason.ADMISSION,
        created_by=user,
    )


def record_class_change(student, new_class_stream, user=None, when=None):
    """Close the current window and open a REASSIGNMENT window for a class change.

    The caller is responsible for deciding a change is warranted; this always
    splits the windows so the service is correct standalone too. The student's
    current ``class_stream`` is kept in sync with the new open window.
    """
    when = _as_date(when or localdate())
    with transaction.atomic():
        current = student.enrollments.filter(end_date__isnull=True).first()
        if current is not None:
            if when <= _as_date(current.start_date):
                raise ValidationError(
                    'Class change date must be after the current start date.',
                )
            current.end_date = when
            current.save(update_fields=['end_date', 'updated_at'])
        enrollment = StudentEnrollment.objects.create(
            student=student,
            class_stream=new_class_stream,
            start_date=when,
            end_date=None,
            reason=EnrollmentReason.REASSIGNMENT,
            created_by=user,
        )
        student.class_stream = new_class_stream
        student.save(update_fields=['class_stream'])
        return enrollment