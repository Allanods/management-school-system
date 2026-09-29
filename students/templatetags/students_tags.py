from django import template

register = template.Library()

STATUS_BADGE_CLASSES = {
    'ACTIVE': 'text-bg-success',
    'INACTIVE': 'text-bg-secondary',
    'GRADUATED': 'text-bg-primary',
    'TRANSFERRED': 'text-bg-warning',
    'SUSPENDED': 'text-bg-danger',
}


@register.filter
def status_badge(value):
    return STATUS_BADGE_CLASSES.get(value, 'text-bg-secondary')