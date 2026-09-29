from django.db.models import Count

from .models import Attendance


def status_counts(queryset):
    """Counts of each status plus total and present percentage for a queryset."""
    counts = {choice: 0 for choice, _ in Attendance.Status.choices}
    rows = (
        queryset.order_by()
        .values('status')
        .annotate(total=Count('id'))
    )
    for row in rows:
        counts[row['status']] = row['total']
    total = sum(counts.values())
    percent = (counts['PRESENT'] / total * 100) if total else 0
    return {
        'counts': counts,
        'total': total,
        'percent': percent,
    }