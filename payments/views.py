from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_http_methods

from hms.decorators import staff_required
from hms.http import api_error, request_data, wants_json
from hms.responses import form_error_response, validation_response
from students.models import Student

from .forms import AdjustmentForm, PaymentForm
from .models import Payment
from .receipts import receipt_pdf
from .services import payment_status_queryset, record_payment, status_row


def serialize(payment):
    return {
        "receipt_no": payment.receipt_no,
        "student_id": payment.student.student_id,
        "amount": f"{payment.amount:.2f}",
        "date": payment.date.isoformat(),
        "mode": payment.mode,
        "reference": payment.reference,
        "adjustment_of": payment.adjustment_of.receipt_no
        if payment.adjustment_of_id
        else None,
        "adjustment_reason": payment.adjustment_reason,
    }


@staff_required
@require_http_methods(["GET", "POST"])
def payment_list(request):
    if request.method == "POST":
        return payment_create(request)
    query = request.GET.get("q", "").strip()
    payments = Payment.objects.select_related("student", "adjustment_of")
    if query:
        payments = payments.filter(
            Q(student__student_id__icontains=query)
            | Q(student__name__icontains=query)
            | Q(receipt_no__icontains=query)
        )
    page = Paginator(payments, 25).get_page(request.GET.get("page"))
    if wants_json(request):
        return JsonResponse(
            {
                "results": [serialize(p) for p in page],
                "total": page.paginator.count,
                "page": page.number,
            }
        )
    return render(
        request,
        "payments/payment_list.html",
        {"payments": page, "page_obj": page, "query": query},
    )


def payment_form(request, original=None):
    form_type = AdjustmentForm if original else PaymentForm
    form = form_type()
    if request.method == "POST":
        try:
            data = request_data(request)
            if request.content_type == "application/json" and original is None:
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
            form = form_type(data)
            if form.is_valid():
                values = form.cleaned_data.copy()
                if original:
                    values.update(student=original.student, adjustment_of=original)
                payment = record_payment(actor=request.user, **values)
                if wants_json(request):
                    return JsonResponse(serialize(payment), status=201)
                messages.success(request, f"Receipt {payment.receipt_no} recorded.")
                return redirect("payment-receipt", receipt_no=payment.receipt_no)
            if wants_json(request):
                return form_error_response(form, missing_fields=("student",))
        except ValidationError as error:
            if wants_json(request):
                return validation_response(error)
            form.add_error(None, "; ".join(error.messages))
    return render(
        request, "payments/payment_form.html", {"form": form, "original": original}
    )


@staff_required
@require_http_methods(["GET", "POST"])
def payment_create(request):
    return payment_form(request)


@staff_required
@require_http_methods(["GET", "POST"])
def payment_adjust(request, receipt_no):
    original = get_object_or_404(
        Payment.objects.select_related("student"),
        receipt_no=receipt_no,
        adjustment_of__isnull=True,
    )
    return payment_form(request, original)


def get_receipt(receipt_no):
    return get_object_or_404(
        Payment.objects.select_related("student", "adjustment_of"),
        receipt_no=receipt_no,
    )


@staff_required
@require_GET
def payment_receipt(request, receipt_no):
    payment = get_receipt(receipt_no)
    if wants_json(request):
        return JsonResponse(serialize(payment))
    return render(
        request,
        "payments/receipt.html",
        {"payment": payment, "adjustments": payment.adjustments.all()},
    )


@staff_required
@require_GET
def payment_receipt_pdf(request, receipt_no):
    payment = get_receipt(receipt_no)
    return FileResponse(
        receipt_pdf(payment),
        as_attachment=True,
        filename=f"{payment.receipt_no}.pdf",
        content_type="application/pdf",
    )


@staff_required
@require_GET
def student_payment_status(request, pk):
    student = get_object_or_404(payment_status_queryset(), pk=pk)
    row = status_row(student)
    if wants_json(request):
        return JsonResponse(row)
    return render(request, "payments/status.html", {"row": row, "student": student})
