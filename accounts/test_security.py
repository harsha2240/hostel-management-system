from datetime import timedelta

from django.contrib.sessions.models import Session
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent

from .forms import AccountCreationForm, AccountUpdateForm
from .models import User


class SessionAndLockoutTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_superuser(
            username="security-admin",
            password="Strongpass123",
        )

    def test_django_admin_login_enforces_five_attempt_lockout(self):
        for _ in range(5):
            self.client.post(
                reverse("admin:login"),
                {
                    "username": self.admin.username,
                    "password": "wrong",
                },
            )
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.is_locked())
        self.assertEqual(AuditEvent.objects.filter(action="login_failed").count(), 5)
        response = self.client.post(
            reverse("admin:login"),
            {
                "username": self.admin.username,
                "password": "Strongpass123",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("_auth_user_id", self.client.session)
        self.admin.locked_until = timezone.now() - timedelta(seconds=1)
        self.admin.save(update_fields=["locked_until"])
        response = self.client.post(
            reverse("admin:login"),
            {
                "username": self.admin.username,
                "password": "Strongpass123",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)

    def test_lockout_is_shared_between_application_and_admin_logins(self):
        for index in range(5):
            url = reverse("login") if index % 2 else reverse("admin:login")
            self.client.post(
                url, {"username": self.admin.username, "password": "wrong"}
            )
        response = self.client.post(
            reverse("login"),
            {
                "username": self.admin.username,
                "password": "Strongpass123",
            },
        )
        self.assertContains(response, "Invalid username or password")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_success_resets_failed_attempts_and_expired_lock_starts_a_new_count(self):
        self.admin.failed_attempts = 4
        self.admin.locked_until = timezone.now() - timedelta(seconds=1)
        self.admin.save(update_fields=["failed_attempts", "locked_until"])
        self.client.post(
            reverse("login"), {"username": self.admin.username, "password": "wrong"}
        )
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.failed_attempts, 1)
        self.assertIsNone(self.admin.locked_until)
        self.client.post(
            reverse("login"),
            {
                "username": self.admin.username,
                "password": "Strongpass123",
            },
        )
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.failed_attempts, 0)

    def test_inactive_account_cannot_sign_in(self):
        self.admin.is_active = False
        self.admin.save(update_fields=["is_active"])
        self.client.post(
            reverse("login"),
            {
                "username": self.admin.username,
                "password": "Strongpass123",
            },
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_server_session_expiry_logout_and_cache_control(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse("dashboard"))
        self.assertIn("no-store", response["Cache-Control"])
        key = self.client.session.session_key
        Session.objects.filter(session_key=key).update(
            expire_date=timezone.now() - timedelta(seconds=1),
        )
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)
        self.client.force_login(self.admin)
        key = self.client.session.session_key
        self.assertEqual(self.client.get(reverse("logout")).status_code, 405)
        self.client.post(reverse("logout"))
        self.assertFalse(Session.objects.filter(session_key=key).exists())

    @override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True)
    def test_https_session_and_csrf_cookies_have_required_flags(self):
        self.client.get(reverse("login"), secure=True)
        response = self.client.post(
            reverse("login"),
            {
                "username": self.admin.username,
                "password": "Strongpass123",
            },
            secure=True,
        )
        self.assertTrue(response.cookies["sessionid"]["secure"])
        self.assertTrue(response.cookies["sessionid"]["httponly"])
        self.assertTrue(response.cookies["csrftoken"]["secure"])

    def test_login_post_is_protected_by_csrf(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(
            reverse("login"),
            {
                "username": self.admin.username,
                "password": "Strongpass123",
            },
        )
        self.assertEqual(response.status_code, 403)
        self.assertNotIn("_auth_user_id", client.session)

    def test_unknown_role_cannot_access_dashboard(self):
        account = User.objects.create_user(username="invalid-role")
        User.objects.filter(pk=account.pk).update(role="invalid")
        account.refresh_from_db()
        self.client.force_login(account)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 403)

    def test_superuser_role_and_password_similarity_validation(self):
        form = AccountUpdateForm({"role": User.Role.STUDENT}, instance=self.admin)
        self.assertFalse(form.is_valid())
        form = AccountCreationForm(
            {
                "username": "similarname123",
                "password": "similarname123",
                "role": User.Role.WARDEN,
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("password", form.errors)
