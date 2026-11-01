
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from accounts.decorators import roles_required
from accounts.models import User
from allocations.models import Allocation
from audit.models import AuditEvent
from audit.services import record_event
from payments.models import Payment
from payments.services import payment_status_queryset, status_row

from .forms import StudentForm
from .models import Student


def can_manage_students(user):
    return user.is_authenticated and user.role in (
        User.Role.ADMIN,
        User.Role.WARDEN,
    )


@login_required
def student_list(request):
    if not can_manage_students(request.user):
        return HttpResponseForbidden(
            "You do not have permission to manage students."
        )

    query = request.GET.get("q", "").strip()
    students = Student.objects.all()

    if query:
        students = students.filter(
            Q(student_id__icontains=query)
            | Q(name__icontains=query)
            | Q(
                allocations__status=Allocation.AllocationStatus.ACTIVE,
                allocations__bed__room__hostel__name__icontains=query,
            )
        ).distinct()

    paginator = Paginator(students, 20)
    page_obj = paginator.get_page(request.GET.get("page"))

    return render(
        request,
        "students/student_list.html",
        {"page_obj": page_obj, "query": query},
    )


@login_required
@require_http_methods(["GET", "POST"])
def student_create(request):
    if not can_manage_students(request.user):
        return HttpResponseForbidden(
            "You do not have permission to register students."
        )

    form = StudentForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            student = form.save()
            record_event(
                user=request.user,
                action=AuditEvent.Action.CREATE,
                record=student,
            )
        messages.success(
            request,
            f"Student {student.student_id} registered successfully.",
        )
        return redirect("student-list")

    return render(
        request,
        "students/student_form.html",
        {"form": form, "heading": "Register Student"},
    )


@login_required
@require_http_methods(["GET", "POST"])
def student_update(request, pk):
    if not can_manage_students(request.user):
        return HttpResponseForbidden(
            "You do not have permission to update students."
        )

    student = get_object_or_404(Student, pk=pk)
    form = StudentForm(request.POST or None, instance=student)

    form.fields["student_id"].disabled = True
    form.fields.pop("status")

    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            student = form.save()
            record_event(
                user=request.user,
                action=AuditEvent.Action.UPDATE,
                record=student,
            )
        messages.success(
            request,
            f"Student {student.student_id} updated successfully.",
        )
        return redirect("student-list")

    return render(
        request,
        "students/student_form.html",
        {
            "form": form,
            "heading": "Update Student",
            "student": student,
        },
    )


@login_required
@require_http_methods(["POST"])
@transaction.atomic
def student_deactivate(request, pk):
    if not can_manage_students(request.user):
        return HttpResponseForbidden(
            "You do not have permission to deactivate students."
        )

    student = get_object_or_404(
        Student.objects.select_for_update(),
        pk=pk,
    )

    allocation = (
        Allocation.objects.select_related(
            "bed",
            "bed__room",
            "bed__room__hostel",
        )
        .filter(
            student=student,
            status=Allocation.AllocationStatus.ACTIVE,
        )
        .first()
    )

    if allocation:
        messages.error(
            request,
            f"Cannot deactivate {student.student_id}: "
            f"active bed {allocation.bed.label} in "
            f"{allocation.bed.room.hostel.name} is allocated to this student. "
            "Complete the allocation first.",
        )
        return redirect("student-list")

    if student.status == Student.Status.INACTIVE:
        messages.info(request, "This student is already inactive.")
    else:
        student.status = Student.Status.INACTIVE
        student.save(update_fields=["status", "updated_at"])
        record_event(
            user=request.user,
            action=AuditEvent.Action.DEACTIVATE,
            record=student,
        )
        messages.success(
            request,
            f"Student {student.student_id} deactivated successfully.",
        )

    return redirect("student-list")


@roles_required(User.Role.STUDENT)
@require_GET
def my_records(request):
    """Show only the student profile explicitly linked to this login."""
    student = (
        Student.objects.filter(user_id=request.user.pk)
        .select_related("user")
        .first()
    )
    if student is None:
        return render(request, "students/my_records.html", {"student": None})

    allocations = (
        student.allocations.exclude(status=Allocation.AllocationStatus.CANCELLED)
        .select_related("bed__room__hostel")
        .order_by("-allocated_on", "-pk")
    )
    payments = (
        Payment.objects.filter(student_id=student.pk)
        .select_related("adjustment_of")
        .order_by("-date", "-pk")
    )
    balance_student = payment_status_queryset(
        Student.objects.filter(pk=student.pk)
    ).get(pk=student.pk)
    return render(
        request,
        "students/my_records.html",
        {
            "student": student,
            "allocations": allocations,
            "current_allocation": allocations.filter(
                status=Allocation.AllocationStatus.ACTIVE
            ).first(),
            "payments": payments,
            "payment_summary": status_row(balance_student),
        },
    )
