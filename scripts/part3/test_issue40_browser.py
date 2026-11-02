"""Explicit browser/HTTP case execution on Django's disposable MySQL test database.

Run only through run_issue40_browser.py. This is candidate-build evidence for
issue #40, not final team acceptance or the Unit/System/Coverage reports.
"""

import base64
import csv
import hashlib
import json
import os
import platform
import secrets
import subprocess
from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal
from io import BytesIO, StringIO
from pathlib import Path

from django import get_version
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connection
from django.test import override_settings
from django.utils import timezone
from pypdf import PdfReader

from accounts.models import User
from allocations.models import Allocation
from allocations.services import allocate
from audit.models import AuditEvent
from hostels.models import Bed, Hostel
from payments.models import Payment, ReceiptSequence
from payments.services import payment_status_queryset, status_row
from tests.factories import make_room, make_student


@override_settings(
    ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"],
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class Issue40BrowserExecution(StaticLiveServerTestCase):
    def test_candidate_functional_cases_and_committed_allocation_timing(self):
        started_at = datetime.now(UTC)
        self.assertEqual(connection.vendor, "mysql")
        self.assertEqual(connection.settings_dict["NAME"], "test_hms")
        self.assertFalse(connection.in_atomic_block)
        today = timezone.localdate()
        password = secrets.token_urlsafe(24)
        actor = User.objects.create_user(
            username="issue40-warden", password=password, role=User.Role.WARDEN
        )
        login = User.objects.create_user(
            username="issue40-student", password=password, role=User.Role.STUDENT
        )
        own = make_student(101, name="Issue40 Student", user=login)
        other = make_student(102)
        female = make_student(103, gender="Female")
        resident = make_student(104)
        hostel = Hostel.objects.create(name="Issue40 Boys", hostel_type="Boys")
        old_room = make_room(
            "I401", hostel=hostel, capacity=3, fee_amount=Decimal("10000.00")
        )
        target_room = make_room(
            "I402", hostel=hostel, capacity=2, fee_amount=Decimal("10000.00")
        )
        old_bed, _unused_bed, occupied_bed = list(old_room.beds.all())
        target_bed, maintenance_bed = list(target_room.beds.all())
        maintenance_bed.status = Bed.BedStatus.MAINTENANCE
        maintenance_bed.save(update_fields=["status"])
        allocate(student=resident, bed=occupied_bed, actor=actor)
        ReceiptSequence.objects.get_or_create(pk=1)
        timing_hostel = Hostel.objects.create(
            name="Issue40 Timing Boys", hostel_type="Boys"
        )
        timed = []
        for index in range(20):
            student = make_student(200 + index)
            room = make_room(
                f"T{index:03}", hostel=timing_hostel, capacity=1, room_type="Single"
            )
            timed.append(
                {"student_id": student.student_id, "bed_id": room.beds.get().pk}
            )
        conflict_students = [make_student(300 + index) for index in range(2)]
        conflict_bed = make_room(
            "CONFLICT", hostel=timing_hostel, capacity=1, room_type="Single"
        ).beds.get()
        config = {
            "base_url": self.live_server_url,
            "password": password,
            "warden": actor.username,
            "student_login": login.username,
            "student": {"pk": own.pk, "student_id": own.student_id},
            "other_student_pk": other.pk,
            "female_student_pk": female.pk,
            "old_bed": old_bed.pk,
            "old_bed_label": old_bed.label,
            "target_bed": target_bed.pk,
            "target_bed_label": target_bed.label,
            "hostel_id": hostel.pk,
            "hostel_name": hostel.name,
            "today": today.isoformat(),
            "timed_allocations": timed,
            "conflict_students": [student.student_id for student in conflict_students],
            "conflict_bed": conflict_bed.pk,
        }
        result = subprocess.run(
            ["node", str(Path(__file__).with_name("issue40_browser.cjs"))],
            input=json.dumps(config),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        summary = json.loads(result.stdout)
        self.assertEqual(len(summary["observations"]), 10)
        original_id, successor_id = summary["allocation_ids"]
        history = list(Allocation.objects.filter(student=own))
        self.assertEqual([row.pk for row in history], [successor_id, original_id])
        self.assertTrue(all(row.status == "Completed" for row in history))
        self.assertTrue(all(row.vacated_on == today for row in history))
        self.assertEqual(
            set(
                Bed.objects.filter(pk__in=[old_bed.pk, target_bed.pk]).values_list(
                    "status", flat=True
                )
            ),
            {"Available"},
        )
        self.assertFalse(
            Allocation.objects.filter(student__in=[other, female]).exists()
        )
        self.assertEqual(
            Allocation.objects.filter(bed=conflict_bed, status="Active").count(), 1
        )
        self.assertEqual(Allocation.objects.filter(status="Active").count(), 22)
        self.assertEqual(Payment.objects.count(), 2)
        self.assertEqual(ReceiptSequence.objects.get(pk=1).last_value, 2)
        self.assertEqual(
            list(Payment.objects.order_by("pk").values_list("receipt_no", flat=True)),
            summary["receipts"],
        )
        self.assertEqual(
            sum(Payment.objects.values_list("amount", flat=True)), Decimal("10000.00")
        )
        self.assertEqual(
            set(Payment.objects.values_list("student_id", flat=True)), {own.pk}
        )
        balance = status_row(payment_status_queryset().get(pk=own.pk))
        self.assertEqual(
            (balance["status"], balance["paid"], balance["due"]),
            ("Paid", "10000.00", "0.00"),
        )
        pdf = base64.b64decode(summary.pop("receipt_pdf_base64"), validate=True)
        pdf_text = " ".join(
            page.extract_text() for page in PdfReader(BytesIO(pdf)).pages
        )
        for expected in (
            summary["receipts"][0],
            own.student_id,
            own.name,
            "5000.00",
            "UPI",
            "PART340A",
            today.strftime("%d-%m-%Y"),
        ):
            self.assertIn(expected, pdf_text)
        summary["receipt_pdf"] = {
            "sha256": hashlib.sha256(pdf).hexdigest(),
            "verified_fields": [
                "receipt",
                "student ID",
                "student name",
                "amount",
                "mode",
                "reference",
                "payment date",
            ],
        }
        occupancy = summary["reports"]["occupancy"]
        bed_rows = list(Bed.objects.filter(room__hostel=hostel).values("pk", "status"))
        bed_counts = Counter(row["status"] for row in bed_rows)
        self.assertEqual(len(bed_rows), 5)
        self.assertEqual(bed_counts, {"Occupied": 1, "Available": 3, "Maintenance": 1})
        active_beds = set(
            Allocation.objects.filter(
                bed__room__hostel=hostel, status="Active"
            ).values_list("bed_id", flat=True)
        )
        self.assertEqual(active_beds, {occupied_bed.pk})
        self.assertEqual(
            active_beds, {row["pk"] for row in bed_rows if row["status"] == "Occupied"}
        )
        percentage = Decimal(bed_counts["Occupied"] * 100) / len(bed_rows)
        database_occupancy = [
            hostel.name,
            str(len(bed_rows)),
            str(bed_counts["Occupied"]),
            str(bed_counts["Available"]),
            str(bed_counts["Maintenance"]),
            f"{percentage:.2f}%",
        ]
        self.assertEqual(occupancy["html_rows"], [database_occupancy])
        occupancy_csv = list(
            csv.DictReader(StringIO(occupancy["csv"].lstrip("\ufeff")))
        )
        self.assertEqual(len(occupancy_csv), 1)
        for heading, value in {
            "Hostel Name": hostel.name,
            "Total Beds": "5",
            "Occupied Beds": "1",
            "Available Beds": "3",
            "Beds Under Maintenance": "1",
            "Occupancy %": "20.00",
        }.items():
            self.assertEqual(occupancy_csv[0][heading], value)
        payment_report = summary["reports"]["payment"]
        database_payment_rows = []
        for student in (own, resident):
            allocations = Allocation.objects.filter(student=student)
            current = allocations.filter(status="Active").first()
            latest = current or allocations.order_by("-allocated_on", "-pk").first()
            self.assertIsNotNone(latest)
            self.assertEqual(latest.bed.room.hostel_id, hostel.pk)
            expected_room = target_room if student == own else old_room
            self.assertEqual(latest.bed.room_id, expected_room.pk)
            fee = latest.bed.room.fee_amount
            self.assertEqual(fee, Decimal("10000.00"))
            paid = sum(
                Payment.objects.filter(student=student).values_list(
                    "amount", flat=True
                ),
                Decimal("0.00"),
            )
            self.assertEqual(
                paid, Decimal("10000.00") if student == own else Decimal("0.00")
            )
            due = max(fee - paid, Decimal("0.00"))
            expected_status = "Paid" if student == own else "Pending"
            database_payment_rows.append(
                [
                    student.student_id,
                    student.name,
                    latest.bed.room.hostel.name,
                    latest.bed.room.room_number,
                    f"{fee:.2f}",
                    f"{paid:.2f}",
                    f"{due:.2f}",
                    expected_status,
                ]
            )
        self.assertEqual(payment_report["html_rows"], database_payment_rows)
        self.assertEqual(
            payment_report["html_rows"],
            [
                [
                    own.student_id,
                    own.name,
                    hostel.name,
                    target_room.room_number,
                    "10000.00",
                    "10000.00",
                    "0.00",
                    "Paid",
                ],
                [
                    resident.student_id,
                    resident.name,
                    hostel.name,
                    old_room.room_number,
                    "10000.00",
                    "0.00",
                    "10000.00",
                    "Pending",
                ],
            ],
        )
        payment_csv = list(
            csv.DictReader(StringIO(payment_report["csv"].lstrip("\ufeff")))
        )
        self.assertEqual(len(payment_csv), 2)
        by_student = {row["Student ID"]: row for row in payment_csv}
        for row in payment_report["html_rows"]:
            for heading, value in zip(
                [
                    "Student ID",
                    "Student Name",
                    "Hostel Name",
                    "Room",
                    "Fee Amount (INR)",
                    "Amount Paid (INR)",
                    "Due (INR)",
                    "Payment Status",
                ],
                row,
                strict=True,
            ):
                self.assertEqual(by_student[row[0]][heading], value)
        self.assertEqual(len(summary["allocation_timings"]), 20)
        self.assertTrue(summary["concurrency_client_intervals_overlap"])
        for row in summary["allocation_timings"]:
            record = Allocation.objects.get(pk=row["allocation_id"])
            self.assertEqual(record.student.student_id, row["student_id"])
            self.assertEqual(record.bed_id, row["bed_id"])
            self.assertEqual(record.status, "Active")
        self.assertEqual(
            AuditEvent.objects.filter(user=actor, action="payment").count(), 2
        )
        summary["database_verification"] = {
            "vendor": connection.vendor,
            "database": "test_hms",
            "durable_autocommit": not connection.in_atomic_block,
            "single_conflict_winner": True,
            "receipt_counter": 2,
            "invalid_submissions_unchanged": True,
            "html_csv_and_database_match": True,
        }
        project = Path(__file__).resolve().parents[2]
        summary["source"] = {
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=project, text=True
            ).strip(),
            "git_dirty": bool(
                subprocess.check_output(
                    ["git", "status", "--porcelain"], cwd=project, text=True
                ).strip()
            ),
        }
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            mysql_version = cursor.fetchone()[0]
        summary["environment"] = {
            "python": platform.python_version(),
            "django": get_version(),
            "mysql": mysql_version,
            "started_at": started_at.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
        }
        summary["harness_sha256"] = {
            name: hashlib.sha256(
                Path(__file__).with_name(name).read_bytes()
            ).hexdigest()
            for name in (
                "test_issue40_browser.py",
                "issue40_browser.cjs",
                "run_issue40_browser.py",
            )
        }
        summary["acceptance_status"] = {
            "classification": "candidate checkpoint",
            "case_review": "pending team review",
            "build_acceptance": "pending team acceptance",
            "remaining_owned_cases": ["TC-PERF-01", "TC-PERF-03", "TC-OPS-01"],
            "ALC05_rollback": "requires companion injected-failure regression evidence",
        }
        output = Path(os.environ["HMS_ISSUE40_OUTPUT_DIR"])
        (output / "browser-results.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        print(
            "Issue #40 browser/HTTP evidence saved; nine functional cases plus allocation timing/conflict checks executed."
        )
        self.assertTrue(
            summary["allocation_timings_passed"],
            "An allocation exceeded the under-3-second target; inspect recorded timings.",
        )
