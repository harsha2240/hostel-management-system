import csv

from django.core.exceptions import ValidationError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET

from hms.decorators import staff_required
from hms.http import wants_json
from hms.responses import validation_response
from hostels.models import Hostel

from .services import occupancy_rows, payment_status_rows

OCCUPANCY_COLUMNS = (
    ("Hostel Name", "hostel"),
    ("Total Beds", "total_beds"),
    ("Occupied Beds", "occupied_beds"),
    ("Available Beds", "available_beds"),
    ("Beds Under Maintenance", "maintenance_beds"),
    ("Occupancy %", "occupancy_percent"),
)
PAYMENT_COLUMNS = (
    ("Student ID", "student_id"),
    ("Student Name", "student_name"),
    ("Hostel Name", "hostel"),
    ("Room", "room"),
    ("Fee Amount (INR)", "fee"),
    ("Amount Paid (INR)", "paid"),
    ("Due (INR)", "due"),
    ("Payment Status", "status"),
)


def csv_cell(value):
    """Keep user-provided text literal when opened in a spreadsheet."""
    if isinstance(value, str) and (
        value.lstrip().startswith(("=", "+", "-", "@"))
        or value.startswith(("\t", "\r", "\n"))
    ):
        return "'" + value
    return value


def report_response(request, kind):
    try:
        selected = request.GET.get("hostel", "").strip()
        if selected:
            # Strip leading zeros before bounding the integer conversion. Python
            # rejects extremely long digit strings before the range check can run.
            selected = selected.lstrip("0")
            if (
                not selected.isascii()
                or not selected.isdigit()
                or len(selected) > 19
                or not 0 < int(selected) <= 2**63 - 1
            ):
                raise ValidationError("Choose a valid hostel ID.")
            selected = get_object_or_404(Hostel, pk=int(selected)).pk
        else:
            selected = None
        output = request.GET.get("format") or (
            "json" if wants_json(request) else "html"
        )
        if output not in {"html", "json", "csv"}:
            raise ValidationError("Choose html, json or csv as the report format.")
    except ValidationError as error:
        return validation_response(error)
    occupancy = kind == "occupancy"
    rows = occupancy_rows(selected) if occupancy else payment_status_rows(selected)
    generated_on = timezone.localtime()
    if output == "json":
        return JsonResponse({"rows": rows, "generated_on": generated_on.isoformat()})
    if output == "csv":
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{kind}.csv"'
        response.write("\ufeff")
        columns = OCCUPANCY_COLUMNS if occupancy else PAYMENT_COLUMNS
        writer = csv.writer(response)
        writer.writerow([heading for heading, _ in columns] + ["Generated On"])
        generated_label = generated_on.strftime("%d-%m-%Y %H:%M:%S IST")
        for row in rows:
            writer.writerow(
                [csv_cell(row[key]) for _, key in columns] + [generated_label]
            )
        return response
    return render(
        request,
        "reports/report.html",
        {
            "rows": rows,
            "occupancy": occupancy,
            "hostels": Hostel.objects.all(),
            "selected_hostel": selected,
            "generated_on": generated_on,
        },
    )


@staff_required
@require_GET
def occupancy_report(request):
    return report_response(request, "occupancy")


@staff_required
@require_GET
def payment_status_report(request):
    return report_response(request, "payment-status")
