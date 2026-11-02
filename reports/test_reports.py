import csv
from decimal import Decimal
from io import StringIO

from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from allocations.services import allocate, release, transfer
from hostels.models import Bed, Hostel
from payments.models import ReceiptSequence
from payments.services import record_payment
from tests.factories import make_room, make_student

from .services import occupancy_rows, payment_status_rows


class ReportTests(TestCase):
    def setUp(self):
        ReceiptSequence.objects.get_or_create(pk=1)
        self.actor = User.objects.create_user(username="report-warden", role="warden")
        self.student = make_student()
        self.room = make_room(capacity=4, fee_amount=Decimal("1000.00"))
        self.beds = list(self.room.beds.all())
        self.empty = Hostel.objects.create(
            name="Empty hostel", hostel_type="Girls", is_active=False
        )
        self.client.force_login(self.actor)

    def allocate(self, bed=None, student=None):
        return allocate(
            student=student or self.student, bed=bed or self.beds[0], actor=self.actor
        )

    def pay(self, **overrides):
        return record_payment(
            actor=self.actor,
            **({"student": self.student, "amount": "250", "mode": "Cash"} | overrides),
        )

    def rows(self, name, **query):
        response = self.client.get(reverse(name), query, HTTP_ACCEPT="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        self.assertIn("generated_on", response.json())
        return response.json()["rows"]

    def csv_rows(self, name, **query):
        response = self.client.get(reverse(name), {"format": "csv"} | query)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "text/csv; charset=utf-8")
        self.assertIn("attachment;", response["Content-Disposition"])
        return list(csv.DictReader(StringIO(response.content.decode("utf-8-sig"))))

    def test_occupancy_counts_current_records_maintenance_and_empty_hostels(self):
        first = self.allocate()
        release(allocation_id=first.pk, actor=self.actor)
        self.allocate()
        Bed.objects.filter(pk=self.beds[1].pk).update(status="Maintenance")
        Bed.objects.filter(pk=self.beds[2].pk).update(status="Occupied")
        rows = {row["hostel_id"]: row for row in self.rows("occupancy-report")}
        self.assertEqual(
            rows[self.room.hostel_id],
            {
                "hostel_id": self.room.hostel_id,
                "hostel": self.room.hostel.name,
                "total_beds": 4,
                "occupied_beds": 2,
                "available_beds": 1,
                "maintenance_beds": 1,
                "occupancy_percent": "50.00",
            },
        )
        self.assertEqual(rows[self.empty.pk]["total_beds"], 0)
        self.assertEqual(rows[self.empty.pk]["occupancy_percent"], "0.00")

    def test_active_allocations_override_stale_availability_and_maintenance_flags(self):
        first = self.allocate()
        Bed.objects.filter(pk=self.beds[0].pk).update(status="Available")
        row = occupancy_rows(self.room.hostel_id)[0]
        self.assertEqual((row["occupied_beds"], row["available_beds"]), (1, 3))
        Bed.objects.filter(pk=self.beds[0].pk).update(status="Maintenance")
        row = occupancy_rows(self.room.hostel_id)[0]
        self.assertEqual((row["occupied_beds"], row["maintenance_beds"]), (1, 0))
        release(allocation_id=first.pk, actor=self.actor)
        row = occupancy_rows(self.room.hostel_id)[0]
        self.assertEqual(
            (row["occupied_beds"], row["maintenance_beds"], row["available_beds"]),
            (0, 1, 3),
        )

    def test_occupancy_csv_and_html_match_json_and_preserve_filters(self):
        self.allocate()
        rows = self.rows("occupancy-report", hostel=self.room.hostel_id)
        self.assertEqual(len(rows), 1)
        exported = self.csv_rows("occupancy-report", hostel=self.room.hostel_id)
        self.assertEqual(len(exported), 1)
        for heading, key in (
            ("Hostel Name", "hostel"),
            ("Total Beds", "total_beds"),
            ("Occupied Beds", "occupied_beds"),
            ("Available Beds", "available_beds"),
            ("Beds Under Maintenance", "maintenance_beds"),
            ("Occupancy %", "occupancy_percent"),
        ):
            self.assertEqual(exported[0][heading], str(rows[0][key]))
        self.assertTrue(exported[0]["Generated On"].endswith(" IST"))
        response = self.client.get(
            reverse("occupancy-report"), {"hostel": self.room.hostel_id}
        )
        self.assertContains(response, "25.00%")
        self.assertContains(response, self.room.hostel.name)
        self.assertContains(response, f'value="{self.room.hostel_id}" selected')
        self.assertNotContains(response, f"<td>{self.empty.name}</td>")

    def test_payment_report_sums_once_across_allocation_history_and_filters_last_room(
        self,
    ):
        original = self.allocate()
        second_room = make_room("202", fee_amount=Decimal("2000.00"))
        current = transfer(
            allocation_id=original.pk,
            new_bed=second_room.beds.first(),
            actor=self.actor,
        )
        self.pay()
        self.pay(amount="750", mode="UPI")
        unassigned = make_student(2)
        self.pay(student=unassigned, amount="25")
        rows = {row["student_id"]: row for row in self.rows("payment-status-report")}
        row = rows[self.student.student_id]
        self.assertEqual(
            (row["fee"], row["paid"], row["due"], row["status"]),
            ("2000.00", "1000.00", "1000.00", "Partial"),
        )
        self.assertEqual(rows[unassigned.student_id]["status"], "Pending")
        self.assertEqual(
            self.rows("payment-status-report", hostel=self.room.hostel_id), []
        )
        self.assertEqual(
            len(self.rows("payment-status-report", hostel=second_room.hostel_id)), 1
        )
        release(allocation_id=current.pk, actor=self.actor)
        self.assertEqual(
            self.rows("payment-status-report", hostel=second_room.hostel_id)[0]["paid"],
            "1000.00",
        )

    def test_payment_report_csv_and_html_match_json_after_corrections(self):
        self.allocate()
        original = self.pay(amount="1000")
        self.pay(amount="-250", adjustment_of=original, adjustment_reason="Refund")
        row = self.rows("payment-status-report")[0]
        exported = self.csv_rows("payment-status-report")[0]
        for heading, key in (
            ("Student ID", "student_id"),
            ("Student Name", "student_name"),
            ("Hostel Name", "hostel"),
            ("Room", "room"),
            ("Fee Amount (INR)", "fee"),
            ("Amount Paid (INR)", "paid"),
            ("Due (INR)", "due"),
            ("Payment Status", "status"),
        ):
            self.assertEqual(exported[heading], row[key])
        response = self.client.get(reverse("payment-status-report"))
        for expected in (self.student.student_id, "750.00", "250.00", "Partial"):
            self.assertContains(response, expected)

    def test_csv_quotes_unicode_and_formula_text_and_html_escapes_names(self):
        self.room.hostel.name = '  =2+2, "North"\nWing'
        self.room.hostel.save()
        self.student.name = "@SUM(1,2) <b>Élève</b>"
        self.student.save()
        self.allocate()
        self.assertEqual(
            self.csv_rows("occupancy-report")[0]["Hostel Name"],
            "'" + self.room.hostel.name,
        )
        row = self.csv_rows("payment-status-report")[0]
        self.assertEqual(row["Student Name"], "'" + self.student.name)
        self.assertEqual(row["Hostel Name"], "'" + self.room.hostel.name)
        response = self.client.get(reverse("payment-status-report"))
        self.assertContains(response, "&lt;b&gt;Élève&lt;/b&gt;")
        self.assertNotContains(response, "<b>Élève</b>")

    def test_empty_reports_and_invalid_filters_formats_and_methods(self):
        self.assertEqual(self.rows("payment-status-report", hostel=self.empty.pk), [])
        for name in ("occupancy-report", "payment-status-report"):
            for identifier in (
                "bad",
                "-1",
                "0",
                "1.5",
                "9" * 100,
                "9" * 5000,
                "0" * 5000,
                "١",
            ):
                with self.subTest(name=name, identifier=identifier):
                    self.assertEqual(
                        self.client.get(
                            reverse(name),
                            {"hostel": identifier},
                            HTTP_ACCEPT="application/json",
                        ).status_code,
                        400,
                    )
            self.assertEqual(
                self.client.get(
                    reverse(name), {"hostel": 999999}, HTTP_ACCEPT="application/json"
                ).status_code,
                404,
            )
            self.assertEqual(
                self.client.get(reverse(name), {"format": "pdf"}).status_code, 400
            )
            self.assertEqual(self.client.post(reverse(name)).status_code, 405)
        # The other hostel has zero beds and still appears in the CSV.
        self.assertEqual(
            self.csv_rows("occupancy-report", hostel=self.empty.pk)[0]["Occupancy %"],
            "0.00",
        )

    def test_numeric_hostel_filter_accepts_leading_zeros(self):
        identifier = "0" * 5000 + str(self.room.hostel_id)

        self.assertEqual(
            self.rows("occupancy-report", hostel=identifier),
            occupancy_rows(self.room.hostel_id),
        )

    def test_reports_landing_redirects_to_occupancy_report(self):
        response = self.client.get(reverse("reports-home"))
        self.assertRedirects(response, reverse("occupancy-report"))

    def test_reports_allow_admin_warden_and_deny_students_and_anonymous_for_all_formats(
        self,
    ):
        for role, expected in (("admin", 200), ("warden", 200), ("student", 403)):
            self.actor.role = role
            self.actor.save()
            for name in ("occupancy-report", "payment-status-report"):
                for output in ("html", "json", "csv"):
                    self.assertEqual(
                        self.client.get(reverse(name), {"format": output}).status_code,
                        expected,
                    )
        self.client.logout()
        for name in ("occupancy-report", "payment-status-report"):
            self.assertEqual(
                self.client.get(
                    reverse(name), HTTP_ACCEPT="application/json"
                ).status_code,
                401,
            )
            self.assertEqual(
                self.client.get(reverse(name), {"format": "csv"}).status_code, 302
            )

    def test_query_counts_do_not_grow_with_students_or_hostels(self):
        self.allocate()
        self.pay()
        for i in range(2, 8):
            make_student(i)
            make_room(str(100 + i))
        with self.assertNumQueries(2):
            self.assertEqual(len(occupancy_rows()), 8)
        with self.assertNumQueries(1):
            self.assertEqual(len(payment_status_rows()), 7)
