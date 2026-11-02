"""Explicit JMeter execution; invoke only through run_issue40_load.py.

No application database is seeded. All users and records are synthetic and
exist only in Django's disposable test_hms. Raw evidence is private/ignored;
only sanitized result summaries are suitable for review/publication.
"""

import csv
import hashlib
import json
import math
import os
import platform
import secrets
import subprocess
import tempfile
import zipfile
from collections import Counter
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit

from django import get_version
from django.contrib.auth.hashers import make_password
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.db import connection
from django.test import override_settings

from accounts.models import User
from hostels.models import Bed, Hostel, Room
from students.models import Student

THREADS = 50
HTTP_LABELS = ("setup_login_form", "load_login", "load_search", "load_beds")


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metrics(rows):
    values = sorted(int(row["elapsed"]) for row in rows)
    errors = sum(row["success"].lower() != "true" for row in rows)
    within = sum(value <= 2000 for value in values)
    span = (
        max(int(row["timeStamp"]) + int(row["elapsed"]) for row in rows)
        - min(int(row["timeStamp"]) for row in rows)
        if rows
        else 0
    )
    return {
        "count": len(rows),
        "errors": errors,
        "within_2000_ms": within,
        "fraction_within_2000_ms": within / len(rows) if rows else 0,
        "min_ms": values[0] if values else None,
        "p50_ms": values[math.ceil(0.50 * len(values)) - 1] if values else None,
        "p95_ms": values[math.ceil(0.95 * len(values)) - 1] if values else None,
        "max_ms": values[-1] if values else None,
        "observed_requests_per_second": len(rows) * 1000 / span if span else 0,
    }


def summarize(jtl, seconds, returncode, *, volume=False):
    with jtl.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    http = [row for row in rows if row["label"] in HTTP_LABELS]
    starts = [row for row in rows if row["label"] == "measurement_start"]
    ends = [row for row in rows if row["label"] == "measurement_end"]
    names = {row["threadName"] for row in starts}
    start_times = {
        int(row["phase_started_ms"]) for row in starts if row["phase_started_ms"]
    }
    durations = [
        int(row["phase_elapsed_ms"]) for row in ends if row["phase_elapsed_ms"]
    ]
    end_names = Counter(row["threadName"] for row in ends)
    all_errors = sum(row["success"].lower() != "true" for row in rows)
    counts_by_thread = {
        label: dict(Counter(row["threadName"] for row in http if row["label"] == label))
        for label in HTTP_LABELS
    }
    participation = (
        len(starts) == len(ends) == len(names) == THREADS
        and set(end_names) == names
        and all(value == 1 for value in end_names.values())
        and len(start_times) == 1
        and len(durations) == THREADS
        and min(durations) >= seconds * 1000
        and all(set(counts_by_thread[label]) == names for label in HTTP_LABELS)
        and all(count == 1 for count in counts_by_thread["load_login"].values())
        and all(count == 1 for count in counts_by_thread["setup_login_form"].values())
        and max((int(row["allThreads"]) for row in rows), default=0) == THREADS
    )
    overall = metrics(http)
    search = metrics([row for row in http if row["label"] == "load_search"])
    volume_search_passed = bool(search["count"] and search["max_ms"] <= 2000)
    measured = [row for row in http if row["label"] != "setup_login_form"]
    passed = (
        returncode == 0
        and participation
        and all_errors == 0
        and overall["count"] > 0
        and overall["fraction_within_2000_ms"] >= 0.95
        and (not volume or volume_search_passed)
    )
    failures = Counter(
        (row["label"], row["responseCode"], row.get("failureMessage", ""))
        for row in rows
        if row["success"].lower() != "true"
    )
    return {
        "criterion": "At least 95% of ALL HTTP sampler transactions (including login form/login and followed redirects) within 2000 ms; zero HTTP/content/controller errors; 50 users each measured for the full requested interval.",
        "status": ("PASS" if passed else "FAIL")
        if seconds >= 600
        else "SMOKE_NOT_ACCEPTANCE",
        "smoke_checks_passed": passed if seconds < 600 else None,
        "requested_seconds": seconds,
        "required_acceptance_seconds": 600,
        "volume_search_additional_criterion": "Every volume search HTTP sampler completes within 2000 ms"
        if volume
        else None,
        "volume_search_within_2000_ms": volume_search_passed if volume else None,
        "all_http": overall,
        "measured_http_including_login": metrics(measured),
        "per_route": {
            label: metrics([row for row in http if row["label"] == label])
            for label in HTTP_LABELS
        },
        "all_sample_errors_including_controllers": all_errors,
        "participation": {
            "valid": participation,
            "configured_threads": THREADS,
            "start_markers": len(starts),
            "end_markers": len(ends),
            "unique_started_threads": len(names),
            "unique_finished_threads": len(end_names),
            "maximum_observed_threads": max(
                (int(row["allThreads"]) for row in rows), default=0
            ),
            "common_barrier_start_ms": sorted(start_times),
            "minimum_thread_measured_ms": min(durations) if durations else None,
            "maximum_thread_measured_ms": max(durations) if durations else None,
            "per_thread_measured_ms": {
                row["threadName"]: int(row["phase_elapsed_ms"] or 0) for row in ends
            },
            "per_route_per_thread_samples": counts_by_thread,
        },
        "failures": [
            {
                "label": label,
                "response_code": code,
                "assertion": assertion,
                "count": count,
            }
            for (label, code, assertion), count in failures.items()
        ],
        "jmeter_exit_code": returncode,
        "measurement_notes": [
            "No samples or failures are removed from overall acceptance metrics.",
            "GET login form is measured before the 50-user barrier; login POST is measured inside the full load interval.",
            "A one-second think time precedes every measured HTTP sampler, including login; this pacing is excluded from HTTP response latency and included in elapsed load duration.",
            "Each login follows its redirect and asserts the authenticated Warden dashboard; search and bed assertions require authenticated navigation plus real fixture table rows.",
            "HTTP latency includes complete followed redirects; no response/request bodies or headers are stored in CSV.",
            "Acceptance status describes this candidate build only; team case review and build acceptance remain separate.",
        ],
    }


@override_settings(
    ALLOWED_HOSTS=["localhost", "127.0.0.1", "testserver"],
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
)
class Issue40LoadExecution(StaticLiveServerTestCase):
    def test_baseline_and_volume_jmeter(self):
        self.assertEqual(connection.vendor, "mysql")
        self.assertEqual(connection.settings_dict["NAME"], "test_hms")
        self.assertFalse(connection.in_atomic_block)
        config = json.loads(os.environ["HMS_ISSUE40_LOAD_CONFIG"])
        output = Path(config["output"])
        password = secrets.token_urlsafe(32)
        encoded = make_password(password)
        User.objects.bulk_create(
            [
                User(
                    username=f"issue40-load-{index}",
                    password=encoded,
                    role=User.Role.WARDEN,
                )
                for index in range(1, THREADS + 1)
            ]
        )
        hostel = Hostel.objects.create(
            name="Issue40 Synthetic Boys", hostel_type="Boys"
        )
        scenarios = (
            ["baseline", "volume"]
            if config["scenario"] == "both"
            else [config["scenario"]]
        )
        summary = {
            "scenarios": [],
            "scope": "TC-PERF-01 and TC-PERF-03 only; candidate-build execution",
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
        summary["harness_sha256"] = {
            name: file_hash(Path(__file__).with_name(name))
            for name in (
                "run_issue40_load.py",
                "test_issue40_load.py",
                "issue40_load.jmx",
            )
        }
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            mysql_version = cursor.fetchone()[0]
        with zipfile.ZipFile(config["jmeter_jar"]) as archive:
            manifest = archive.read("META-INF/MANIFEST.MF").decode("utf-8")
        summary["environment"] = {
            "python": platform.python_version(),
            "django": get_version(),
            "mysql": mysql_version,
            "java": subprocess.run(
                [config["java"], "-version"], check=True, capture_output=True, text=True
            ).stderr.strip(),
            "jmeter_manifest_version": [
                line for line in manifest.splitlines() if "Version:" in line
            ],
            "server": "Threaded Django StaticLiveServerTestCase over loopback HTTP; disposable MySQL test_hms; normal password hasher and audit/session writes",
            "security_overrides": "Loopback HTTP only; secure redirect/session/CSRF cookie flags disabled for this local harness",
            "think_time_ms_per_measured_request": 1000,
            "ramp_seconds": 5,
        }
        for scenario in scenarios:
            students, beds = (100, 80) if scenario == "baseline" else (5000, 2000)
            self.seed_fixture(hostel, students, beds)
            actual = {
                "students": Student.objects.count(),
                "beds": Bed.objects.count(),
                "rooms": Room.objects.count(),
                "users": User.objects.count(),
            }
            self.assertEqual(
                actual,
                {
                    "students": students,
                    "beds": beds,
                    "rooms": beds // 2,
                    "users": THREADS,
                },
            )
            destination = output / scenario
            destination.mkdir()
            parts = urlsplit(self.live_server_url)
            properties = {
                "hms.host": parts.hostname,
                "hms.port": str(parts.port),
                "hms.password": password,
                "hms.seconds": str(config["seconds"]),
                "hms.srn": "HMSP300000000",
                "hms.hostel_id": str(hostel.pk),
                "hms.hostel_name": hostel.name,
                "hms.bed_label": "R0000-A",
                "sample_variables": "phase_started_ms,phase_elapsed_ms",
                "jmeter.save.saveservice.output_format": "csv",
                "jmeter.save.saveservice.timestamp_format": "ms",
                "jmeter.save.saveservice.print_field_names": "true",
                "jmeter.save.saveservice.assertion_results_failure_message": "true",
                "jmeter.save.saveservice.thread_counts": "true",
                "jmeter.save.saveservice.response_data": "false",
                "jmeter.save.saveservice.samplerData": "false",
                "jmeter.save.saveservice.requestHeaders": "false",
                "jmeter.save.saveservice.responseHeaders": "false",
                "jmeter.save.saveservice.subresults": "false",
                "jmeter.save.saveservice.url": "false",
            }
            started = datetime.now(UTC)
            jtl = destination / "samples.csv"
            log = destination / "jmeter.log"
            console = destination / "console.log"
            failure = None
            returncode = -1
            with tempfile.TemporaryDirectory(prefix="hms-issue40-private-") as private:
                transient = Path(private) / "load.properties"
                transient.write_text(
                    "".join(f"{key}={value}\n" for key, value in properties.items()),
                    encoding="ascii",
                )
                command = [
                    config["java"],
                    "-jar",
                    config["jmeter_jar"],
                    "-n",
                    "-t",
                    str(Path(__file__).with_name("issue40_load.jmx")),
                    "-q",
                    str(transient),
                    "-l",
                    str(jtl),
                    "-j",
                    str(log),
                ]
                try:
                    with console.open("w", encoding="utf-8") as stream:
                        result = subprocess.run(
                            command,
                            stdout=stream,
                            stderr=subprocess.STDOUT,
                            timeout=config["seconds"] + 300,
                            check=False,
                        )
                    returncode = result.returncode
                except subprocess.TimeoutExpired:
                    failure = "JMeter exceeded requested duration plus 300 seconds; terminated. Raw evidence retained."
            try:
                result_summary = summarize(
                    jtl, config["seconds"], returncode, volume=scenario == "volume"
                )
            except (OSError, ValueError, KeyError) as error:
                result_summary = {
                    "status": "FAIL",
                    "evidence_parse_failure": type(error).__name__,
                    "jmeter_exit_code": returncode,
                }
            result_summary.update(
                {
                    "scenario": scenario,
                    "case_id": "TC-PERF-01" if scenario == "baseline" else "TC-PERF-03",
                    "started_at": started.isoformat(),
                    "completed_at": datetime.now(UTC).isoformat(),
                    "fixture_counts": actual,
                    "fixture_recipe": "Deterministic HMSP3 + 8-digit SRNs; synthetic example.test contacts; Double rooms of capacity two with exactly two Available beds; 50 distinct Warden accounts with normal hashed random password",
                    "raw_evidence_sha256": {
                        path.name: file_hash(path)
                        for path in (jtl, log, console)
                        if path.exists()
                    },
                    "execution_failure": failure,
                }
            )
            summary["scenarios"].append(result_summary)
            (output / "load-results.json").write_text(
                json.dumps(summary, indent=2) + "\n", encoding="utf-8"
            )
            print(
                f"Issue #40 {scenario}: {result_summary['status']}; evidence retained in ignored output."
            )
        for result_summary in summary["scenarios"]:
            self.assertIsNone(result_summary["execution_failure"])
            self.assertTrue(
                result_summary["status"] == "PASS"
                or (
                    result_summary["status"] == "SMOKE_NOT_ACCEPTANCE"
                    and result_summary["smoke_checks_passed"]
                ),
                "Load criteria failed; inspect load-results.json and retained raw evidence.",
            )

    def seed_fixture(self, hostel, student_count, bed_count):
        Student.objects.bulk_create(
            [
                Student(
                    student_id=f"HMSP3{index:08d}",
                    name=f"Issue40 Load Student {index:05d}",
                    date_of_birth=date(2005, 1, 2),
                    gender="Male",
                    course="CSE",
                    year=2,
                    mobile=f"900{index:07d}",
                    email=f"student{index}@example.test",
                    guardian_name="Synthetic Guardian",
                    guardian_mobile=f"800{index:07d}",
                )
                for index in range(Student.objects.count(), student_count)
            ],
            batch_size=500,
        )
        first_new_room = Room.objects.count()
        Room.objects.bulk_create(
            [
                Room(
                    hostel=hostel,
                    room_number=f"R{index:04d}",
                    floor=index // 100,
                    room_type="Double",
                    capacity=2,
                    fee_amount=Decimal("10000.00"),
                )
                for index in range(first_new_room, bed_count // 2)
            ],
            batch_size=500,
        )
        rooms = Room.objects.filter(room_number__gte=f"R{first_new_room:04d}")
        Bed.objects.bulk_create(
            [
                Bed(room=room, label=f"{room.room_number}-{suffix}", status="Available")
                for room in rooms
                for suffix in ("A", "B")
            ],
            batch_size=500,
        )
