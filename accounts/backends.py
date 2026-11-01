"""Apply the same lockout policy to application and Django admin logins."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.db import transaction
from django.utils import timezone


class LockoutBackend(ModelBackend):
    attempts = 5
    duration = timedelta(minutes=15)

    def authenticate(self, request, username=None, password=None, **kwargs):
        user_model = get_user_model()
        username = username or kwargs.get(user_model.USERNAME_FIELD)
        if username is None or password is None:
            return None
        try:
            user = user_model._default_manager.get_by_natural_key(username)
        except user_model.DoesNotExist:
            user_model().set_password(password)
            return None

        # Hash outside the row lock so concurrent logins do not hold it during
        # the normal PBKDF2 calculation. Recheck if the password changed.
        password_matches = user.check_password(password)
        with transaction.atomic():
            current = user_model.objects.select_for_update().get(pk=user.pk)
            if not self.user_can_authenticate(current) or current.is_locked():
                return None
            if current.password != user.password:
                password_matches = current.check_password(password)
            if current.locked_until:
                current.failed_attempts = 0
                current.locked_until = None
            if password_matches:
                current.failed_attempts = 0
            else:
                current.failed_attempts += 1
                if current.failed_attempts >= self.attempts:
                    current.locked_until = timezone.now() + self.duration
                    current.failed_attempts = 0
            current.save(update_fields=["failed_attempts", "locked_until"])
            return current if password_matches else None
