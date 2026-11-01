import os
from datetime import timedelta
from time import perf_counter
from unittest import skipIf

from django.conf import settings
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from audit.models import AuditEvent

from .models import User


class AuthenticationTests(TestCase):
    def setUp(self):
        self.student = User.objects.create_user(username='student1', password='Validpass123', role=User.Role.STUDENT)

    def test_login_page_welcomes_new_users_and_explains_account_setup(self):
        response = self.client.get(reverse("login"))
        self.assertContains(response, "Welcome to HMS")
        self.assertContains(response, "New here? Ask your hostel administrator")
        self.assertNotContains(response, "Create account")

    def test_login_shows_role_dashboard_and_logout_clears_session(self):
        response = self.client.post(reverse('login'), {'username': 'student1', 'password': 'Validpass123'})
        self.assertRedirects(response, reverse('dashboard'))
        dashboard = self.client.get(reverse('dashboard'))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, 'Student')
        session_key = self.client.session.session_key
        self.client.post(reverse('logout'))
        self.assertNotEqual(self.client.session.session_key, session_key)
        self.assertRedirects(self.client.get(reverse('dashboard')), f'{reverse("login")}?next={reverse("dashboard")}')

    def test_each_role_can_access_dashboard_and_dashboard_reflects_role(self):
        expected_content = {
            User.Role.ADMIN: 'Manage user accounts and roles',
            User.Role.WARDEN: 'Hostel operations',
            User.Role.STUDENT: 'Find your place on campus',
        }
        for role, label in ((User.Role.ADMIN, 'Admin'), (User.Role.WARDEN, 'Warden'),
                            (User.Role.STUDENT, 'Student')):
            with self.subTest(role=role):
                account = User.objects.create_user(
                    username=f'{role}-dashboard', password='Validpass123', role=role,
                )
                self.client.force_login(account)
                response = self.client.get(reverse('dashboard'))
                self.assertContains(response, f'{label} dashboard')
                self.assertContains(response, expected_content[role])
                if role == User.Role.ADMIN:
                    self.assertContains(response, reverse('user-management'))
                else:
                    self.assertNotContains(response, reverse('user-management'))

    @skipIf(
        os.environ.get("COVERAGE_RUN") == "true",
        "Wall-clock thresholds are measured without coverage instrumentation.",
    )
    def test_login_and_role_dashboard_respond_within_two_seconds(self):
        for role in User.Role.values:
            account = self.student if role == User.Role.STUDENT else User.objects.create_user(
                username=f'{role}-performance', password='Validpass123', role=role,
            )
            client = Client()
            with self.subTest(role=role):
                started = perf_counter()
                login_response = client.post(
                    reverse('login'), {'username': account.username, 'password': 'Validpass123'},
                )
                login_seconds = perf_counter() - started
                self.assertRedirects(login_response, reverse('dashboard'))
                self.assertLess(login_seconds, 2.0, f'{role} login took {login_seconds:.3f} seconds')

                started = perf_counter()
                dashboard_response = client.get(reverse('dashboard'))
                dashboard_seconds = perf_counter() - started
                self.assertEqual(dashboard_response.status_code, 200)
                self.assertLess(
                    dashboard_seconds, 2.0,
                    f'{role} dashboard took {dashboard_seconds:.3f} seconds',
                )

    def test_session_cookie_is_http_only_and_uses_fifteen_minute_rolling_expiry(self):
        response = self.client.post(reverse('login'), {'username': 'student1', 'password': 'Validpass123'})
        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(cookie['httponly'])
        self.assertEqual(bool(cookie['secure']), settings.SESSION_COOKIE_SECURE)
        self.assertEqual(self.client.session.get_expiry_age(), 15 * 60)
        self.assertTrue(settings.SESSION_EXPIRE_AT_BROWSER_CLOSE)
        self.assertTrue(settings.SESSION_SAVE_EVERY_REQUEST)

    @override_settings(SESSION_COOKIE_SECURE=True, CSRF_COOKIE_SECURE=True)
    def test_session_and_csrf_cookies_are_secure_when_enabled_for_deployment(self):
        login_page = self.client.get(reverse('login'))
        csrf_cookie = login_page.cookies[settings.CSRF_COOKIE_NAME]
        self.assertTrue(csrf_cookie['secure'])

        response = self.client.post(
            reverse('login'),
            {'username': 'student1', 'password': 'Validpass123'},
        )
        session_cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(session_cookie['secure'])
        self.assertTrue(session_cookie['httponly'])

    def test_invalid_password_is_generic_and_locks_after_five_attempts(self):
        first = self.client.post(reverse('login'), {'username': 'student1', 'password': 'wrong'})
        self.assertContains(first, 'Invalid username or password')
        for _ in range(4):
            self.client.post(reverse('login'), {'username': 'student1', 'password': 'wrong'})
        self.student.refresh_from_db()
        self.assertIsNotNone(self.student.locked_until)
        self.assertGreater(self.student.locked_until, timezone.now())
        self.assertEqual(self.student.failed_attempts, 0)

    def test_locked_account_keeps_generic_error(self):
        self.student.locked_until = timezone.now() + timedelta(minutes=15)
        self.student.save(update_fields=['locked_until'])
        response = self.client.post(reverse('login'), {'username': 'student1', 'password': 'wrong'})
        self.assertContains(response, 'Invalid username or password')

    def test_expired_session_requires_login(self):
        self.client.force_login(self.student)
        session = self.client.session
        session.set_expiry(-1)
        session.save()
        response = self.client.get(reverse('dashboard'))
        self.assertRedirects(response, f'{reverse("login")}?next={reverse("dashboard")}')

    def test_admin_can_create_and_deactivate_accounts(self):
        admin_user = User.objects.create_user(username='admin1', password='Validpass123', role=User.Role.ADMIN)
        self.client.force_login(admin_user)
        response = self.client.post(reverse('user-management'), {
            'username': 'newwarden', 'password': 'Securepass42', 'role': User.Role.WARDEN,
        })
        self.assertRedirects(response, reverse('user-management'))
        target = User.objects.get(username='newwarden')
        self.assertTrue(target.check_password('Securepass42'))
        self.client.post(reverse('user-deactivate', args=[target.pk]))
        target.refresh_from_db()
        self.assertFalse(target.is_active)

    def test_non_admin_cannot_manage_accounts(self):
        for role in (User.Role.WARDEN, User.Role.STUDENT):
            with self.subTest(role=role):
                account = User.objects.create_user(
                    username=f'{role}-no-admin', password='Validpass123', role=role,
                )
                self.client.force_login(account)
                self.assertEqual(self.client.get(reverse('user-management')).status_code, 403)
                self.assertEqual(self.client.post(reverse('user-management'), {
                    'username': f'{role}-intruder',
                    'password': 'Validpass123',
                    'role': User.Role.ADMIN,
                }).status_code, 403)

    def test_password_policy_rejects_password_without_letter_or_digit(self):
        admin_user = User.objects.create_user(username='admin2', password='Validpass123', role=User.Role.ADMIN)
        self.client.force_login(admin_user)
        response = self.client.post(reverse('user-management'), {
            'username': 'weak-password-user', 'password': 'onlyletters', 'role': User.Role.STUDENT,
        })
        self.assertEqual(response.status_code, 200)
        self.assertFalse(User.objects.filter(username='weak-password-user').exists())

    def test_duplicate_username_is_rejected(self):
        admin_user = User.objects.create_user(username='admin3', password='Validpass123', role=User.Role.ADMIN)
        self.client.force_login(admin_user)
        response = self.client.post(reverse('user-management'), {
            'username': 'student1', 'password': 'Validpass123', 'role': User.Role.STUDENT,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(User.objects.filter(username='student1').count(), 1)

    def test_admin_can_update_account(self):
        admin_user = User.objects.create_user(username='admin-update', password='Validpass123', role=User.Role.ADMIN)
        target = User.objects.create_user(username='target-user', password='Validpass123', role=User.Role.WARDEN)
        self.client.force_login(admin_user)

        response = self.client.post(reverse('user-update', args=[target.pk]), {
            'first_name': 'Updated', 'last_name': 'User', 'email': 'updated@example.test',
            'role': User.Role.STUDENT,
        })

        self.assertRedirects(response, reverse('user-management'))
        target.refresh_from_db()
        self.assertEqual(target.first_name, 'Updated')
        self.assertEqual(target.role, User.Role.STUDENT)

    def test_non_admin_cannot_update_account(self):
        target = User.objects.create_user(username='target-update', password='Validpass123', role=User.Role.WARDEN)
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(reverse('user-update', args=[target.pk])).status_code, 403)


    def test_profile_settings_save_is_audited_and_unchanged_save_is_not(self):
        self.client.force_login(self.student)
        data = {
            "section": "profile",
            "first_name": "Asha",
            "last_name": "Student",
            "email": "asha@example.test",
        }
        response = self.client.post(reverse("settings"), data)
        self.assertRedirects(response, reverse("settings"))
        self.student.refresh_from_db()
        self.assertEqual(self.student.first_name, "Asha")
        self.assertEqual(self.student.email, "asha@example.test")
        self.assertEqual(
            AuditEvent.objects.filter(
                user=self.student, action=AuditEvent.Action.UPDATE,
                record_type="accounts.user", record_id=str(self.student.pk),
            ).count(),
            1,
        )

        response = self.client.post(reverse("settings"), data)
        self.assertRedirects(response, reverse("settings"))
        self.assertEqual(
            AuditEvent.objects.filter(
                user=self.student, action=AuditEvent.Action.UPDATE,
                record_type="accounts.user", record_id=str(self.student.pk),
            ).count(),
            1,
        )

    def test_password_settings_change_audits_without_secret_and_preserves_session(self):
        self.client.force_login(self.student)
        old_session_key = self.client.session.session_key
        new_password = "Changedpass123"
        response = self.client.post(reverse("settings"), {
            "section": "password",
            "old_password": "Validpass123",
            "new_password1": new_password,
            "new_password2": new_password,
        })
        self.assertRedirects(response, reverse("settings"))
        self.assertNotEqual(self.client.session.session_key, old_session_key)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password(new_password))
        self.assertEqual(
            AuditEvent.objects.filter(
                user=self.student, action=AuditEvent.Action.UPDATE,
                record_type="accounts.user", record_id=str(self.student.pk),
            ).count(),
            1,
        )
        self.assertNotIn(new_password, str(list(AuditEvent.objects.values())))

    def test_invalid_password_settings_do_not_change_password_or_audit(self):
        self.client.force_login(self.student)
        response = self.client.post(reverse("settings"), {
            "section": "password",
            "old_password": "wrong-password",
            "new_password1": "Changedpass123",
            "new_password2": "Mismatchpass123",
        })
        self.assertEqual(response.status_code, 200)
        self.student.refresh_from_db()
        self.assertTrue(self.student.check_password("Validpass123"))
        self.assertFalse(AuditEvent.objects.filter(
            user=self.student, action=AuditEvent.Action.UPDATE,
        ).exists())
