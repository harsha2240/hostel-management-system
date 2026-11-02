"""Append-only payments with transactional, sequential receipt numbers."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.db.models import Q, Sum
from django.utils import timezone

from students.models import Student


class ReceiptSequence(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    last_value = models.PositiveBigIntegerField(default=0)

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name="single_receipt_sequence"),
            models.CheckConstraint(
                condition=Q(last_value__lte=99999999999), name="receipt_sequence_limit"
            ),
        ]


class PaymentQuerySet(models.QuerySet):
    def immutable(self, *args, **kwargs):
        raise ValidationError(
            "Payments are permanent. Record a new adjusting entry to make a correction.",
            code="IMMUTABLE_FIELD",
        )

    update = delete = bulk_create = bulk_update = immutable


class Payment(models.Model):
    class Mode(models.TextChoices):
        CASH = "Cash", "Cash"
        UPI = "UPI", "UPI"
        BANK_TRANSFER = "Bank Transfer", "Bank Transfer"

    student = models.ForeignKey(
        Student, on_delete=models.PROTECT, related_name="payments"
    )
    receipt_no = models.CharField(max_length=12, unique=True, editable=False)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField(default=timezone.localdate)
    mode = models.CharField(max_length=15, choices=Mode.choices)
    reference = models.CharField(
        max_length=30,
        blank=True,
        validators=[RegexValidator(r"^[A-Za-z0-9]*$", "Use letters and numbers only.")],
    )
    adjustment_of = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="adjustments",
    )
    adjustment_reason = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = PaymentQuerySet.as_manager()

    class Meta:
        ordering = ["-date", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(adjustment_of__isnull=True, amount__gt=0, adjustment_reason="")
                    | (
                        Q(adjustment_of__isnull=False)
                        & ~Q(amount=0)
                        & ~Q(adjustment_reason="")
                    )
                ),
                name="payment_or_reasoned_adjustment",
            ),
            models.CheckConstraint(
                condition=Q(mode__in=["Cash", "UPI", "Bank Transfer"]),
                name="valid_payment_mode",
            ),
        ]

    def __str__(self):
        return self.receipt_no

    def clean(self):
        super().clean()
        if isinstance(self.date, date) and self.date > timezone.localdate():
            raise ValidationError({"date": "Payment date cannot be in the future."})
        if isinstance(self.adjustment_reason, str):
            self.adjustment_reason = self.adjustment_reason.strip()
        if (
            isinstance(self.amount, Decimal)
            and self.amount.is_finite()
            and (self.amount == 0 or (not self.adjustment_of_id and self.amount < 0))
        ):
            raise ValidationError(
                {"amount": "Enter a positive payment or a nonzero adjustment."}
            )
        if bool(self.adjustment_of_id) != bool(self.adjustment_reason):
            raise ValidationError(
                {
                    "adjustment_reason": "A correction must identify the original payment and give a reason."
                }
            )

    @transaction.atomic
    def save(self, *args, **kwargs):
        if not self._state.adding or self.pk is not None or self.receipt_no:
            raise ValidationError(
                "Payments cannot be edited. Record a new adjusting entry.",
                code="IMMUTABLE_FIELD",
            )
        if (
            args
            or kwargs.get("force_update")
            or kwargs.get("update_fields") is not None
        ):
            raise ValidationError("Payments must be inserted as complete new records.")
        try:
            self.student = Student.objects.select_for_update().get(pk=self.student_id)
        except Student.DoesNotExist:
            raise ValidationError("Student not found.", code="NOT_FOUND") from None
        self.full_clean(exclude=["receipt_no"])
        if self.adjustment_of_id:
            original = Payment.objects.select_for_update().get(pk=self.adjustment_of_id)
            if original.student_id != self.student_id or original.adjustment_of_id:
                raise ValidationError(
                    "Adjust the original payment for the same student, not another adjustment."
                )
            if self.date < original.date:
                raise ValidationError(
                    {"date": "An adjustment cannot predate its original payment."}
                )
            adjusted = original.adjustments.aggregate(total=Sum("amount"))[
                "total"
            ] or Decimal("0")
            if original.amount + adjusted + self.amount < 0:
                raise ValidationError(
                    {
                        "amount": "Adjustments cannot reverse more than the recorded amount."
                    }
                )
        try:
            sequence = ReceiptSequence.objects.select_for_update().get(pk=1)
        except ReceiptSequence.DoesNotExist:
            raise ValidationError(
                "Receipt numbering is not initialized. Apply the payment migration."
            ) from None
        if sequence.last_value >= 99999999999:
            raise ValidationError("The receipt number range is exhausted.")
        sequence.last_value += 1
        sequence.save(update_fields=["last_value"])
        self.receipt_no = f"R{sequence.last_value:011d}"
        kwargs["force_insert"] = True
        return super().save(**kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Payments cannot be deleted. Record a new adjusting entry.",
            code="IMMUTABLE_FIELD",
        )
