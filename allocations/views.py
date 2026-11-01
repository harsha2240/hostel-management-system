from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from hms.decorators import staff_required as staff_only
from hms.http import api_error, request_data, wants_json
from hms.responses import validation_response
from hostels.models import Bed
from students.models import Student

from .forms import AllocationForm, ReleaseForm, TransferForm
from .models import Allocation
from .services import allocate, release, transfer


def serialize(allocation):
    return {
        "allocation_id": allocation.pk,
        "student_id": allocation.student.student_id,
        "bed_id": allocation.bed_id,
        "bed": allocation.bed.label,
        "hostel": allocation.bed.room.hostel.name,
        "status": allocation.status,
        "allocated_on": allocation.allocated_on.isoformat(),
        "vacated_on": allocation.vacated_on.isoformat()
        if allocation.vacated_on
        else None,
    }


def form_error(request, form, error=None):
    if error is not None:
        if wants_json(request):
            return validation_response(error)
        form.add_error(None, "; ".join(error.messages))
    if wants_json(request):
        missing = any(
            error.code == "invalid_choice"
            for errors in form.errors.as_data().values()
            for error in errors
        )
        return api_error(
            "Please correct the highlighted fields.",
            fields=form.errors.get_json_data(),
            code="NOT_FOUND" if missing else "VALIDATION_ERROR",
            status=404 if missing else 400,
        )
    return None


def available_beds():
    return (
        Bed.objects.select_related("room__hostel")
        .filter(status=Bed.BedStatus.AVAILABLE, room__hostel__is_active=True)
        .exclude(allocations__status=Allocation.AllocationStatus.ACTIVE)
    )


@staff_only
@require_http_methods(["GET", "POST"])
def allocation_list(request):
    if request.method == "POST":
        return allocation_create(request)
    query = request.GET.get("q", "").strip()
    allocations = Allocation.objects.select_related("student", "bed__room__hostel")
    if query:
        allocations = allocations.filter(
            Q(student__student_id__icontains=query)
            | Q(student__name__icontains=query)
            | Q(bed__label__icontains=query)
            | Q(bed__room__hostel__name__icontains=query)
        )
    page = Paginator(allocations, 25).get_page(request.GET.get("page"))
    if wants_json(request):
        return JsonResponse(
            {
                "results": [serialize(a) for a in page],
                "page": page.number,
                "total": page.paginator.count,
            }
        )
    return render(
        request,
        "allocations/allocation_list.html",
        {"allocations": page, "page_obj": page, "query": query},
    )


@staff_only
@require_http_methods(["GET", "POST"])
def allocation_create(request):
    form = AllocationForm()
    if request.method == "POST":
        try:
            data = request_data(request)
            if request.content_type == "application/json":
                data = dict(data)
                identifier = data.pop("student_id", None)
                student = (
                    Student.objects.filter(student_id=identifier).first()
                    if isinstance(identifier, str)
                    else None
                )
                if student is None:
                    return api_error("Student not found.", code="NOT_FOUND", status=404)
                data["student"] = student.pk
                data["bed"] = data.pop("bed_id", None)
            form = AllocationForm(data)
            if form.is_valid():
                allocation = allocate(actor=request.user, **form.cleaned_data)
                if wants_json(request):
                    return JsonResponse(serialize(allocation), status=201)
                messages.success(
                    request,
                    f"Bed {allocation.bed.label} allocated to {allocation.student.name}.",
                )
                return redirect("allocation-list")
            response = form_error(request, form)
        except ValidationError as error:
            response = form_error(request, form, error)
        if response is not None:
            return response
    else:
        form.fields["student"].queryset = Student.objects.filter(
            status=Student.Status.ACTIVE
        ).exclude(allocations__status=Allocation.AllocationStatus.ACTIVE)
        form.fields["bed"].queryset = available_beds()
    return render(
        request,
        "allocations/allocation_form.html",
        {"form": form, "heading": "Create Hostel Allocation"},
    )


@staff_only
@require_http_methods(["GET", "POST"])
def allocation_transfer(request, pk):
    allocation = get_object_or_404(
        Allocation.objects.select_related("student", "bed"), pk=pk
    )
    form = TransferForm()
    if request.method == "POST":
        try:
            data = request_data(request)
            if request.content_type == "application/json":
                data = {"new_bed": data.get("new_bed_id")}
            form = TransferForm(data)
            if form.is_valid():
                successor = transfer(
                    allocation_id=allocation.pk, actor=request.user, **form.cleaned_data
                )
                if wants_json(request):
                    return JsonResponse(serialize(successor))
                messages.success(
                    request, "Transfer completed; allocation history is preserved."
                )
                return redirect("allocation-list")
            response = form_error(request, form)
        except ValidationError as error:
            response = form_error(request, form, error)
        if response is not None:
            return response
    else:
        form.fields["new_bed"].queryset = available_beds().exclude(pk=allocation.bed_id)
    return render(
        request,
        "allocations/allocation_form.html",
        {"form": form, "heading": "Transfer Allocation", "allocation": allocation},
    )


@staff_only
@require_http_methods(["GET", "POST"])
def allocation_release(request, pk):
    allocation = get_object_or_404(
        Allocation.objects.select_related("student", "bed"), pk=pk
    )
    form = ReleaseForm()
    if request.method == "POST":
        try:
            data = request_data(request)
            if request.resolver_match.url_name == "allocation-complete" and not data:
                data = {"vacate_date": timezone.localdate()}
            form = ReleaseForm(data)
            if form.is_valid():
                completed = release(
                    allocation_id=allocation.pk, actor=request.user, **form.cleaned_data
                )
                if wants_json(request):
                    payload = serialize(completed)
                    payload["status"] = "Released"
                    return JsonResponse(payload)
                messages.success(request, "Allocation released.")
                return redirect("allocation-list")
            response = form_error(request, form)
        except ValidationError as error:
            response = form_error(request, form, error)
        if response is not None:
            return response
    return render(
        request,
        "allocations/allocation_form.html",
        {"form": form, "heading": "Release Allocation", "allocation": allocation},
    )


@staff_only
@require_http_methods(["GET"])
def allocation_history(request, pk):
    student = get_object_or_404(Student, pk=pk)
    allocations = student.allocations.select_related("student", "bed__room__hostel")
    if wants_json(request):
        return JsonResponse(
            {
                "student_id": student.student_id,
                "allocations": [serialize(a) for a in allocations],
            }
        )
    return render(
        request,
        "allocations/allocation_list.html",
        {"allocations": allocations, "student": student},
    )


@staff_only
@require_POST
def allocation_complete(request, pk):
    return allocation_release(request, pk)
