from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from .utils import normalize_student_id


class StudentIDOrUsernameBackend(ModelBackend):
    """Students log in with their Student ID (any case, stray spaces ignored);
    teachers and admins log in with their username."""

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        User = get_user_model()
        cleaned = username.strip()
        user = (
            User.objects.filter(student_id=normalize_student_id(cleaned)).first()
            or User.objects.filter(username=cleaned).first()
        )
        if user is None:
            # Run the hasher anyway to keep response timing similar.
            User().set_password(password)
            return None
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None
