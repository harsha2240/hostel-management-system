from datetime import timedelta
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from tests.factories import make_student

from .mixins import AuditedAdminMixin
from .models import AuditEvent
from .services import record_event


class AuditTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="audit-admin",
            password="Strongpass123",
        )
        cls.warden = User.objects.create_user(
            username="audit-warden",
            password="Strongpass123",
            role=User.Role.WARDEN,
        )

    def test_authentication_events_include_actor_record_and_time_without_secrets(self):
        before = timezone.now()
        self.client.post(
            reverse("login"),
            {
                "username": self.warden.username,
                "password": "wrong-secret-123",
            },
        )
        failure = AuditEvent.objects.get(action=AuditEvent.Action.LOGIN_FAILED)
        self.assertIsNone(failure.user_id)
        self.assertEqual(failure.record_id, str(self.warden.pk))
        self.client.post(
            reverse("login"),
            {
                "username": self.warden.username,
                "password": "Strongpass123",
            },
        )
        login = AuditEvent.objects.get(action=AuditEvent.Action.LOGIN)
        self.assertEqual(login.user_id, self.warden.pk)
        self.assertEqual(login.record_type, "accounts.user")
        self.assertGreaterEqual(login.timestamp, before)
        session_key = self.client.session.session_key
        self.client.post(reverse("logout"))
        self.assertEqual(
            AuditEvent.objects.get(action=AuditEvent.Action.LOGOUT).user_id,
            self.warden.pk,
        )
        serialized = str(list(AuditEvent.objects.values()))
        for secret in ("wrong-secret-123", "Strongpass123", session_key):
            self.assertNotIn(secret, serialized)

    def test_unknown_username_failure_is_logged_without_storing_input(self):
        username = "unknown-input-secret"
        self.client.post(reverse("login"), {"username": username, "password": "wrong"})
        event = AuditEvent.objects.get(action=AuditEvent.Action.LOGIN_FAILED)
        self.assertIsNone(event.user_id)
        self.assertEqual(event.record_id, "")
        self.assertNotIn(username, str(list(AuditEvent.objects.values())))

    def test_create_update_and_deactivate_accounts_record_the_admin_actor(self):
        self.client.force_login(self.admin)
        self.client.post(
            reverse("user-management"),
            {
                "username": "audited-account",
                "password": "Otherstrong42",
                "role": User.Role.WARDEN,
            },
        )
        target = User.objects.get(username="audited-account")
        self.client.post(
            reverse("user-update", args=[target.pk]),
            {
                "first_name": "Edited",
                "role": User.Role.STUDENT,
            },
        )
        self.client.post(reverse("user-deactivate", args=[target.pk]))
        events = AuditEvent.objects.filter(record_id=str(target.pk)).order_by("pk")
        self.assertEqual(
            list(events.values_list("action", flat=True)),
            [
                AuditEvent.Action.CREATE,
                AuditEvent.Action.UPDATE,
                AuditEvent.Action.DEACTIVATE,
            ],
        )
        self.assertEqual(set(events.values_list("user_id", flat=True)), {self.admin.pk})

    def test_audit_failure_rolls_back_account_creation(self):
        self.client.force_login(self.admin)
        with patch(
            "accounts.views.record_event", side_effect=RuntimeError("audit failed")
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse("user-management"),
                    {
                        "username": "must-rollback",
                        "password": "Otherstrong42",
                        "role": User.Role.WARDEN,
                    },
                )
        self.assertFalse(User.objects.filter(username="must-rollback").exists())

    def test_only_admin_can_read_audit_log_including_direct_json_requests(self):
        response = self.client.get(reverse("audit-log"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            self.client.get(
                reverse("audit-log"),
                HTTP_ACCEPT="application/json",
            ).status_code,
            401,
        )
        for role in (User.Role.WARDEN, User.Role.STUDENT):
            self.warden.role = role
            self.warden.save(update_fields=["role"])
            self.client.force_login(self.warden)
            response = self.client.get(
                reverse("audit-log"), HTTP_ACCEPT="application/json"
            )
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["error"]["code"], "ACCESS_DENIED")
        self.client.force_login(self.admin)
        self.assertEqual(self.client.get(reverse("audit-log")).status_code, 200)
        self.assertEqual(
            self.client.get(
                reverse("audit-log"),
                HTTP_ACCEPT="application/json",
            ).status_code,
            200,
        )

    def test_audit_filter_and_pagination_keep_valid_query_links(self):
        for index in range(27):
            record_event(
                user=self.admin,
                action=AuditEvent.Action.CREATE,
                record_type="sample",
                record_id=str(index),
            )
        self.client.force_login(self.admin)
        response = self.client.get(reverse("audit-log"), {"action": "create"})
        self.assertContains(response, "action=create&amp;page=2")
        self.assertNotContains(response, "??")
        page = self.client.get(
            reverse("audit-log"),
            {"action": "create", "page": 2},
            HTTP_ACCEPT="application/json",
        ).json()
        self.assertEqual(page["page"], 2)
        self.assertEqual(page["total"], 27)
        self.assertEqual(len(page["results"]), 2)

    def test_events_cannot_be_changed_or_deleted_through_supported_orm_operations(self):
        event = record_event(
            user=self.admin, action=AuditEvent.Action.CREATE, record=self.warden
        )
        event.action = AuditEvent.Action.UPDATE
        with self.assertRaises(ValidationError):
            event.save()
        with self.assertRaises(ValidationError):
            event.delete()
        with self.assertRaises(ValidationError):
            AuditEvent.objects.filter(pk=event.pk).update(action="update")
        with self.assertRaises(ValidationError):
            AuditEvent.objects.bulk_update([event], ["action"])
        with self.assertRaises(ValidationError):
            AuditEvent.objects.all().delete()
        replacement = AuditEvent(
            pk=event.pk,
            action="update",
            record_type="accounts.user",
            record_id=str(self.warden.pk),
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            replacement.save()
        with self.assertRaises(ValidationError):
            AuditEvent.objects.bulk_create(
                [replacement],
                update_conflicts=True,
                update_fields=["action"],
            )
        event.refresh_from_db()
        self.assertEqual(event.action, AuditEvent.Action.CREATE)

    def test_retention_command_preserves_a_full_year_and_supports_dry_run(self):
        now = timezone.now()
        events = []
        for age in (367, 366, 365, 0):
            with patch(
                "django.utils.timezone.now", return_value=now - timedelta(days=age)
            ):
                events.append(
                    record_event(
                        user=self.admin,
                        action=AuditEvent.Action.CREATE,
                        record=self.warden,
                    )
                )
        with self.assertRaises(CommandError):
            call_command("purge_audit_logs", days=365, stdout=StringIO())
        with self.assertRaises(ValidationError):
            AuditEvent.objects.purge_before(now - timedelta(days=365))
        with patch("django.utils.timezone.now", return_value=now):
            output = StringIO()
            call_command("purge_audit_logs", dry_run=True, stdout=output)
            self.assertIn("1 audit entries eligible", output.getvalue())
            self.assertEqual(AuditEvent.objects.count(), 4)
            call_command("purge_audit_logs", stdout=StringIO())
        self.assertEqual(
            set(AuditEvent.objects.values_list("pk", flat=True)),
            {event.pk for event in events[1:]},
        )

    def test_admin_password_changes_are_audited_without_password_contents(self):
        self.client.force_login(self.admin)
        response = self.client.post(
            reverse("admin:auth_user_password_change", args=[self.warden.pk]),
            {"password1": "Changedstrong42", "password2": "Changedstrong42"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            AuditEvent.objects.filter(
                user=self.admin,
                action=AuditEvent.Action.UPDATE,
                record_id=str(self.warden.pk),
            ).exists()
        )
        self.assertNotIn("Changedstrong42", str(list(AuditEvent.objects.values())))

    def test_invalid_audit_action_is_rejected(self):
        with self.assertRaises(ValueError):
            record_event(user=self.admin, action="unknown", record=self.warden)


class _AdminParentStub:
    def __init__(self):
        self.parent_log = []

    def save_model(self, request, obj, form, change):
        obj.save()

    def log_addition(self, request, obj, message):
        self.parent_log.append(("addition", obj.pk))

    def log_change(self, request, obj, message):
        self.parent_log.append(("change", obj.pk))


class _AuditedAdminStub(AuditedAdminMixin, _AdminParentStub):
    pass


class AuditedAdminMixinTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="admin-mixin-test", password="Strongpass123"
        )
        self.request = SimpleNamespace(user=self.admin)
        self.model_admin = _AuditedAdminStub()

    def test_add_update_and_deactivation_events_are_recorded_for_admin_actor(self):
        user = User(username="mixin-created", role=User.Role.WARDEN)
        user.set_unusable_password()
        self.model_admin.save_model(self.request, user, form=None, change=False)
        self.model_admin.log_addition(self.request, user, message="added")

        user.first_name = "Edited"
        self.model_admin.save_model(self.request, user, form=None, change=True)
        self.model_admin.log_change(self.request, user, message="updated")

        user.is_active = False
        self.model_admin.save_model(self.request, user, form=None, change=True)
        self.model_admin.log_change(self.request, user, message="deactivated")

        student = make_student(number=98)
        student.status = student.Status.INACTIVE
        self.model_admin.save_model(self.request, student, form=None, change=True)
        self.model_admin.log_change(self.request, student, message="deactivated")

        user_events = list(
            AuditEvent.objects.filter(
                record_type="accounts.user", record_id=str(user.pk)
            )
            .order_by("pk")
            .values_list("user_id", "action")
        )
        self.assertEqual(
            user_events,
            [
                (self.admin.pk, AuditEvent.Action.CREATE),
                (self.admin.pk, AuditEvent.Action.UPDATE),
                (self.admin.pk, AuditEvent.Action.DEACTIVATE),
            ],
        )
        student_event = AuditEvent.objects.get(
            record_type="students.student", record_id=str(student.pk)
        )
        self.assertEqual(student_event.user_id, self.admin.pk)
        self.assertEqual(student_event.action, AuditEvent.Action.DEACTIVATE)
        self.assertEqual(
            self.model_admin.parent_log,
            [
                ("addition", user.pk),
                ("change", user.pk),
                ("change", user.pk),
                ("change", student.pk),
            ],
        )
        self.assertFalse(self.model_admin.has_delete_permission(self.request, user))
