from decimal import Decimal

from django.db import transaction
from django.db.models import Case, DecimalField, OuterRef, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce

from allocations.models import Allocation
from audit.models import AuditEvent
from audit.services import record_event
from students.models import Student

from .models import Payment


@transaction.atomic
def record_payment(*, actor, **data):
    payment = Payment(**data)
    payment.save()
    record_event(user=actor, action=AuditEvent.Action.PAYMENT, record=payment)
    return payment


def payment_status_queryset(students=None):
    """One query for student balances; independent subqueries avoid join multiplication."""
    students = Student.objects.all() if students is None else students
    latest = (
        Allocation.objects.filter(student_id=OuterRef("pk"))
        .exclude(status=Allocation.AllocationStatus.CANCELLED)
        .annotate(
            priority=Case(When(status=Allocation.AllocationStatus.ACTIVE, then=0), default=1)
        )
        .order_by("priority", "-allocated_on", "-pk")
    )
    totals = (
        Payment.objects.filter(student_id=OuterRef("pk"))
        .order_by()
        .values("student_id")
        .annotate(total=Sum("amount"))
        .values("total")
    )
    money = DecimalField(max_digits=20, decimal_places=2)
    return students.annotate(
        fee_amount=Coalesce(
            Subquery(latest.values("bed__room__fee_amount")[:1]),
            Value(Decimal("0.00")),
            output_field=money,
        ),
        amount_paid=Coalesce(
            Subquery(totals), Value(Decimal("0.00")), output_field=money
        ),
        billing_hostel_id=Subquery(latest.values("bed__room__hostel_id")[:1]),
        billing_hostel=Subquery(latest.values("bed__room__hostel__name")[:1]),
        billing_room=Subquery(latest.values("bed__room__room_number")[:1]),
    )


def status_row(student):
    fee, paid = student.fee_amount, student.amount_paid
    if fee <= 0 or paid <= 0:
        status = "Pending"
    elif paid >= fee:
        status = "Paid"
    else:
        status = "Partial"
    return {
        "student_id": student.student_id,
        "student_name": student.name,
        "hostel_id": student.billing_hostel_id,
        "hostel": student.billing_hostel or "",
        "room": student.billing_room or "",
        "fee": f"{fee:.2f}",
        "paid": f"{paid:.2f}",
        "due": f"{max(fee - paid, Decimal('0')):.2f}",
        "status": status,
        "fee_configured": student.billing_hostel_id is not None and fee > 0,
    }
