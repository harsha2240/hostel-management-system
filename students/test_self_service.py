from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from allocations.services import allocate
from hostels.models import Hostel
from payments.models import ReceiptSequence
from payments.services import record_payment
from tests.factories import make_room, make_student


class StudentSelfServiceTests(TestCase):
    def setUp(self):
        self.student_user = User.objects.create_user(
            username="portal-student-one",
            password="Validpass123",
            role=User.Role.STUDENT,
        )
        self.other_user = User.objects.create_user(
            username="portal-student-two",
            password="Validpass123",
            role=User.Role.STUDENT,
        )
        self.student = make_student(1, user=self.student_user)
        self.other_student = make_student(2, user=self.other_user)
        self.warden = User.objects.create_user(
            username="portal-warden", role=User.Role.WARDEN
        )
        self.hostel = Hostel.objects.create(name="Maple House", hostel_type="Boys")
        self.room = make_room(
            number="301",
            hostel=self.hostel,
            fee_amount=Decimal("1000.00"),
        )
        self.other_hostel = Hostel.objects.create(
            name="Cedar House", hostel_type="Boys"
        )
        self.other_room = make_room(
            number="402",
            hostel=self.other_hostel,
            fee_amount=Decimal("800.00"),
        )
        ReceiptSequence.objects.get_or_create(pk=1)
        self.client.force_login(self.student_user)

    def make_payment(self, student, amount):
        return record_payment(
            actor=self.warden,
            student=student,
            amount=Decimal(amount),
            date=timezone.localdate(),
            mode="UPI",
        )

    def test_student_sees_only_own_allocation_and_payment_details(self):
        allocate(
            student=self.student,
            bed=self.room.beds.first(),
            actor=self.warden,
        )
        allocate(
            student=self.other_student,
            bed=self.other_room.beds.first(),
            actor=self.warden,
        )
        own_payment = self.make_payment(self.student, "400.00")
        other_payment = self.make_payment(self.other_student, "250.00")

        response = self.client.get(reverse("student-self-service"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Maple House")
        self.assertContains(response, "301")
        self.assertContains(response, own_payment.receipt_no)
        self.assertContains(response, "Partial")
        self.assertNotContains(response, "Cedar House")
        self.assertNotContains(response, "402")
        self.assertNotContains(response, other_payment.receipt_no)
        self.assertNotContains(response, self.other_student.student_id)

    def test_empty_allocation_and_payment_history_is_explained(self):
        response = self.client.get(reverse("student-self-service"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "You do not have an active room allocation.")
        self.assertContains(response, "No allocation history yet.")
        self.assertContains(response, "No payments are recorded for you yet.")
        self.assertContains(response, "Pending")

    def test_unlinked_student_login_gets_helpful_empty_state(self):
        unlinked = User.objects.create_user(
            username="portal-unlinked", password="Validpass123", role=User.Role.STUDENT
        )
        self.client.force_login(unlinked)

        response = self.client.get(reverse("student-self-service"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your student profile is not linked yet")
        self.assertContains(response, "Ask an administrator or warden")
        self.assertNotContains(response, self.student.student_id)

    def test_only_student_role_can_open_self_service_page(self):
        self.client.force_login(self.warden)
        self.assertEqual(
            self.client.get(reverse("student-self-service")).status_code, 403
        )

        admin = User.objects.create_user(username="portal-admin", role=User.Role.ADMIN)
        self.client.force_login(admin)
        self.assertEqual(
            self.client.get(reverse("student-self-service")).status_code, 403
        )

    def test_login_is_required_for_self_service_page(self):
        self.client.logout()
        response = self.client.get(reverse("student-self-service"))
        self.assertRedirects(
            response,
            f"{reverse('login')}?next={reverse('student-self-service')}",
        )

    def test_dashboard_and_navigation_link_to_my_records(self):
        dashboard = self.client.get(reverse("dashboard"))
        self.assertContains(dashboard, reverse("student-self-service"))

    def test_student_account_picker_excludes_staff_and_accounts_linked_elsewhere(self):
        from students.forms import StudentForm

        admin = User.objects.create_user(username="picker-admin", role=User.Role.ADMIN)
        unlinked = User.objects.create_user(
            username="picker-unlinked", role=User.Role.STUDENT
        )
        form = StudentForm()
        account_ids = set(form.fields["user"].queryset.values_list("pk", flat=True))

        self.assertIn(unlinked.pk, account_ids)
        self.assertNotIn(self.student_user.pk, account_ids)
        self.assertNotIn(self.other_user.pk, account_ids)
        self.assertNotIn(admin.pk, account_ids)

        edit_form = StudentForm(instance=self.student)
        edit_ids = set(edit_form.fields["user"].queryset.values_list("pk", flat=True))
        self.assertIn(self.student_user.pk, edit_ids)
        self.assertNotIn(self.other_user.pk, edit_ids)
