from django.test import TestCase
from django.urls import reverse

from accounts.models import User


class DashboardNavigationSmokeTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="nav-admin", role=User.Role.ADMIN
        )
        self.warden = User.objects.create_user(
            username="nav-warden", role=User.Role.WARDEN
        )
        self.student = User.objects.create_user(
            username="nav-student", role=User.Role.STUDENT
        )

    def assert_pages_load(self, user, route_names):
        self.client.force_login(user)
        dashboard = self.client.get(reverse("dashboard"))
        self.assertEqual(dashboard.status_code, 200)
        for route_name in route_names:
            with self.subTest(role=user.role, route=route_name):
                self.assertContains(dashboard, reverse(route_name))
                response = self.client.get(reverse(route_name), follow=True)
                self.assertEqual(response.status_code, 200, response.content[:300])

    def test_admin_dashboard_navigation_pages_load(self):
        self.assert_pages_load(
            self.admin,
            (
                "student-list",
                "hostel-list",
                "bed-list",
                "allocation-list",
                "payment-list",
                "occupancy-report",
                "user-management",
                "audit-log",
                "settings",
            ),
        )

    def test_warden_dashboard_navigation_pages_load(self):
        self.assert_pages_load(
            self.warden,
            (
                "student-list",
                "bed-list",
                "allocation-list",
                "payment-list",
                "occupancy-report",
                "settings",
            ),
        )
        for route_name in ("hostel-list", "user-management", "audit-log"):
            self.assertEqual(self.client.get(reverse(route_name)).status_code, 403)

    def test_student_dashboard_navigation_and_staff_route_denials(self):
        self.assert_pages_load(
            self.student,
            ("bed-list", "student-self-service", "settings"),
        )
        for route_name in (
            "student-list",
            "allocation-list",
            "payment-list",
            "occupancy-report",
            "user-management",
            "audit-log",
        ):
            self.assertEqual(self.client.get(reverse(route_name)).status_code, 403)
