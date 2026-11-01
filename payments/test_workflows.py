from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from io import BytesIO
from threading import Barrier
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.db import (
    IntegrityError,
    close_old_connections,
    connection,
    connections,
    transaction,
)
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone
from pypdf import PdfReader

from accounts.models import User
from allocations.services import allocate, release, transfer
from audit.models import AuditEvent
from hostels.forms import RoomForm
from hostels.models import Room
from tests.factories import make_room, make_student

from .models import Payment, ReceiptSequence
from .services import payment_status_queryset, record_payment, status_row


class PaymentWorkflowTests(TestCase):
    def setUp(self):
        ReceiptSequence.objects.get_or_create(pk=1)
        self.actor = User.objects.create_user(username="payments-warden", role="warden")
        self.student = make_student(name="A & B <Smith>")
        self.room = make_room(fee_amount=Decimal("1000.00"))
        self.client.force_login(self.actor)

    def record(self, **overrides):
        data = dict(
            student=self.student,
            amount="400.00",
            date=timezone.localdate(),
            mode="UPI",
            reference="TEST123",
        )
        return record_payment(actor=self.actor, **(data | overrides))

    def balance(self):
        return status_row(payment_status_queryset().get(pk=self.student.pk))

    def test_numbered_payments_are_permanent_and_audited_for_the_actor(self):
        first = self.record()
        second = self.record(mode="Bank Transfer")
        self.assertEqual(
            (first.receipt_no, second.receipt_no), ("R00000000001", "R00000000002")
        )
        self.assertEqual(first.amount, Decimal("400.00"))
        self.assertEqual(first.student_id, self.student.pk)
        self.assertEqual(
            AuditEvent.objects.filter(user=self.actor, action="payment").count(), 2
        )

    def test_invalid_amounts_modes_dates_and_references_do_not_consume_numbers(self):
        for amount in (
            "0",
            "-1",
            "NaN",
            "Infinity",
            "-Infinity",
            "1.001",
            "100000000",
            "text",
        ):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                self.record(amount=amount)
        for data in (
            {"mode": "Card"},
            {"date": timezone.localdate() + timedelta(days=1)},
            {"date": "invalid"},
            {"reference": "A" * 31},
            {"reference": "invalid/ref"},
        ):
            with self.subTest(data=data), self.assertRaises(ValidationError):
                self.record(**data)
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(ReceiptSequence.objects.get(pk=1).last_value, 0)

    def test_edit_delete_bulk_and_primary_key_replay_are_blocked(self):
        payment = self.record()
        payment.amount = Decimal("1.00")
        attempts = [
            lambda: payment.save(),
            lambda: payment.save(update_fields=["amount"]),
            lambda: payment.delete(),
            lambda: Payment.objects.all().delete(),
            lambda: Payment.objects.update(amount=1),
            lambda: Payment.objects.bulk_update([payment], ["amount"]),
            lambda: Payment.objects.bulk_create(
                [Payment(student=self.student, amount=1, mode="Cash")]
            ),
            lambda: Payment(
                pk=payment.pk, student=self.student, amount=1, mode="Cash"
            ).save(),
            lambda: Payment(
                student=self.student,
                amount=1,
                mode="Cash",
                receipt_no=payment.receipt_no,
            ).save(),
        ]
        for attempt in attempts:
            with self.subTest(attempt=attempt), self.assertRaises(ValidationError):
                attempt()
        payment.refresh_from_db()
        self.assertEqual(payment.amount, Decimal("400.00"))
        self.assertEqual(Payment.objects.count(), 1)

    def test_adjustments_preserve_original_and_validate_their_source_and_net_amount(
        self,
    ):
        original = self.record()
        correction = self.record(
            amount="-100",
            adjustment_of=original,
            adjustment_reason="Duplicate part of entry",
        )
        self.assertEqual(correction.adjustment_of_id, original.pk)
        self.assertEqual(correction.receipt_no, "R00000000002")
        original.refresh_from_db()
        self.assertEqual(original.amount, Decimal("400.00"))
        for data in (
            {
                "amount": "-301",
                "adjustment_of": original,
                "adjustment_reason": "Too much",
            },
            {"amount": "0", "adjustment_of": original, "adjustment_reason": "Zero"},
            {"amount": "-1", "adjustment_of": original},
            {"amount": "-1", "adjustment_of": original, "adjustment_reason": "   "},
            {"amount": "1", "adjustment_reason": "No original"},
            {
                "amount": "1",
                "adjustment_of": correction,
                "adjustment_reason": "Wrong source",
            },
            {
                "student": make_student(2),
                "amount": "1",
                "adjustment_of": original,
                "adjustment_reason": "Wrong student",
            },
        ):
            with self.subTest(data=data), self.assertRaises(ValidationError):
                self.record(**data)
        self.record(
            amount="-300",
            adjustment_of=original,
            adjustment_reason="Reverse the remainder",
        )
        self.assertEqual(self.balance()["paid"], "0.00")
        self.record(
            amount="10", adjustment_of=original, adjustment_reason="Correct the refund"
        )
        self.assertEqual(self.balance()["paid"], "10.00")
        self.assertEqual(Payment.objects.count(), 4)

    def test_adjustment_cannot_predate_original(self):
        original = self.record()
        with self.assertRaises(ValidationError):
            self.record(
                amount="-1",
                date=timezone.localdate() - timedelta(days=1),
                adjustment_of=original,
                adjustment_reason="Earlier date",
            )

    def test_audit_failure_rolls_back_the_payment_and_receipt_counter(self):
        with (
            patch(
                "payments.services.record_event",
                side_effect=RuntimeError("audit unavailable"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.record()
        self.assertEqual(Payment.objects.count(), 0)
        self.assertEqual(ReceiptSequence.objects.get(pk=1).last_value, 0)
        self.assertEqual(self.record().receipt_no, "R00000000001")

    def test_status_tracks_pending_partial_paid_and_adjustments_without_join_multiplication(
        self,
    ):
        allocation = allocate(
            student=self.student, bed=self.room.beds.first(), actor=self.actor
        )
        self.assertEqual(self.balance()["status"], "Pending")
        payment = self.record()
        self.assertEqual(
            (self.balance()["status"], self.balance()["due"]), ("Partial", "600.00")
        )
        self.record(amount="600")
        self.assertEqual(
            (self.balance()["status"], self.balance()["paid"]), ("Paid", "1000.00")
        )
        release(allocation_id=allocation.pk, actor=self.actor)
        self.assertEqual(self.balance()["status"], "Paid")
        next_room = make_room(
            "202", hostel=self.room.hostel, fee_amount=Decimal("2000.00")
        )
        allocation = allocate(
            student=self.student, bed=self.room.beds.first(), actor=self.actor
        )
        transfer(
            allocation_id=allocation.pk,
            new_bed=next_room.beds.first(),
            actor=self.actor,
        )
        self.assertEqual(
            (self.balance()["status"], self.balance()["fee"], self.balance()["paid"]),
            ("Partial", "2000.00", "1000.00"),
        )
        self.record(amount="-400", adjustment_of=payment, adjustment_reason="Refund")
        self.assertEqual(self.balance()["paid"], "600.00")

    def test_no_allocation_or_unconfigured_fee_remains_pending_with_advance_payment(
        self,
    ):
        self.record(amount="1500")
        self.assertEqual(
            (self.balance()["status"], self.balance()["fee_configured"]),
            ("Pending", False),
        )
        self.room.fee_amount = 0
        self.room.save()
        allocate(student=self.student, bed=self.room.beds.first(), actor=self.actor)
        self.assertEqual(
            (self.balance()["status"], self.balance()["fee_configured"]),
            ("Pending", False),
        )

    def test_database_constraints_reject_nonpositive_payments_and_unknown_mode(self):
        payment = self.record()
        for field, value in (("amount", 0), ("amount", -1), ("mode", "Card")):
            with (
                self.subTest(field=field, value=value),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    f"UPDATE payments_payment SET {field}=%s WHERE id=%s",
                    [value, payment.pk],
                )

    def test_receipt_range_exhaustion_fails_without_overwriting_history(self):
        ReceiptSequence.objects.filter(pk=1).update(last_value=99999999999)
        with self.assertRaises(ValidationError):
            self.record()
        self.assertEqual(Payment.objects.count(), 0)

    def test_fee_configuration_rejects_negative_values_and_preserves_legacy_form_posts(
        self,
    ):
        data = dict(
            hostel=self.room.hostel_id,
            room_number="101",
            floor=0,
            room_type="Double",
            capacity=2,
        )
        form = RoomForm(data, instance=self.room)
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.save().fee_amount, Decimal("1000.00"))
        form = RoomForm(data | {"fee_amount": "-1"}, instance=self.room)
        self.assertFalse(form.is_valid())
        self.room.refresh_from_db()
        self.room.fee_amount = Decimal("-1")
        with self.assertRaises(ValidationError):
            self.room.save()
        with self.assertRaises(IntegrityError), transaction.atomic():
            Room.objects.filter(pk=self.room.pk).update(fee_amount=-1)

    def test_json_workflow_receipts_adjustments_and_real_pdf_contents(self):
        response = self.client.post(
            reverse("payment-list"),
            {
                "student_id": self.student.student_id,
                "amount": "400.00",
                "date": timezone.localdate().isoformat(),
                "mode": "UPI",
                "reference": "TEST123",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        receipt = response.json()["receipt_no"]
        url = reverse("payment-receipt", args=[receipt])
        self.assertContains(self.client.get(url), "A &amp; B &lt;Smith&gt;")
        response = self.client.get(reverse("payment-receipt-pdf", args=[receipt]))
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn(f"{receipt}.pdf", response["Content-Disposition"])
        contents = b"".join(response.streaming_content)
        text = " ".join(
            page.extract_text() for page in PdfReader(BytesIO(contents)).pages
        )
        for expected in (
            receipt,
            self.student.student_id,
            self.student.name,
            "400.00",
            "UPI",
            "TEST123",
            timezone.localdate().strftime("%d-%m-%Y"),
        ):
            self.assertIn(expected, text)
        response = self.client.post(
            reverse("payment-adjust", args=[receipt]),
            {
                "amount": "-100",
                "date": timezone.localdate().isoformat(),
                "mode": "Cash",
                "reference": "",
                "adjustment_reason": "Refund <duplicate> & correct",
            },
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201, response.content)
        self.assertEqual(response.json()["adjustment_of"], receipt)
        adjusted = response.json()["receipt_no"]
        response = self.client.get(reverse("payment-receipt-pdf", args=[adjusted]))
        text = " ".join(
            page.extract_text()
            for page in PdfReader(BytesIO(b"".join(response.streaming_content))).pages
        )
        self.assertIn("-100.00", text)
        self.assertIn("Refund <duplicate> & correct", text)
        response = self.client.get(
            reverse("student-payment-status", args=[self.student.pk]),
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.json()["paid"], "300.00")
        self.assertEqual(
            self.client.get(
                reverse("payment-list"), HTTP_ACCEPT="application/json"
            ).json()["total"],
            2,
        )

    def test_invalid_json_fields_missing_records_and_methods(self):
        data = {
            "student_id": self.student.student_id,
            "amount": "1",
            "date": timezone.localdate().isoformat(),
            "mode": "Cash",
        }
        for bad in ("{", "[]", "null"):
            self.assertEqual(
                self.client.post(
                    reverse("payment-list"), bad, content_type="application/json"
                ).status_code,
                400,
            )
        for overrides in (
            {"amount": "NaN"},
            {"amount": "0"},
            {"date": "bad"},
            {"mode": "Card"},
            {"reference": "a/b"},
        ):
            self.assertEqual(
                self.client.post(
                    reverse("payment-list"),
                    data | overrides,
                    content_type="application/json",
                ).status_code,
                400,
            )
        self.assertEqual(
            self.client.post(
                reverse("payment-list"),
                data | {"student_id": "missing"},
                content_type="application/json",
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("payment-receipt", args=["missing"]),
                HTTP_ACCEPT="application/json",
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                reverse("student-payment-status", args=[999999]),
                HTTP_ACCEPT="application/json",
            ).status_code,
            404,
        )
        payment = self.record()
        self.assertEqual(
            self.client.post(
                reverse("payment-receipt", args=[payment.receipt_no])
            ).status_code,
            405,
        )
        self.assertEqual(self.client.delete(reverse("payment-list")).status_code, 405)

    def test_staff_html_forms_and_all_routes_deny_students_and_anonymous_users(self):
        payment = self.record()
        urls = [
            reverse("payment-list"),
            reverse("payment-create"),
            reverse("payment-adjust", args=[payment.receipt_no]),
            reverse("payment-receipt", args=[payment.receipt_no]),
            reverse("payment-receipt-pdf", args=[payment.receipt_no]),
            reverse("student-payment-status", args=[self.student.pk]),
        ]
        for role in ("warden", "admin"):
            self.actor.role = role
            self.actor.save()
            for url in urls:
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200, url)
                if response.streaming:
                    b"".join(response.streaming_content)
        self.actor.role = "student"
        self.actor.save()
        for url in urls:
            self.assertEqual(
                self.client.get(url, HTTP_ACCEPT="application/json").status_code,
                403,
                url,
            )
        self.client.logout()
        for url in urls:
            self.assertEqual(
                self.client.get(url, HTTP_ACCEPT="application/json").status_code,
                401,
                url,
            )

    def test_form_encoded_missing_student_preserves_json_not_found_response(self):
        response = self.client.post(
            reverse("payment-create"),
            {
                "student": 999999,
                "amount": "100",
                "date": timezone.localdate().isoformat(),
                "mode": "Cash",
            },
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")
        self.assertEqual(
            response.json()["error"]["fields"]["student"][0]["code"],
            "invalid_choice",
        )
        self.assertFalse(Payment.objects.exists())

    def test_payment_and_adjustment_forms_require_csrf_and_work_with_a_valid_token(
        self,
    ):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        client.get(reverse("payment-create"))
        data = {
            "student": self.student.pk,
            "amount": "100",
            "date": timezone.localdate().isoformat(),
            "mode": "Cash",
        }
        self.assertEqual(client.post(reverse("payment-create"), data).status_code, 403)
        token = client.cookies["csrftoken"].value
        self.assertEqual(
            client.post(
                reverse("payment-create"), data, HTTP_X_CSRFTOKEN=token
            ).status_code,
            302,
        )
        payment = Payment.objects.get()
        url = reverse("payment-adjust", args=[payment.receipt_no])
        correction = {
            "amount": "-100",
            "date": timezone.localdate().isoformat(),
            "mode": "Cash",
            "adjustment_reason": "Refund",
        }
        self.assertEqual(client.post(url, correction).status_code, 403)
        self.assertEqual(
            client.post(url, correction, HTTP_X_CSRFTOKEN=token).status_code, 302
        )


class PaymentConcurrencyTests(TransactionTestCase):
    def setUp(self):
        ReceiptSequence.objects.get_or_create(pk=1)
        self.actor = User.objects.create_user(
            username="parallel-payments", role="warden"
        )
        self.students = [make_student(i) for i in range(1, 5)]

    def concurrent(self, operations):
        barrier = Barrier(len(operations), timeout=20)

        def run(operation):
            close_old_connections()
            try:
                barrier.wait()
                return operation().receipt_no
            except ValidationError:
                return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            return list(pool.map(run, operations))

    def test_simultaneous_payments_receive_unique_sequential_numbers(self):
        receipts = self.concurrent(
            [
                lambda student=student: record_payment(
                    actor=self.actor, student=student, amount="100", mode="Cash"
                )
                for student in self.students
            ]
        )
        self.assertEqual(sorted(receipts), [f"R{i:011d}" for i in range(1, 5)])
        self.assertEqual(Payment.objects.count(), 4)
        self.assertEqual(AuditEvent.objects.filter(action="payment").count(), 4)

    def test_competing_corrections_cannot_reverse_a_payment_twice(self):
        original = record_payment(
            actor=self.actor, student=self.students[0], amount="100", mode="Cash"
        )
        receipts = self.concurrent(
            [
                lambda: record_payment(
                    actor=self.actor,
                    student=self.students[0],
                    amount="-80",
                    mode="Cash",
                    adjustment_of=original,
                    adjustment_reason="Correction",
                )
                for _ in range(2)
            ]
        )
        self.assertEqual(sorted(receipts), ["R00000000002", "rejected"])
        self.assertEqual(Payment.objects.count(), 2)
        self.assertEqual(ReceiptSequence.objects.get(pk=1).last_value, 2)
