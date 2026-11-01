from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models, transaction


class Hostel(models.Model):
    class HostelType(models.TextChoices):
        BOYS = "Boys", "Boys"
        GIRLS = "Girls", "Girls"

    name = models.CharField(max_length=100, unique=True)
    hostel_type = models.CharField(max_length=5, choices=HostelType.choices)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class RoomQuerySet(models.QuerySet):
    SYNC_FIELDS = {"capacity", "room_number"}

    def update(self, **kwargs):
        if self.SYNC_FIELDS.intersection(kwargs):
            raise ValueError(
                "Use Room.save() to change capacity or room_number "
                "so beds can be synchronized."
            )
        return super().update(**kwargs)

    def bulk_update(self, objs, fields, batch_size=None):
        if self.SYNC_FIELDS.intersection(fields):
            raise ValueError(
                "Use Room.save() to change capacity or room_number "
                "so beds can be synchronized."
            )
        return super().bulk_update(objs, fields, batch_size=batch_size)


class Room(models.Model):
    objects = RoomQuerySet.as_manager()

    class RoomType(models.TextChoices):
        SINGLE = "Single", "Single"
        DOUBLE = "Double", "Double"
        TRIPLE = "Triple", "Triple"

    hostel = models.ForeignKey(
        Hostel,
        on_delete=models.PROTECT,
        related_name="rooms",
    )
    room_number = models.CharField(max_length=10)
    floor = models.PositiveSmallIntegerField()
    room_type = models.CharField(max_length=10, choices=RoomType.choices)
    capacity = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(4)]
    )
    fee_amount = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        default=Decimal("0.00"),
        validators=[MinValueValidator(Decimal("0.00"))],
        help_text="Room fee in INR. Set a positive fee before using payment status.",
    )

    class Meta:
        ordering = ["hostel", "floor", "room_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["hostel", "room_number"],
                name="unique_room_number_per_hostel",
            ),
            models.CheckConstraint(
                condition=models.Q(fee_amount__gte=0), name="nonnegative_room_fee"
            ),
        ]

    def clean(self):
        super().clean()

        if self.capacity is not None and not 1 <= self.capacity <= 4:
            raise ValidationError({"capacity": "Capacity must be between 1 and 4."})

        if not self.pk or self.capacity is None:
            return

        from allocations.models import Allocation

        allocated_beds = (
            self.beds.filter(allocations__status=Allocation.AllocationStatus.ACTIVE)
            .distinct()
            .count()
        )

        if allocated_beds > self.capacity:
            raise ValidationError(
                {
                    "capacity": (
                        f"This room has {allocated_beds} beds with active "
                        "allocations. Complete or move allocations before "
                        "reducing capacity further."
                    )
                }
            )

    @transaction.atomic
    def save(self, *args, **kwargs):
        old_room_number = None
        self.fee_amount = self._meta.get_field("fee_amount").clean(
            self.fee_amount, self
        )

        if self.pk:
            previous = Room.objects.select_for_update().get(pk=self.pk)
            old_room_number = previous.room_number

        super().save(*args, **kwargs)

        # Rename existing bed labels when the room number changes.
        if old_room_number is not None and old_room_number != self.room_number:
            for bed in self.beds.select_for_update().all():
                suffix = bed.label.rsplit("-", 1)[-1]
                bed.label = f"{self.room_number}-{suffix}"
                bed.save(update_fields=["label"])

        # Remove excess beds only when they have no allocation history.
        # Beds with allocation records must be preserved.
        if self.beds.count() > self.capacity:
            removable_beds = (
                self.beds.exclude(allocations__isnull=False)
                .order_by("-label")
                .distinct()
            )

            excess = self.beds.count() - self.capacity

            for bed in removable_beds[:excess]:
                bed.delete()

        # Create missing beds without duplicating existing labels.
        for suffix in ["A", "B", "C", "D"][: self.capacity]:
            Bed.objects.get_or_create(
                room=self,
                label=f"{self.room_number}-{suffix}",
                defaults={"status": Bed.BedStatus.AVAILABLE},
            )

        # A historical or allocated bed may need to remain beyond capacity.
        # Never silently delete a bed that has an allocation record.
        if self.beds.count() > self.capacity:
            from allocations.models import Allocation

            active_bed_count = (
                self.beds.filter(allocations__status=Allocation.AllocationStatus.ACTIVE)
                .distinct()
                .count()
            )

            if active_bed_count > self.capacity:
                raise ValidationError(
                    "Capacity cannot be reduced below the number of "
                    "beds with active allocations."
                )

    def __str__(self):
        return f"{self.hostel.name} - Room {self.room_number}"


class Bed(models.Model):
    class BedStatus(models.TextChoices):
        AVAILABLE = "Available", "Available"
        OCCUPIED = "Occupied", "Occupied"
        MAINTENANCE = "Maintenance", "Under maintenance"

    room = models.ForeignKey(
        Room,
        on_delete=models.PROTECT,
        related_name="beds",
    )
    label = models.CharField(max_length=20)
    status = models.CharField(
        max_length=12,
        choices=BedStatus.choices,
        default=BedStatus.AVAILABLE,
    )

    class Meta:
        ordering = ["room", "label"]
        constraints = [
            models.UniqueConstraint(
                fields=["room", "label"],
                name="unique_bed_label_per_room",
            )
        ]

    def __str__(self):
        return self.label
