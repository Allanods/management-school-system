from functools import wraps

from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied

ADMIN = 'ADMIN'
TEACHER = 'TEACHER'
PARENT = 'PARENT'


def get_role(user):
    if not user or not user.is_authenticated:
        return None
    profile = getattr(user, 'profile', None)
    return profile.role if profile else None


def has_role(user, roles):
    return get_role(user) in roles


def role_required(*roles):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(request.get_full_path())
            if not has_role(request.user, roles):
                raise PermissionDenied(
                    'You do not have permission to access this page.'
                )
            return view_func(request, *args, **kwargs)
        return _wrapped
    return decorator


admin_required = role_required(ADMIN)
teacher_required = role_required(TEACHER)
parent_required = role_required(PARENT)


class RoleRequiredMixin(UserPassesTestMixin):
    roles = ()
    raise_exception = True
    permission_denied_message = 'You do not have permission to access this page.'

    def test_func(self):
        return has_role(self.request.user, self.roles)

    def handle_no_permission(self):
        if not self.request.user.is_authenticated:
            return redirect_to_login(self.request.get_full_path())
        return super().handle_no_permission()


class AdminRequiredMixin(RoleRequiredMixin):
    roles = (ADMIN,)


class StaffRequiredMixin(RoleRequiredMixin):
    roles = (ADMIN, TEACHER)


class TeacherRequiredMixin(RoleRequiredMixin):
    roles = (TEACHER,)


class ParentRequiredMixin(RoleRequiredMixin):
    roles = (PARENT,)