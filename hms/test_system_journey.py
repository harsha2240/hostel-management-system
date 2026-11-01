"""Cross-feature journey checks for the merged HMS application."""

from decimal import Decimal

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from audit.models import AuditEvent
from hostels.models import Hostel
from payments.models import ReceiptSequence
from tests.factories import make_room, make_student


class StudentHostelJourneyTests(TestCase):
    def setUp(self):
        ReceiptSequence.objects.get_or_create(pk=1)
        self.warden = User.objects.create_user(
            username="journey-warden", password="Validpass123", role=User.Role.WARDEN
        )
        self.student_user = User.objects.create_user(
            username="journey-student",
            password="Validpass123",
            role=User.Role.STUDENT,
        )
        self.student = make_student(number=91, user=self.student_user)
        self.other_student = make_student(number=92, name="Unrelated Student")
        self.hostel = Hostel.objects.create(name="Journey Hostel", hostel_type="Boys")
        self.room = make_room(
            "901",
            hostel=self.hostel,
            capacity=2,
            fee_amount=Decimal("1000.00"),
        )
        self.bed = self.room.beds.first()
        self.staff_client = self.client
        self.staff_client.force_login(self.warden)
        self.student_client = Client()
        self.student_client.force_login(self.student_user)

    def test_staff_allocation_payment_student_view_and_reports_work_together(self):
        allocation_response = self.staff_client.post(
            reverse("allocation-list"),
            {"student_id": self.student.student_id, "bed_id": self.bed.pk},
            content_type="application/json",
        )
        self.assertEqual(allocation_response.status_code, 201)
        self.bed.refresh_from_db()
        self.assertEqual(self.bed.status, "Occupied")

        payment_response = self.staff_client.post(
            reverse("payment-create"),
            {
                "student_id": self.student.student_id,
                "amount": "400.00",
                "date": timezone.localdate().isoformat(),
                "mode": "UPI",
                "reference": "JOURNEY001",
            },
            content_type="application/json",
        )
        self.assertEqual(payment_response.status_code, 201, payment_response.content)
        receipt_no = payment_response.json()["receipt_no"]
        self.assertEqual(payment_response.json()["student_id"], self.student.student_id)

        receipt = self.staff_client.get(
            reverse("payment-receipt", args=[receipt_no]),
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(receipt.status_code, 200)
        self.assertEqual(receipt.json()["amount"], "400.00")
        pdf = self.staff_client.get(reverse("payment-receipt-pdf", args=[receipt_no]))
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf["Content-Type"], "application/pdf")

        student_page = self.student_client.get(reverse("student-self-service"))
        self.assertEqual(student_page.status_code, 200)
        self.assertContains(student_page, self.hostel.name)
        self.assertContains(student_page, self.room.room_number)
        self.assertContains(student_page, receipt_no)
        self.assertNotContains(student_page, self.other_student.name)

        occupancy = self.staff_client.get(
            reverse("occupancy-report"), HTTP_ACCEPT="application/json"
        )
        self.assertEqual(occupancy.status_code, 200)
        occupancy_row = next(
            row
            for row in occupancy.json()["rows"]
            if row["hostel_id"] == self.hostel.pk
        )
        self.assertEqual(occupancy_row["occupied_beds"], 1)

        payment_status = self.staff_client.get(
            reverse("payment-status-report"), HTTP_ACCEPT="application/json"
        )
        student_row = next(
            row
            for row in payment_status.json()["rows"]
            if row["student_id"] == self.student.student_id
        )
        self.assertEqual(
            (student_row["paid"], student_row["due"], student_row["status"]),
            ("400.00", "600.00", "Partial"),
        )

        self.assertEqual(
            self.student_client.get(reverse("occupancy-report")).status_code, 403
        )
        self.assertEqual(
            self.staff_client.get(reverse("student-self-service")).status_code, 403
        )
        event_actions = set(
            AuditEvent.objects.filter(user=self.warden).values_list("action", flat=True)
        )
        self.assertTrue({"allocate", "payment"}.issubset(event_actions))
