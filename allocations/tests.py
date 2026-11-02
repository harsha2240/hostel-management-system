from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from allocations.models import Allocation
from audit.models import AuditEvent
from hostels.models import Bed
from tests.factories import make_room, make_student


class AllocationModelTests(TestCase):
    def setUp(self):
        self.student1 = make_student()
        self.student2 = make_student(2)
        self.bed1, self.bed2 = make_room().beds.all()

    def test_active_allocation_occupies_bed(self):
        allocation = Allocation(
            student=self.student1,
            bed=self.bed1,
        )
        allocation.save()

        self.bed1.refresh_from_db()
        self.assertEqual(self.bed1.status, Bed.BedStatus.OCCUPIED)
        self.assertEqual(
            allocation.active_student_id,
            self.student1.pk,
        )
        self.assertEqual(allocation.active_bed_id, self.bed1.pk)

    def test_student_cannot_have_two_active_allocations(self):
        Allocation.objects.create(
            student=self.student1,
            bed=self.bed1,
        )

        with self.assertRaises(ValidationError):
            Allocation.objects.create(
                student=self.student1,
                bed=self.bed2,
            )

    def test_bed_cannot_have_two_active_allocations(self):
        Allocation.objects.create(
            student=self.student1,
            bed=self.bed1,
        )

        with self.assertRaises(ValidationError):
            Allocation.objects.create(
                student=self.student2,
                bed=self.bed1,
            )

    def test_maintenance_bed_cannot_be_allocated(self):
        self.bed1.status = Bed.BedStatus.MAINTENANCE
        self.bed1.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            Allocation.objects.create(
                student=self.student1,
                bed=self.bed1,
            )

    def test_completing_allocation_releases_bed(self):
        allocation = Allocation.objects.create(
            student=self.student1,
            bed=self.bed1,
        )

        allocation.status = Allocation.AllocationStatus.COMPLETED
        allocation.vacated_on = timezone.localdate()
        allocation.save()

        self.bed1.refresh_from_db()
        self.assertEqual(self.bed1.status, Bed.BedStatus.AVAILABLE)
        self.assertIsNone(allocation.active_student_id)
        self.assertIsNone(allocation.active_bed_id)

    def test_completing_allocation_preserves_maintenance_status(self):
        allocation = Allocation.objects.create(
            student=self.student1,
            bed=self.bed1,
        )

        self.bed1.status = Bed.BedStatus.MAINTENANCE
        self.bed1.save(update_fields=["status"])

        allocation.status = Allocation.AllocationStatus.COMPLETED
        allocation.vacated_on = timezone.localdate()
        allocation.save()

        self.bed1.refresh_from_db()
        self.assertEqual(self.bed1.status, Bed.BedStatus.MAINTENANCE)


class AllocationViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="allocation_admin",
            role=User.Role.ADMIN,
        )

        self.student_user = User.objects.create_user(
            username="allocation_student",
            role=User.Role.STUDENT,
        )

        self.student = make_student()
        self.bed = make_room("201").beds.get(label="201-A")

    def test_admin_can_view_allocation_list(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("allocation-list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Hostel Allocations")

    def test_admin_can_open_allocation_form(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse("allocation-create"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Create Hostel Allocation")
        self.assertContains(response, self.student.student_id)

    def test_student_cannot_manage_allocations(self):
        self.client.force_login(self.student_user)

        self.assertEqual(
            self.client.get(reverse("allocation-list")).status_code,
            403,
        )
        self.assertEqual(
            self.client.get(reverse("allocation-create")).status_code,
            403,
        )

    def test_admin_can_create_allocation(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse("allocation-create"),
            {
                "student": self.student.pk,
                "bed": self.bed.pk,
                "allocated_on": timezone.localdate().isoformat(),
            },
        )

        self.assertRedirects(response, reverse("allocation-list"))

        allocation = Allocation.objects.get(student=self.student)
        self.assertEqual(allocation.bed, self.bed)
        self.assertEqual(
            allocation.status,
            Allocation.AllocationStatus.ACTIVE,
        )
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.ALLOCATE,
            record_type="allocations.allocation",
            record_id=str(allocation.pk),
        )
        self.assertEqual(event.user, self.admin)

        self.bed.refresh_from_db()
        self.assertEqual(self.bed.status, Bed.BedStatus.OCCUPIED)

    def test_allocation_creation_rolls_back_if_audit_event_fails(self):
        self.client.force_login(self.admin)

        with (
            patch(
                "allocations.services.record_event",
                side_effect=RuntimeError("audit write failed"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(
                reverse("allocation-create"),
                {"student": self.student.pk, "bed": self.bed.pk},
            )

        self.assertFalse(Allocation.objects.filter(student=self.student).exists())
        self.bed.refresh_from_db()
        self.assertEqual(self.bed.status, Bed.BedStatus.AVAILABLE)

    def test_release_rolls_back_if_audit_event_fails(self):
        self.client.force_login(self.admin)
        allocation = Allocation.objects.create(
            student=self.student,
            bed=self.bed,
        )

        with (
            patch(
                "allocations.services.record_event",
                side_effect=RuntimeError("audit write failed"),
            ),
            self.assertRaises(RuntimeError),
        ):
            self.client.post(
                reverse("allocation-complete", args=[allocation.pk]),
            )

        allocation.refresh_from_db()
        self.assertEqual(allocation.status, Allocation.AllocationStatus.ACTIVE)
        self.bed.refresh_from_db()
        self.assertEqual(self.bed.status, Bed.BedStatus.OCCUPIED)

    def test_admin_can_complete_allocation(self):
        self.client.force_login(self.admin)

        allocation = Allocation.objects.create(
            student=self.student,
            bed=self.bed,
        )

        response = self.client.post(
            reverse("allocation-complete", args=[allocation.pk]),
        )

        self.assertRedirects(response, reverse("allocation-list"))

        allocation.refresh_from_db()
        self.assertEqual(
            allocation.status,
            Allocation.AllocationStatus.COMPLETED,
        )
        self.assertIsNotNone(allocation.vacated_on)

        self.bed.refresh_from_db()
        self.assertEqual(self.bed.status, Bed.BedStatus.AVAILABLE)
        event = AuditEvent.objects.get(
            action=AuditEvent.Action.RELEASE,
            record_type="allocations.allocation",
            record_id=str(allocation.pk),
        )
        self.assertEqual(event.user, self.admin)
