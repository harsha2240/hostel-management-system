from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
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

from accounts.models import User
from audit.models import AuditEvent
from hostels.models import Bed
from students.models import Student
from tests.factories import make_room, make_student

from .models import Allocation
from .services import allocate, release, transfer


class AllocationWorkflowTests(TestCase):
    def setUp(self):
        self.actor = User.objects.create_user(username="workflow-warden", role="warden")
        self.student = make_student()
        self.room = make_room()
        self.bed, self.other = self.room.beds.all()
        self.client.force_login(self.actor)

    def create(self):
        return allocate(student=self.student, bed=self.bed, actor=self.actor)

    def test_json_date_types_return_400_without_changing_allocations(self):
        values = (123, True, ["2026-10-26"], {"day": 26})
        before_audits = AuditEvent.objects.count()
        for value in values:
            with self.subTest(action="allocate", value=value):
                response = self.client.post(
                    reverse("allocation-list"),
                    {
                        "student_id": self.student.student_id,
                        "bed_id": self.bed.pk,
                        "allocated_on": value,
                    },
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)
                if isinstance(value, (int, bool)):
                    self.assertEqual(
                        response.json()["error"]["fields"]["allocated_on"][0]["code"],
                        "invalid",
                    )
        self.assertFalse(Allocation.objects.exists())
        self.assertEqual(AuditEvent.objects.count(), before_audits)

        original = self.create()
        before_audits = AuditEvent.objects.count()
        for value in values:
            with self.subTest(action="release", value=value):
                response = self.client.post(
                    reverse("allocation-release", args=[original.pk]),
                    {"vacate_date": value},
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 400)
                if isinstance(value, (int, bool)):
                    self.assertEqual(
                        response.json()["error"]["fields"]["vacate_date"][0]["code"],
                        "invalid",
                    )
        original.refresh_from_db()
        self.bed.refresh_from_db()
        self.assertEqual(original.status, "Active")
        self.assertEqual(self.bed.status, "Occupied")
        self.assertEqual(AuditEvent.objects.count(), before_audits)

    def test_json_reference_types_cannot_select_a_different_integer_key(self):
        before_audits = AuditEvent.objects.count()
        for value in (self.bed.pk + 0.5, float(self.bed.pk), True, False):
            with self.subTest(action="allocate", value=value):
                response = self.client.post(
                    reverse("allocation-list"),
                    {"student_id": self.student.student_id, "bed_id": value},
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")
        self.assertFalse(Allocation.objects.exists())
        self.assertEqual(AuditEvent.objects.count(), before_audits)

        original = self.create()
        before_audits = AuditEvent.objects.count()
        for value in (self.other.pk + 0.5, float(self.other.pk), True, False):
            with self.subTest(action="transfer", value=value):
                response = self.client.post(
                    reverse("allocation-transfer", args=[original.pk]),
                    {"new_bed_id": value},
                    content_type="application/json",
                )
                self.assertEqual(response.status_code, 404)
        original.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(original.status, "Active")
        self.assertEqual(self.other.status, "Available")
        self.assertEqual(Allocation.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.count(), before_audits)

    def test_transfer_and_release_preserve_history_and_emit_actor_audit(self):
        original = self.create()
        successor = transfer(
            allocation_id=original.pk, new_bed=self.other, actor=self.actor
        )
        original.refresh_from_db()
        self.bed.refresh_from_db()
        self.other.refresh_from_db()
        self.assertNotEqual(original.pk, successor.pk)
        self.assertEqual(original.bed_id, self.bed.pk)
        self.assertEqual(original.status, "Completed")
        self.assertEqual(self.bed.status, "Available")
        self.assertEqual(self.other.status, "Occupied")
        release(allocation_id=successor.pk, actor=self.actor)
        self.assertEqual(Allocation.objects.filter(status="Active").count(), 0)
        response = self.client.get(
            reverse("allocation-history", args=[self.student.pk]),
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(
            [a["allocation_id"] for a in response.json()["allocations"]],
            [successor.pk, original.pk],
        )
        self.assertEqual(
            set(
                AuditEvent.objects.filter(user=self.actor).values_list(
                    "action", flat=True
                )
            ),
            {"allocate", "transfer", "release", "login"},
        )

    def test_invalid_eligibility_gender_status_and_dates_are_rejected(self):
        for field, value in (("status", "Inactive"), ("gender", "Female")):
            with self.subTest(field=field):
                setattr(self.student, field, value)
                self.student.save()
                with self.assertRaises(ValidationError):
                    self.create()
                self.student.status, self.student.gender = "Active", "Male"
                self.student.save()
        for state in ("Occupied", "Maintenance"):
            self.bed.status = state
            self.bed.save()
            with self.assertRaises(ValidationError):
                self.create()
        self.bed.status = "Available"
        self.bed.save()
        with self.assertRaises(ValidationError):
            allocate(
                student=self.student,
                bed=self.bed,
                actor=self.actor,
                allocated_on=timezone.localdate() + timedelta(days=1),
            )
        self.assertEqual(Allocation.objects.count(), 0)

    def test_model_deactivation_and_history_cannot_bypass_guards(self):
        allocation = self.create()
        self.student.status = "Inactive"
        with self.assertRaises(ValidationError):
            self.student.save(update_fields=["status"])
        with self.assertRaises(ValidationError):
            Student.objects.filter(pk=self.student.pk).update(status="Inactive")
        allocation.bed = self.other
        with self.assertRaises(ValidationError):
            allocation.save()
        with self.assertRaises(ValidationError):
            allocation.delete()
        with self.assertRaises(ValidationError):
            Allocation.objects.all().delete()
        with self.assertRaises(ValidationError):
            Allocation.objects.update(status="Completed")
        with self.assertRaises(ValidationError):
            Allocation.objects.bulk_create(
                [Allocation(student=self.student, bed=self.other)]
            )

    def test_database_rejects_forged_or_missing_active_keys(self):
        allocation = self.create()
        for field in ("active_student_id", "active_bed_id"):
            with (
                self.subTest(field=field),
                self.assertRaises(IntegrityError),
                transaction.atomic(),
                connection.cursor() as cursor,
            ):
                cursor.execute(
                    f"UPDATE allocations_allocation SET {field}=NULL WHERE id=%s",
                    [allocation.pk],
                )

    def test_transfer_failure_rolls_back_both_beds_and_history(self):
        original = self.create()
        save = Bed.save

        def fail_target(bed, *args, **kwargs):
            if bed.pk == self.other.pk and bed.status == "Occupied":
                raise RuntimeError("simulated storage failure")
            return save(bed, *args, **kwargs)

        with (
            patch.object(Bed, "save", new=fail_target),
            self.assertRaises(RuntimeError),
        ):
            transfer(allocation_id=original.pk, new_bed=self.other, actor=self.actor)
        original.refresh_from_db()
        self.bed.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(
            (original.status, self.bed.status, self.other.status),
            ("Active", "Occupied", "Available"),
        )
        self.assertEqual(Allocation.objects.count(), 1)
        self.assertFalse(AuditEvent.objects.filter(action="transfer").exists())

    def test_audit_failure_rolls_back_allocation_and_release(self):
        with (
            patch(
                "allocations.services.record_event",
                side_effect=RuntimeError("audit unavailable"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.create()
        self.bed.refresh_from_db()
        self.assertEqual(self.bed.status, "Available")
        self.assertEqual(Allocation.objects.count(), 0)
        allocation = self.create()
        with (
            patch(
                "allocations.services.record_event",
                side_effect=RuntimeError("audit unavailable"),
            ),
            self.assertRaises(RuntimeError),
        ):
            release(allocation_id=allocation.pk, actor=self.actor)
        allocation.refresh_from_db()
        self.bed.refresh_from_db()
        self.assertEqual((allocation.status, self.bed.status), ("Active", "Occupied"))

    def test_json_workflow_conflicts_validation_and_permissions(self):
        response = self.client.post(
            reverse("allocation-list"),
            {"student_id": self.student.student_id, "bed_id": self.bed.pk},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 201)
        pk = response.json()["allocation_id"]
        response = self.client.post(
            reverse("allocation-list"),
            {"student_id": self.student.student_id, "bed_id": self.other.pk},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 409)
        response = self.client.post(
            reverse("allocation-transfer", args=[pk]),
            {"new_bed_id": self.other.pk},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        target = response.json()["allocation_id"]
        response = self.client.post(
            reverse("allocation-release", args=[target]),
            {"vacate_date": "bad-date"},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        response = self.client.post(
            reverse("allocation-release", args=[target]),
            {"vacate_date": timezone.localdate().isoformat()},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            self.client.post(
                reverse("allocation-release", args=[target]),
                {"vacate_date": timezone.localdate().isoformat()},
                content_type="application/json",
            ).status_code,
            409,
        )
        self.assertEqual(
            self.client.post(
                reverse("allocation-list"), "{", content_type="application/json"
            ).status_code,
            400,
        )
        self.actor.role = "student"
        self.actor.save()
        for url in (
            reverse("allocation-list"),
            reverse("allocation-transfer", args=[pk]),
            reverse("allocation-history", args=[self.student.pk]),
        ):
            self.assertEqual(
                self.client.get(url, HTTP_ACCEPT="application/json").status_code, 403
            )

    def test_new_write_routes_require_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.actor)
        client.get(reverse("allocation-create"))
        self.assertEqual(
            client.post(
                reverse("allocation-list"),
                {"student": self.student.pk, "bed": self.bed.pk},
            ).status_code,
            403,
        )
        token = client.cookies["csrftoken"].value
        self.assertEqual(
            client.post(
                reverse("allocation-create"),
                {"student": self.student.pk, "bed": self.bed.pk},
                HTTP_X_CSRFTOKEN=token,
            ).status_code,
            302,
        )

    def test_json_form_errors_preserve_reference_and_validation_status_codes(self):
        response = self.client.post(
            reverse("allocation-create"),
            {"student_id": self.student.student_id, "bed_id": 999999},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")
        self.assertEqual(
            response.json()["error"]["fields"]["bed"][0]["code"], "invalid_choice"
        )

        allocation = self.create()
        response = self.client.post(
            reverse("allocation-transfer", args=[allocation.pk]),
            {"new_bed_id": 999999},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "NOT_FOUND")
        self.assertIn("new_bed", response.json()["error"]["fields"])

        response = self.client.post(
            reverse("allocation-release", args=[allocation.pk]),
            {},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"]["code"], "VALIDATION_ERROR")
        self.assertIn("vacate_date", response.json()["error"]["fields"])
        allocation.refresh_from_db()
        self.assertEqual(allocation.status, "Active")


class AllocationConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.actor = User.objects.create_user(
            username="concurrent-warden", role="warden"
        )
        self.student = make_student()
        self.second = make_student(2)
        self.room = make_room()
        self.bed, self.other = self.room.beds.all()

    def concurrent(self, operations):
        barrier = Barrier(len(operations), timeout=20)

        def run(operation):
            close_old_connections()
            try:
                barrier.wait()
                operation()
                return "ok"
            except ValidationError:
                return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as pool:
            return list(pool.map(run, operations))

    def test_simultaneous_same_bed_or_same_student_has_one_winner(self):
        statuses = self.concurrent(
            [
                lambda: allocate(student=self.student, bed=self.bed, actor=self.actor),
                lambda: allocate(student=self.second, bed=self.bed, actor=self.actor),
            ]
        )
        self.assertEqual(sorted(statuses), ["ok", "rejected"])
        allocation = Allocation.objects.get(status="Active")
        release(allocation_id=allocation.pk, actor=self.actor)
        statuses = self.concurrent(
            [
                lambda: allocate(student=self.student, bed=self.bed, actor=self.actor),
                lambda: allocate(
                    student=self.student, bed=self.other, actor=self.actor
                ),
            ]
        )
        self.assertEqual(sorted(statuses), ["ok", "rejected"])
        self.assertEqual(Allocation.objects.filter(status="Active").count(), 1)

    def test_allocation_racing_deactivation_preserves_student_eligibility(self):
        def deactivate():
            student = Student.objects.get(pk=self.student.pk)
            student.status = "Inactive"
            student.save()

        self.concurrent(
            [
                lambda: allocate(student=self.student, bed=self.bed, actor=self.actor),
                deactivate,
            ]
        )
        self.student.refresh_from_db()
        active = Allocation.objects.filter(
            student=self.student, status="Active"
        ).exists()
        self.assertEqual(self.student.status, "Active" if active else "Inactive")

    def test_cross_room_transfers_lock_rooms_in_consistent_order(self):
        second_room = make_room("202", hostel=self.room.hostel)
        second_bed, second_target = second_room.beds.all()
        first = allocate(student=self.student, bed=self.bed, actor=self.actor)
        second = allocate(student=self.second, bed=second_bed, actor=self.actor)
        statuses = self.concurrent(
            [
                lambda: transfer(
                    allocation_id=first.pk, new_bed=second_target, actor=self.actor
                ),
                lambda: transfer(
                    allocation_id=second.pk, new_bed=self.other, actor=self.actor
                ),
            ]
        )
        self.assertEqual(statuses, ["ok", "ok"])
        self.assertEqual(Allocation.objects.count(), 4)
        self.assertEqual(Allocation.objects.filter(status="Active").count(), 2)
