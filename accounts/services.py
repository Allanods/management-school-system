"""Canonical account-management invariants.

School records (Teacher, Parent) and authentication accounts (User +
UserProfile) are deliberately independent:

- ``Teacher.is_active`` / ``Parent`` describe the school record.
- ``User.is_active`` describes whether the account may log in.
- ``UserProfile.role`` is the single source of the user's role.

Nothing in this module ever creates a school record, deletes a record or a
user, or changes a user's role. Every mutation re-checks eligibility at call
time so callers can never rely on a stale queryset from a GET page.
"""
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError

from core.models import Teacher
from students.models import Parent

from .access import PARENT, TEACHER
from .models import UserProfile

TEACHER_PERSONA = 'teacher'
PARENT_PERSONA = 'parent'

ROLE_FOR_PERSONA = {
    TEACHER_PERSONA: UserProfile.Roles.TEACHER,
    PARENT_PERSONA: UserProfile.Roles.PARENT,
}
PERSONA_FOR_ROLE = {
    UserProfile.Roles.TEACHER: TEACHER_PERSONA,
    UserProfile.Roles.PARENT: PARENT_PERSONA,
}


def school_persona_for(user):
    """Return ``(kind, record)`` for a user's linked persona.

    ``kind`` is one of ``'teacher'``, ``'parent'`` or ``None``; ``record`` is
    the linked ``Teacher``/``Parent`` or ``None``. A user may only ever carry
    one persona (their ``UserProfile.role`` is single-valued).
    """
    if not user or not user.is_authenticated:
        return (None, None)
    if getattr(user, 'teacher', None) is not None:
        return (TEACHER_PERSONA, user.teacher)
    if getattr(user, 'parent', None) is not None:
        return (PARENT_PERSONA, user.parent)
    return (None, None)


def eligible_teacher_records():
    """Unlinked Teacher school records that may receive a login account."""
    return Teacher.objects.filter(user__isnull=True).select_related('department')


def eligible_parent_records():
    """Unlinked Parent school records that may receive a login account."""
    return Parent.objects.filter(user__isnull=True)


def eligible_users_for_link(persona):
    """Users available to be linked to the given persona type.

    A user is eligible only when they have the matching role, are not a
    superuser, and are not already linked to any persona. Accounts are never
    created here — this only finds existing accounts.
    """
    role = ROLE_FOR_PERSONA.get(persona)
    if role is None:
        return User.objects.none()
    return User.objects.filter(
        profile__role=role,
        is_superuser=False,
        teacher__isnull=True,
        parent__isnull=True,
    )


def _require_unlinked_record(record):
    if record is None:
        raise ValidationError('A Teacher or Parent record must be provided.')
    if record.user_id:
        raise ValidationError('This record already has a linked user account.')


def _require_unlinked_user(user):
    if getattr(user, 'teacher', None) is not None \
            or getattr(user, 'parent', None) is not None:
        raise ValidationError('This user is already linked to another person.')
    if user.is_superuser:
        raise ValidationError('A superuser account cannot be linked.')


def create_user_account(username, password, role, *, record=None, email=''):
    """Create a login account linked to an eligible school record.

    ``role`` must be ``TEACHER`` or ``PARENT`` and must match ``record``.
    ``record`` must be an unlinked Teacher or Parent. The account is created
    active; only an explicit account action may change that.
    """
    role = str(role)
    if role not in (UserProfile.Roles.TEACHER, UserProfile.Roles.PARENT):
        raise ValidationError(
            'Only Teacher and Parent accounts can be created in the app.'
        )
    if record is None:
        raise ValidationError('An unlinked Teacher or Parent record is required.')
    persona = PERSONA_FOR_ROLE[role]
    if persona == TEACHER_PERSONA and not isinstance(record, Teacher):
        raise ValidationError('A Teacher record must be selected for a Teacher account.')
    if persona == PARENT_PERSONA and not isinstance(record, Parent):
        raise ValidationError('A Parent record must be selected for a Parent account.')
    _require_unlinked_record(record)

    user = User.objects.create_user(username=username, password=password, email=email)
    user.profile.role = role
    user.profile.save(update_fields=['role'])
    record.user = user
    record.save(update_fields=['user'])
    return user


def link_user_to_persona(user, persona, record):
    """Linking an existing, eligible account to an unlinked school record."""
    if persona not in (TEACHER_PERSONA, PARENT_PERSONA):
        raise ValidationError('Unknown persona type.')
    if user is None:
        raise ValidationError('A user account must be provided.')
    if user.is_superuser:
        raise ValidationError('A superuser account cannot be linked.')
    profile = getattr(user, 'profile', None)
    if profile is None or profile.role != ROLE_FOR_PERSONA[persona]:
        expected = 'Teacher' if persona == TEACHER_PERSONA else 'Parent'
        raise ValidationError(
            f'Only users with the {expected} role can be linked this way.'
        )
    _require_unlinked_user(user)
    _require_unlinked_record(record)
    record.user = user
    record.save(update_fields=['user'])
    return record


def unlink_user(user):
    """Remove a user's persona link. The User, Teacher and Parent records all
    remain; only the nullable OneToOne link is cleared."""
    if user is None:
        raise ValidationError('A user account must be provided.')
    if user.is_superuser:
        raise ValidationError('A superuser account cannot be unlinked.')
    if getattr(user, 'teacher', None) is not None:
        teacher = user.teacher
        teacher.user = None
        teacher.save(update_fields=['user'])
    if getattr(user, 'parent', None) is not None:
        parent = user.parent
        parent.user = None
        parent.save(update_fields=['user'])


def set_account_password(user, new_password):
    """Set a new password with Django hashing and the project validators."""
    if user is None:
        raise ValidationError('A user account must be provided.')
    if user.is_superuser:
        raise ValidationError('A superuser account password cannot be set here.')
    validate_password(new_password, user=user)
    user.set_password(new_password)
    user.save(update_fields=['password'])


def deactivate_account(user):
    """Disable login for a user. Nothing else is touched: the school record,
    its history, marks, attendance and finance records all stay intact."""
    if user is None:
        raise ValidationError('A user account must be provided.')
    if user.is_superuser:
        raise ValidationError('A superuser account cannot be deactivated.')
    if user.is_active:
        user.is_active = False
        user.save(update_fields=['is_active'])


def activate_account(user):
    """Re-enable login. Never alters the linked school record's state."""
    if user is None:
        raise ValidationError('A user account must be provided.')
    if user.is_superuser:
        raise ValidationError('Superuser accounts are managed only in Django admin.')
    if not user.is_active:
        user.is_active = True
        user.save(update_fields=['is_active'])