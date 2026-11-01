from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .models import User


def role_required(*roles):
    """Require login AND one of the given roles. Enforced server-side on every request."""

    def decorator(view_func):
        @login_required
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if request.user.role not in roles and not (
                User.Role.SUPER_ADMIN in roles and request.user.is_superuser
            ):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator


super_admin_required = role_required(User.Role.SUPER_ADMIN)
staff_required = role_required(User.Role.SUPER_ADMIN, User.Role.TEACHER)
