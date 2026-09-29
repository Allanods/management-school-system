from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from math import ceil

from django.db.models import Q

from academics.models import Assessment, Mark
from academics.services import grade_for_percentage, student_term_results
from attendance.models import Attendance
from core.models import ClassStream, Term
from core.services import teacher_authorized_class_streams
from students.models import Student
from students.services import (
    enrollment_on,
    get_class_roster_for_term,
    has_enrollment_history,
)

ZERO = Decimal('0')

# Approved ranking-eligibility rule (Phase 12B): a student is rankable in a
# (class_stream, term) when they have published marks on at least ceil(50%)
# of the window-relevant published assessments AND on at least ceil(50%) of
# the distinct subjects covered by those assessments.
RANKING_MIN_ASSESSMENT_COVERAGE = Decimal('0.50')
RANKING_MIN_SUBJECT_COVERAGE = Decimal('0.50')


def _as_date(value):
    """Coerce to a date. Fields created in-process with a string keep the
    raw string until re-fetched, so helpers must normalize before arithmetic."""
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        return value
    return date.fromisoformat(str(value))


def _effective_date(assessment):
    return _as_date(assessment.date or assessment.term.start_date)


def _published_assessments(class_stream, term):
    return list(
        Assessment.objects.filter(
            class_stream=class_stream,
            term=term,
            status=Assessment.Status.PUBLISHED,
        ).select_related('subject', 'term')
    )


def _inclusive_member_end(enrollment):
    """Last calendar day of membership. Enrollment windows are half-open
    [start_date, end_date), so the inclusive last day is end_date - 1."""
    end = _as_date(enrollment.end_date)
    if end is None:
        return date.max
    return end - timedelta(days=1)


def membership_overlap(student, class_stream, term):
    """Inclusive membership day-ranges of ``student`` inside ``class_stream``
    that overlap ``term``, or an empty list when there is none.

    Enrollment-backed whenever the student has enrollment history. Students
    without history use the legacy rule: they belong to the class for the
    whole term when their current ``Student.class_stream`` matches.
    """
    cs_id = getattr(class_stream, 'pk', class_stream)
    term_start = _as_date(term.start_date)
    term_end = _as_date(term.end_date)
    if has_enrollment_history(student):
        windows = []
        for enrollment in student.enrollments.filter(class_stream_id=cs_id):
            start = max(_as_date(enrollment.start_date), term_start)
            end = min(_inclusive_member_end(enrollment), term_end)
            if start <= end:
                windows.append((start, end))
        return windows
    if student.class_stream_id == cs_id:
        return [(term_start, term_end)]
    return []


def _is_in_window(effective_date, window):
    start, end = window
    if effective_date < start:
        return False
    if effective_date > end:
        return False
    return True


def membership_assessments(class_stream, term, student):
    """Published assessments of (class_stream, term) whose effective date falls
    inside at least one of the student's membership windows. Mid-term
    promotees therefore only see assessments relevant to the class they were
    in on the assessment date."""
    windows = membership_overlap(student, class_stream, term)
    if not windows:
        return []
    return [
        assessment
        for assessment in _published_assessments(class_stream, term)
        if any(_is_in_window(_effective_date(assessment), window) for window in windows)
    ]


def _required_target(total, coverage):
    return int(ceil(Decimal(total) * coverage))


def eligibility_data(student, assessments):
    """Coverage data for one student against a set of window-relevant
    published assessments.

    Returns (eligible, info) where info carries the coverage counts used by
    the views and the CSV exports.
    """
    total = len(assessments)
    if total == 0:
        return False, {
            'records': 0,
            'records_required': 0,
            'subjects': 0,
            'subjects_required': 0,
            'total': 0,
            'total_subjects': 0,
        }
    subject_ids = {assessment.subject_id for assessment in assessments}
    recorded_ids = set(
        Mark.objects.filter(
            student=student,
            assessment_id__in=[assessment.pk for assessment in assessments],
        ).values_list('assessment_id', flat=True)
    )
    recorded = [
        assessment for assessment in assessments
        if assessment.pk in recorded_ids
    ]
    records = len(recorded)
    subjects = len({assessment.subject_id for assessment in recorded})
    records_required = _required_target(total, RANKING_MIN_ASSESSMENT_COVERAGE)
    subjects_required = _required_target(
        len(subject_ids), RANKING_MIN_SUBJECT_COVERAGE
    )
    eligible = records >= records_required and subjects >= subjects_required
    return eligible, {
        'records': records,
        'records_required': records_required,
        'subjects': subjects,
        'subjects_required': subjects_required,
        'total': total,
        'total_subjects': len(subject_ids),
    }


def _scored_totals(student, assessments):
    """Class-scoped (scored, max) sums over the given published assessments."""
    if not assessments:
        return ZERO, ZERO
    marks = Mark.objects.filter(
        student=student,
        assessment_id__in=[assessment.pk for assessment in assessments],
        assessment__status=Assessment.Status.PUBLISHED,
    ).select_related('assessment')
    scored = ZERO
    max_marks = ZERO
    for mark in marks:
        scored += mark.scored
        max_marks += mark.assessment.max_marks
    return scored, max_marks


def class_term_ranking(class_stream, term):
    """Eligible students of (class_stream, term) ranked by their class-scoped
    overall percentage using standard competition ranking (1, 2, 2, 4).

    The rank key is the exact Decimal overall percent with ties broken by
    admission number ascending, so output is deterministic.
    """
    roster = get_class_roster_for_term(class_stream, term, include_inactive=True)
    rows = []
    for student in roster:
        assessments = membership_assessments(class_stream, term, student)
        eligible, info = eligibility_data(student, assessments)
        if not eligible:
            continue
        scored, max_marks = _scored_totals(student, assessments)
        overall = (scored / max_marks * 100) if max_marks else ZERO
        rows.append({
            'student': student,
            'student_id': student.pk,
            'admission_no': student.admission_no,
            'full_name': student.full_name,
            'overall_percent': overall,
            'overall_grade': grade_for_percentage(overall),
            **info,
        })
    rows.sort(key=lambda row: (-row['overall_percent'], row['admission_no']))
    position = 0
    previous = None
    for row in rows:
        position += 1
        if (
            previous is not None
            and row['overall_percent'] == previous['overall_percent']
        ):
            row['position'] = previous['position']
        else:
            row['position'] = position
        previous = row
    return rows


def _subject_averages(class_stream, term, roster_ids):
    """Per-subject averages over students with recorded marks, for a class and
    term. Students without a mark in the subject are counted (not averaged)."""
    published = _published_assessments(class_stream, term)
    by_subject = {}
    for assessment in published:
        by_subject.setdefault(
            assessment.subject_id, {'subject': assessment.subject}
        ).setdefault('assessments', []).append(assessment)

    averages = []
    for group in by_subject.values():
        assessment_ids = [a.pk for a in group['assessments']]
        marks = (
            Mark.objects.filter(
                assessment_id__in=assessment_ids,
                assessment__status=Assessment.Status.PUBLISHED,
            )
            .select_related('student')
        )
        scored = defaultdict(lambda: ZERO)
        max_marks = defaultdict(lambda: ZERO)
        with_marks = set()
        for mark in marks:
            scored[mark.student_id] += mark.scored
            max_marks[mark.student_id] += mark.assessment.max_marks
            with_marks.add(mark.student_id)
        with_marks &= roster_ids

        if not with_marks:
            averages.append({
                'subject': group['subject'],
                'assessment_count': len(assessment_ids),
                'average_percent': None,
                'students_with_marks': 0,
                'no_mark_count': len(roster_ids),
            })
            continue

        total_scored = sum(scored[sid] for sid in with_marks)
        total_max = sum(max_marks[sid] for sid in with_marks)
        averages.append({
            'subject': group['subject'],
            'assessment_count': len(assessment_ids),
            'average_percent': (total_scored / total_max * 100) if total_max else ZERO,
            'students_with_marks': len(with_marks),
            'no_mark_count': len(roster_ids) - len(with_marks),
        })
    averages.sort(key=lambda group: group['subject'].name)
    return averages


def class_term_report(class_stream, term):
    """Full class+term performance report used by the HTML page and the CSV.

    Combines the ranking (eligible students only), the full roster (including
    students without published results, flagged), subject averages over
    students with recorded marks, and an aggregate summary.
    """
    roster = list(
        get_class_roster_for_term(class_stream, term, include_inactive=True)
    )
    ranking = class_term_ranking(class_stream, term)
    by_student = {row['student_id']: row for row in ranking}

    rows = []
    for student in roster:
        row = by_student.get(student.pk)
        rows.append({
            'student': student,
            'is_inactive': student.status != Student.Status.ACTIVE,
            'eligible': bool(row),
            'position': row['position'] if row else None,
            'ranked_count': len(ranking),
            'overall_percent': row['overall_percent'] if row else None,
            'overall_grade': row['overall_grade'] if row else None,
            'records': row['records'] if row else 0,
            'records_required': row['records_required'] if row else 0,
            'total': row['total'] if row else 0,
            'subjects': row['subjects'] if row else 0,
            'subjects_required': row['subjects_required'] if row else 0,
        })

    percents = [row['overall_percent'] for row in ranking]
    summary = {
        'roster_count': len(roster),
        'ranked_count': len(percents),
        'average_percent': (sum(percents) / len(percents)) if percents else None,
        'highest_percent': max(percents) if percents else None,
        'lowest_percent': min(percents) if percents else None,
    }

    return {
        'class_stream': class_stream,
        'term': term,
        'rows': rows,
        'subject_averages': _subject_averages(
            class_stream, term, {student.pk for student in roster}
        ),
        'summary': summary,
    }


def _student_term_classes(student, term):
    """Class streams the student belonged to during ``term`` (enrollment
    backed; legacy current-class fallback)."""
    if has_enrollment_history(student):
        cs_ids = (
            student.enrollments
            .filter(start_date__lt=term.end_date)
            .filter(Q(end_date__isnull=True) | Q(end_date__gt=term.start_date))
            .values_list('class_stream_id', flat=True)
        )
        return list(
            ClassStream.objects.filter(pk__in=list(cs_ids)).select_related(
                'school_class', 'stream'
            )
        )
    if student.class_stream_id:
        return [student.class_stream]
    return []


def student_report(term, student):
    """Report-card payload for one student and term: the per-subject results
    (reused from the academics service) plus a rank for every class the
    student belonged to during the term."""
    results = student_term_results(student, term)
    ranks = []
    for class_stream in _student_term_classes(student, term):
        ranking = class_term_ranking(class_stream, term)
        own = next(
            (row for row in ranking if row['student_id'] == student.pk), None
        )
        ranks.append({
            'class_stream': class_stream,
            'position': own['position'] if own else None,
            'ranked_count': len(ranking),
            'overall_percent': own['overall_percent'] if own else None,
            'overall_grade': own['overall_grade'] if own else None,
            'records': own['records'] if own else 0,
            'records_required': own['records_required'] if own else 0,
            'total': own['total'] if own else 0,
        })
    return {
        'student': student,
        'term': term,
        'results': results,
        'ranks': ranks,
    }


def student_term_choice(student, term_id=None):
    """Resolve the term for a student report: explicit selection, else the
    current term when it has published results, else the most recent term
    with published results for the student."""
    options = Term.objects.filter(
        assessments__status=Assessment.Status.PUBLISHED,
        assessments__marks__student=student,
    ).distinct().order_by('-start_date')
    if term_id:
        term = options.filter(pk=term_id).first()
        if term:
            return term
    current = Term.objects.filter(is_current=True).first()
    if current and options.filter(pk=current.pk).exists():
        return current
    return options.first()


def student_in_teacher_result_scope(teacher, student, term):
    """Whether a teacher may open ``student``'s report for ``term``: the
    student must belong to one of the teacher's result streams. ``term`` may
    be None, in which case current membership is checked."""
    allowed_ids = set(
        teacher_authorized_class_streams(teacher).values_list('pk', flat=True)
    )
    if term is None:
        if student.class_stream_id in allowed_ids:
            return True
        current = enrollment_on(student)
        return (
            current is not None
            and current.class_stream_id in allowed_ids
        )
    for cs_id in allowed_ids:
        if membership_overlap(student, cs_id, term):
            return True
    return False


def class_attendance_report(class_stream, term):
    """Term attendance report for one class: per-student status counts with
    percentage over the student's recorded days, plus a daily roll-up."""
    roster = list(
        get_class_roster_for_term(class_stream, term, include_inactive=True)
    )
    records = list(
        Attendance.objects.filter(
            class_stream=class_stream,
            date__gte=term.start_date,
            date__lte=term.end_date,
        ).select_related('student')
    )
    by_student = defaultdict(list)
    for record in records:
        by_student[record.student_id].append(record)

    rows = []
    for student in roster:
        per = {'PRESENT': 0, 'ABSENT': 0, 'LATE': 0, 'EXCUSED': 0}
        recorded_days = set()
        for record in by_student.get(student.pk, []):
            per[record.status] += 1
            recorded_days.add(record.date)
        recorded_days = len(recorded_days)
        attended = per['PRESENT'] + per['LATE']
        rows.append({
            'student': student,
            'is_inactive': student.status != Student.Status.ACTIVE,
            'present': per['PRESENT'],
            'late': per['LATE'],
            'absent': per['ABSENT'],
            'excused': per['EXCUSED'],
            'recorded_days': recorded_days,
            'percent': (attended / recorded_days * 100) if recorded_days else None,
        })

    daily = []
    for day in sorted({record.date for record in records}):
        per = {'PRESENT': 0, 'ABSENT': 0, 'LATE': 0, 'EXCUSED': 0}
        for record in records:
            if record.date == day:
                per[record.status] += 1
        daily.append({'date': day, **per})

    return {
        'class_stream': class_stream,
        'term': term,
        'rows': rows,
        'days_with_records': len(daily),
        'daily': daily,
    }


def student_attendance_summary(student, term):
    """Per-student attendance for a term, spanning every class they belonged
    to. Percent is over the student's recorded days only."""
    records = Attendance.objects.filter(
        student=student,
        date__gte=term.start_date,
        date__lte=term.end_date,
    )
    per = {'PRESENT': 0, 'ABSENT': 0, 'LATE': 0, 'EXCUSED': 0}
    recorded_days = set()
    for record in records:
        per[record.status] += 1
        recorded_days.add(record.date)
    recorded_days = len(recorded_days)
    attended = per['PRESENT'] + per['LATE']
    return {
        'present': per['PRESENT'],
        'late': per['LATE'],
        'absent': per['ABSENT'],
        'excused': per['EXCUSED'],
        'recorded_days': recorded_days,
        'percent': (attended / recorded_days * 100) if recorded_days else None,
    }


def class_finance_report(term, class_stream):
    """Class-scoped finance report for one term. Every number is derived by
    the fees service's class attribution — nothing here is persisted. All
    students with a financial footprint in the class are listed, including
    fully settled accounts."""
    from fees.services import _term_class_finance, finance_dashboard_stats

    charged, paid, owed, _ = _term_class_finance(term, class_stream)
    student_ids = set(charged) | set(paid)
    students = {
        student.pk: student
        for student in Student.objects.filter(pk__in=student_ids).select_related(
            'class_stream__school_class', 'class_stream__stream'
        )
    }
    rows = []
    for student_id in sorted(
        student_ids, key=lambda sid: students[sid].admission_no
    ):
        rows.append({
            'student': students[student_id],
            'charged': charged[student_id],
            'paid': paid[student_id],
            'owed': owed[student_id],
        })
    stats = finance_dashboard_stats(term, class_stream)
    return {
        'term': term,
        'class_stream': class_stream,
        'rows': rows,
        'totals': {
            'charged': sum(charged.values()),
            'paid': sum(paid.values()),
            'owed': sum(value for value in owed.values() if value > 0),
            'owing_count': stats['owing_count'],
            'paid_full_count': stats['paid_full_count'],
            'in_credit_count': stats['in_credit_count'],
        },
    }