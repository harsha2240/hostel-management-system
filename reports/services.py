from decimal import Decimal

from django.db.models import Count, Exists, OuterRef, Q

from allocations.models import Allocation
from hostels.models import Bed, Hostel
from payments.services import payment_status_queryset, status_row


def occupancy_rows(hostel_id=None):
    hostels = Hostel.objects.all()
    beds = Bed.objects.all()
    if hostel_id is not None:
        hostels = hostels.filter(pk=hostel_id)
        beds = beds.filter(room__hostel_id=hostel_id)
    active = Allocation.objects.filter(
        bed_id=OuterRef("pk"), status=Allocation.AllocationStatus.ACTIVE
    )
    counts = (
        beds.annotate(has_active=Exists(active))
        .order_by()
        .values("room__hostel_id")
        .annotate(
            total=Count("pk"),
            occupied=Count(
                "pk", filter=Q(has_active=True) | Q(status=Bed.BedStatus.OCCUPIED)
            ),
            available=Count(
                "pk", filter=Q(has_active=False, status=Bed.BedStatus.AVAILABLE)
            ),
            maintenance=Count(
                "pk", filter=Q(has_active=False, status=Bed.BedStatus.MAINTENANCE)
            ),
        )
    )
    by_hostel = {row["room__hostel_id"]: row for row in counts}
    rows = []
    for hostel in hostels:
        count = by_hostel.get(hostel.pk, {})
        total, occupied = count.get("total", 0), count.get("occupied", 0)
        percent = Decimal(occupied * 100) / Decimal(total) if total else Decimal(0)
        rows.append(
            {
                "hostel_id": hostel.pk,
                "hostel": hostel.name,
                "total_beds": total,
                "occupied_beds": occupied,
                "available_beds": count.get("available", 0),
                "maintenance_beds": count.get("maintenance", 0),
                "occupancy_percent": f"{percent:.2f}",
            }
        )
    return rows


def payment_status_rows(hostel_id=None):
    students = payment_status_queryset().order_by("student_id")
    if hostel_id is not None:
        students = students.filter(billing_hostel_id=hostel_id)
    return [status_row(student) for student in students]
