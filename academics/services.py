from decimal import Decimal

from django.db.models import Q

from core.models import TeacherAssignment
from .models import Assessment, GradeBand, Mark

ZERO = Decimal('0')


def teacher_authorized_assessments(teacher):
    """Assessments a teacher may manage marks for — only those whose
    (class_stream, subject) pair has a TeacherAssignment for the teacher."""
    pairs = TeacherAssignment.objects.filter(teacher=teacher).values_list(
        'class_stream_id', 'subject_id'
    )
    query = Q()
    for class_stream_id, subject_id in pairs:
        query |= Q(class_stream_id=class_stream_id, subject_id=subject_id)
    return Assessment.objects.filter(query).select_related(
        'term', 'class_stream', 'subject'
    )


def can_manage_assessment(teacher, assessment):
    if teacher is None:
        return False
    return TeacherAssignment.objects.filter(
        teacher=teacher,
        class_stream_id=assessment.class_stream_id,
        subject_id=assessment.subject_id,
    ).exists()


def grade_for_percentage(percent, bands=None):
    """Return the single GradeBand covering the percentage, or None."""
    if bands is None:
        bands = GradeBand.objects.all()
    percent = Decimal(percent)
    for band in bands:
        if band.min_percent <= percent <= band.max_percent:
            return band
    return None


def save_mark(student, assessment, scored):
    """Create or update a validated mark. Raises ValidationError on any
    integrity violation (scored bounds, stream mismatch, subject mismatch)."""
    mark = Mark(
        student=student,
        assessment=assessment,
        subject=assessment.subject,
        scored=scored,
    )
    existing = Mark.objects.filter(
        student=student, assessment=assessment, subject=assessment.subject
    ).first()
    if existing:
        mark = existing
        mark.subject = assessment.subject
        mark.scored = scored
    mark.full_clean()
    mark.save()
    return mark


def assessment_results(assessment):
    """Per-assessment view: rows with percentage/grade plus aggregate stats."""
    rows = []
    marks = assessment.marks.select_related('student').order_by(
        'student__admission_no'
    )
    total = ZERO
    for mark in marks:
        percent = (mark.scored / assessment.max_marks * 100) if assessment.max_marks else ZERO
        rows.append({
            'mark': mark,
            'percent': percent,
            'grade': grade_for_percentage(percent),
        })
        total += mark.scored
    count = len(rows)
    average = (total / count) if count else ZERO
    average_percent = (average / assessment.max_marks * 100) if assessment.max_marks else ZERO
    return {
        'count': count,
        'total': total,
        'average': average,
        'average_percent': average_percent,
        'rows': rows,
    }


def student_term_results(student, term, class_stream_ids=None):
    """Report-card foundation for one student in one term. Only published
    assessments are included; marks are computed on the fly. When
    class_stream_ids is given, only assessments belonging to those streams
    are considered."""
    grouped = {}
    marks = student.marks.filter(
        assessment__term=term,
        assessment__status=Assessment.Status.PUBLISHED,
    )
    if class_stream_ids:
        marks = marks.filter(assessment__class_stream_id__in=class_stream_ids)
    marks = marks.select_related(
        'assessment',
        'assessment__class_stream',
        'assessment__subject',
    ).order_by('assessment__date', 'assessment__name')

    for mark in marks:
        assessment = mark.assessment
        percent = (mark.scored / assessment.max_marks * 100) if assessment.max_marks else ZERO
        group = grouped.setdefault(assessment.subject_id, {
            'subject': assessment.subject,
            'assessments': [],
        })
        group['assessments'].append({
            'assessment': assessment,
            'scored': mark.scored,
            'max': assessment.max_marks,
            'percent': percent,
            'grade': grade_for_percentage(percent),
        })

    rows = []
    totals_scored = ZERO
    totals_max = ZERO
    for group in grouped.values():
        subject_total = sum(item['scored'] for item in group['assessments'])
        subject_max = sum(item['max'] for item in group['assessments'])
        subject_percent = (subject_total / subject_max * 100) if subject_max else ZERO
        group['total'] = subject_total
        group['max'] = subject_max
        group['avg_percent'] = subject_percent
        group['grade'] = grade_for_percentage(subject_percent)
        rows.append(group)
        totals_scored += subject_total
        totals_max += subject_max

    rows.sort(key=lambda g: g['subject'].name)
    overall_percent = (totals_scored / totals_max * 100) if totals_max else ZERO
    return {
        'rows': rows,
        'totals': {'scored': totals_scored, 'max': totals_max},
        'overall_percent': overall_percent,
        'overall_grade': grade_for_percentage(overall_percent),
    }