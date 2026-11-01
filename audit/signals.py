from django.contrib.auth import get_user_model
from django.contrib.auth.signals import (
    user_logged_in,
    user_logged_out,
    user_login_failed,
)
from django.dispatch import receiver

from .models import AuditEvent
from .services import record_event


@receiver(user_logged_in, dispatch_uid='audit.login')
def log_login(sender, request, user, **kwargs):
    record_event(user=user, action=AuditEvent.Action.LOGIN, record=user)


@receiver(user_login_failed, dispatch_uid='audit.login_failed')
def log_login_failure(sender, credentials, request, **kwargs):
    username = credentials.get('username')
    target = None
    if isinstance(username, str) and len(username) <= 150:
        target = get_user_model().objects.filter(username__iexact=username).first()
    record_event(
        user=None, action=AuditEvent.Action.LOGIN_FAILED,
        record=target, record_type='accounts.user',
    )


@receiver(user_logged_out, dispatch_uid='audit.logout')
def log_logout(sender, request, user, **kwargs):
    if user and user.is_authenticated:
        record_event(user=user, action=AuditEvent.Action.LOGOUT, record=user)
