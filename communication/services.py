from django.utils import timezone

from accounts.access import ADMIN, PARENT, TEACHER, get_role
from .models import Announcement


def audiences_for_user(user):
    """Audience labels an authenticated user is allowed to read."""
    role = get_role(user)
    if role == ADMIN:
        return {
            Announcement.Audience.ALL,
            Announcement.Audience.TEACHERS,
            Announcement.Audience.PARENTS,
        }
    if role == TEACHER:
        return {Announcement.Audience.ALL, Announcement.Audience.TEACHERS}
    if role == PARENT:
        return {Announcement.Audience.ALL, Announcement.Audience.PARENTS}
    return set()


def visible_announcements(user):
    """Role-scoped announcement queryset, shared by the list view.

    Admins see everything (drafts and published, all audiences). Teachers and
    parents only ever see published announcements addressed to their audience.
    """
    if not user or not user.is_authenticated:
        return Announcement.objects.none()
    if get_role(user) == ADMIN:
        return Announcement.objects.all().select_related('created_by')
    audiences = audiences_for_user(user)
    return Announcement.objects.filter(
        published=True, audience__in=audiences,
    ).select_related('created_by')


def can_view_announcement(user, announcement):
    """Whether the user may open this announcement's detail page."""
    if not user or not user.is_authenticated:
        return False
    if get_role(user) == ADMIN:
        return True
    return (
        announcement.published
        and announcement.audience in audiences_for_user(user)
    )


def publish_announcement(announcement):
    announcement.published = True
    announcement.published_at = timezone.now()
    announcement.save(update_fields=['published', 'published_at'])


def unpublish_announcement(announcement):
    """Retire a published record. The record, created_by, published_at and
    message are all preserved for the historical record."""
    announcement.published = False
    announcement.save(update_fields=['published'])


def can_delete_announcement(announcement):
    """Only unpublished drafts may be removed. Published announcements are
    permanent history."""
    return not announcement.published