from datetime import date

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone


class AllocationQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Use allocation operations to preserve bed consistency.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Save allocations individually to update their beds.")

    def delete(self):
        raise ValidationError("Allocation history cannot be deleted.")


class Allocation(models.Model):
    class AllocationStatus(models.TextChoices):
        ACTIVE = "Active", "Active"
        COMPLETED = "Completed", "Completed"
        CANCELLED = "Cancelled", "Cancelled"

    student = models.ForeignKey(
        "students.Student", on_delete=models.PROTECT, related_name="allocations"
    )
    bed = models.ForeignKey(
        "hostels.Bed", on_delete=models.PROTECT, related_name="allocations"
    )
    allocated_on = models.DateField(default=timezone.localdate)
    vacated_on = models.DateField(blank=True, null=True)
    status = models.CharField(
        max_length=10, choices=AllocationStatus.choices, default=AllocationStatus.ACTIVE
    )
    active_student_id = models.PositiveBigIntegerField(
        null=True, blank=True, unique=True, editable=False
    )
    active_bed_id = models.PositiveBigIntegerField(
        null=True, blank=True, unique=True, editable=False
    )
    objects = AllocationQuerySet.as_manager()

    class Meta:
        ordering = ["-allocated_on", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=["Active", "Completed", "Cancelled"]),
                name="allocation_valid_status",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        status="Active",
                        vacated_on__isnull=True,
                        active_student_id__isnull=False,
                        active_bed_id__isnull=False,
                        active_student_id=F("student_id"),
                        active_bed_id=F("bed_id"),
                    )
                    | (
                        ~Q(status="Active")
                        & Q(
                            vacated_on__isnull=False,
                            active_student_id__isnull=True,
                            active_bed_id__isnull=True,
                        )
                    )
                ),
                name="allocation_active_keys_consistent",
            ),
            models.CheckConstraint(
                condition=Q(vacated_on__isnull=True)
                | Q(vacated_on__gte=F("allocated_on")),
                name="allocation_dates_ordered",
            ),
        ]

    def clean(self):
        super().clean()
        if not isinstance(self.allocated_on, date):
            raise ValidationError({"allocated_on": "Enter a valid allocation date."})
        if self.vacated_on is not None and not isinstance(self.vacated_on, date):
            raise ValidationError({"vacated_on": "Enter a valid vacate date."})
        today = timezone.localdate()
        if self.allocated_on and self.allocated_on > today:
            raise ValidationError(
                {"allocated_on": "Allocation date cannot be in the future."}
            )
        if self.vacated_on and (
            self.vacated_on < self.allocated_on or self.vacated_on > today
        ):
            raise ValidationError(
                {"vacated_on": "Vacate date must be between allocation date and today."}
            )
        if self.status == self.AllocationStatus.ACTIVE and self.vacated_on:
            raise ValidationError(
                {"vacated_on": "An active allocation cannot have a vacate date."}
            )
        if self.status != self.AllocationStatus.ACTIVE and not self.vacated_on:
            raise ValidationError(
                {"vacated_on": "Enter a vacate date for an inactive allocation."}
            )

    @transaction.atomic
    def save(self, *args, **kwargs):
        from hostels.models import Bed, Hostel, Room
        from students.models import Student

        # Lock Student, then Rooms/Beds in PK order, then Allocation.
        # Student deactivation takes the same Student lock.
        try:
            student = Student.objects.select_for_update().get(pk=self.student_id)
            room_id = Bed.objects.values_list("room_id", flat=True).get(pk=self.bed_id)
            Room.objects.select_for_update().get(pk=room_id)
            bed = (
                Bed.objects.select_for_update()
                .select_related("room__hostel")
                .get(pk=self.bed_id)
            )
        except (Student.DoesNotExist, Room.DoesNotExist, Bed.DoesNotExist):
            raise ValidationError(
                "The selected student or bed no longer exists.", code="NOT_FOUND"
            ) from None
        previous = None
        if not self._state.adding:
            previous = Allocation.objects.select_for_update().get(pk=self.pk)
            if any(
                getattr(previous, field) != getattr(self, field)
                for field in ("student_id", "bed_id", "allocated_on")
            ):
                raise ValidationError(
                    "Allocation history is immutable; use transfer instead.",
                    code="IMMUTABLE_FIELD",
                )
            if previous.status != self.AllocationStatus.ACTIVE:
                raise ValidationError(
                    "This allocation is already inactive.", code="ALREADY_RELEASED"
                )

        active = self.status == self.AllocationStatus.ACTIVE
        self.active_student_id = self.student_id if active else None
        self.active_bed_id = self.bed_id if active else None
        if active:
            if student.status != Student.Status.ACTIVE:
                raise ValidationError(
                    "Only active students can be allocated beds.",
                    code="INACTIVE_STUDENT",
                )
            if not bed.room.hostel.is_active:
                raise ValidationError(
                    "This hostel is inactive.", code="INACTIVE_HOSTEL"
                )
            expected = {
                Student.Gender.MALE: Hostel.HostelType.BOYS,
                Student.Gender.FEMALE: Hostel.HostelType.GIRLS,
            }.get(student.gender)
            if bed.room.hostel.hostel_type != expected:
                raise ValidationError(
                    "Student gender does not match the hostel type.",
                    code="GENDER_MISMATCH",
                )
            if (
                Allocation.objects.filter(
                    student_id=student.pk, status=self.AllocationStatus.ACTIVE
                )
                .exclude(pk=self.pk)
                .exists()
            ):
                raise ValidationError(
                    "This student already has an active allocation.",
                    code="ALREADY_ALLOCATED",
                )
            if (
                Allocation.objects.filter(
                    bed_id=bed.pk, status=self.AllocationStatus.ACTIVE
                )
                .exclude(pk=self.pk)
                .exists()
            ):
                raise ValidationError(
                    "This bed already has an active allocation.", code="BED_OCCUPIED"
                )
            if previous is None and bed.status != Bed.BedStatus.AVAILABLE:
                raise ValidationError(
                    "Select an available bed; occupied and maintenance beds cannot be allocated.",
                    code="BED_OCCUPIED",
                )
        self.full_clean()
        if self._state.adding:
            kwargs["force_insert"] = True
        if kwargs.get("update_fields") is not None:
            kwargs["update_fields"] = set(kwargs["update_fields"]) | {
                "active_student_id",
                "active_bed_id",
            }
        result = super().save(*args, **kwargs)
        if active:
            bed.status = Bed.BedStatus.OCCUPIED
            bed.save(update_fields=["status"])
        elif previous and bed.status == Bed.BedStatus.OCCUPIED:
            bed.status = Bed.BedStatus.AVAILABLE
            bed.save(update_fields=["status"])
        self.student, self.bed = student, bed
        return result

    def delete(self, *args, **kwargs):
        raise ValidationError("Allocation history cannot be deleted.")

    def __str__(self):
        return f"{self.student.student_id} - {self.bed.label} ({self.status})"
