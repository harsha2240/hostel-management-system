"""Private read-only HMS backups and guarded recovery evidence for issue #40.

Run database operations only while other Django/MySQL test suites are stopped.
SQL and credentials remain outside the repository. Recovery creates only the
previously absent, disposable test_hms database and never imports into hms.
"""

import argparse
import csv
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASK_NAME = "HMS-Issue40-DailyBackup"
TARGET = "test_hms"
MYSQL_BIN = Path(r"C:\Program Files\MySQL\MySQL Server 8.4\bin")
REQUIRED_TABLES = (
    "students_student",
    "hostels_bed",
    "allocations_allocation",
    "payments_payment",
    "audit_auditevent",
)


class SafetyError(Exception):
    """An operation was refused before it could affect unrelated resources."""


def private_destination(value):
    path = Path(value).resolve()
    if path.is_relative_to(ROOT) or path == Path(path.anchor):
        raise SafetyError(
            "Backup storage must be a private directory outside the repository."
        )
    return path


def validate_source(database):
    if (
        database.get("ENGINE") != "django.db.backends.mysql"
        or database.get("NAME") != "hms"
    ):
        raise SafetyError("Only the documented MySQL hms source is supported.")
    return database


def validate_target(source, target):
    if source != "hms" or target != TARGET or target == source:
        raise SafetyError(
            "Recovery is restricted to a new disposable test_hms database."
        )


def validate_dump_sql(path):
    # Positional mysqldump without --databases must not choose another schema.
    expression = re.compile(rb"^\s*(?:(?:CREATE|DROP)\s+DATABASE\b|USE\s+)", re.I)
    with path.open("rb") as dump:
        for line in dump:
            if expression.match(line):
                raise SafetyError("The dump contains a database-selection statement.")


def source_settings(connection_file=None):
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hms.settings")
    if connection_file is not None:
        connection_file = Path(connection_file).resolve()
        if connection_file.is_relative_to(ROOT):
            raise SafetyError(
                "Private connection files must be outside the repository."
            )
        values = json.loads(connection_file.read_text(encoding="utf-8"))
        if set(values) != {"DB_NAME", "DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT"}:
            raise SafetyError("The private connection file has unexpected keys.")
        if values["DB_NAME"] != "hms" or values["DB_HOST"] != "127.0.0.1":
            raise SafetyError(
                "Private recovery demonstrations require a local hms database."
            )
        if not 1024 <= int(values["DB_PORT"]) <= 65535:
            raise SafetyError("An unprivileged local sandbox port is required.")
        if int(values["DB_PORT"]) == 3306:
            raise SafetyError("The private sandbox must not use the live MySQL port.")
        os.environ.update({key: str(value) for key, value in values.items()})
    import django

    django.setup()
    from django.conf import settings

    return validate_source(settings.DATABASES["default"])


def protect_directory(path):
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        result = subprocess.run(
            ["whoami", "/user", "/fo", "csv", "/nh"],
            capture_output=True,
            text=True,
            check=True,
        )
        identity = next(csv.reader(result.stdout.splitlines()))
        sid = identity[-1]
        if not re.fullmatch(r"S-\d+(?:-\d+)+", sid):
            raise SafetyError("The current Windows identity could not be validated.")
        subprocess.run(
            [
                "icacls",
                str(path),
                "/inheritance:r",
                "/grant:r",
                f"*{sid}:(OI)(CI)F",
                "/grant:r",
                "*S-1-5-18:(OI)(CI)F",
            ],
            check=True,
            capture_output=True,
        )
    else:
        path.chmod(0o700)


@contextmanager
def client_options(database, parent):
    """The password is neither an argument nor a persistent shared file."""
    with tempfile.TemporaryDirectory(prefix="mysql-options-", dir=parent) as folder:
        private = Path(folder)
        protect_directory(private)
        path = private / "client.cnf"

        def quoted(value):
            return (
                '"'
                + str(value)
                .replace("\\", "\\\\")
                .replace('"', '\\"')
                .replace("\n", "\\n")
                .replace("\r", "\\r")
                + '"'
            )

        content = (
            "[client]\n"
            + "\n".join(
                f"{key}={quoted(value)}"
                for key, value in (
                    ("host", database.get("HOST") or "localhost"),
                    ("port", database.get("PORT") or 3306),
                    ("user", database["USER"]),
                    ("password", database["PASSWORD"]),
                    ("default-character-set", "utf8mb4"),
                )
            )
            + "\n"
        )
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as options:
            options.write(content)
        yield path


def connect(database, name="hms"):
    import MySQLdb

    return MySQLdb.connect(
        host=database.get("HOST") or "localhost",
        port=int(database.get("PORT") or 3306),
        user=database["USER"],
        passwd=database["PASSWORD"],
        db=name,
        charset="utf8mb4",
        autocommit=True,
    )


def snapshot(database, name):
    """Hash complete rows and schema without writing or publishing row values."""
    if name not in ("hms", TARGET):
        raise SafetyError("Unexpected snapshot database.")
    connection = connect(database, name)
    try:
        with connection.cursor() as cursor:
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            cursor.execute("SHOW FULL TABLES WHERE Table_type = 'BASE TABLE'")
            tables = sorted(row[0] for row in cursor.fetchall())
            result = {}
            for table in tables:
                if not re.fullmatch(r"[A-Za-z0-9_]+", table):
                    raise SafetyError("An unexpected table identifier was found.")
                cursor.execute(f"SHOW CREATE TABLE `{table}`")
                definition = cursor.fetchone()[1]
                cursor.execute(f"SELECT * FROM `{table}`")
                # Sorting canonical per-row hashes handles tables without a PK.
                rows = sorted(
                    hashlib.sha256(
                        json.dumps(
                            row, default=str, ensure_ascii=True, separators=(",", ":")
                        ).encode()
                    ).hexdigest()
                    for row in cursor.fetchall()
                )
                result[table] = {
                    "rows": len(rows),
                    "rows_sha256": hashlib.sha256("\n".join(rows).encode()).hexdigest(),
                    "schema_sha256": hashlib.sha256(definition.encode()).hexdigest(),
                }
            connection.rollback()
            return result
    finally:
        connection.close()


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


def consistency(database, name):
    """Count logical violations without publishing any row values."""
    if name not in ("hms", TARGET):
        raise SafetyError("Unexpected consistency-check database.")
    queries = {
        "orphan_allocation_student": "SELECT COUNT(*) FROM allocations_allocation a LEFT JOIN students_student s ON s.id=a.student_id WHERE s.id IS NULL",
        "orphan_allocation_bed": "SELECT COUNT(*) FROM allocations_allocation a LEFT JOIN hostels_bed b ON b.id=a.bed_id WHERE b.id IS NULL",
        "orphan_payment_student": "SELECT COUNT(*) FROM payments_payment p LEFT JOIN students_student s ON s.id=p.student_id WHERE s.id IS NULL",
        "orphan_adjustment_original": "SELECT COUNT(*) FROM payments_payment p LEFT JOIN payments_payment o ON o.id=p.adjustment_of_id WHERE p.adjustment_of_id IS NOT NULL AND o.id IS NULL",
        "orphan_bed_room": "SELECT COUNT(*) FROM hostels_bed b LEFT JOIN hostels_room r ON r.id=b.room_id WHERE r.id IS NULL",
        "orphan_room_hostel": "SELECT COUNT(*) FROM hostels_room r LEFT JOIN hostels_hostel h ON h.id=r.hostel_id WHERE h.id IS NULL",
        "orphan_student_user": "SELECT COUNT(*) FROM students_student s LEFT JOIN accounts_user u ON u.id=s.user_id WHERE s.user_id IS NOT NULL AND u.id IS NULL",
        "orphan_audit_actor": "SELECT COUNT(*) FROM audit_auditevent a LEFT JOIN accounts_user u ON u.id=a.user_id WHERE a.user_id IS NOT NULL AND u.id IS NULL",
        "duplicate_active_student": "SELECT COUNT(*) FROM (SELECT student_id FROM allocations_allocation WHERE status='Active' GROUP BY student_id HAVING COUNT(*)>1) v",
        "duplicate_active_bed": "SELECT COUNT(*) FROM (SELECT bed_id FROM allocations_allocation WHERE status='Active' GROUP BY bed_id HAVING COUNT(*)>1) v",
        "active_allocation_bed_not_occupied": "SELECT COUNT(*) FROM allocations_allocation a JOIN hostels_bed b ON b.id=a.bed_id WHERE a.status='Active' AND b.status<>'Occupied'",
        "occupied_bed_without_active_allocation": "SELECT COUNT(*) FROM hostels_bed b LEFT JOIN allocations_allocation a ON a.bed_id=b.id AND a.status='Active' WHERE b.status='Occupied' AND a.id IS NULL",
        "invalid_adjustment_original_student_or_date": "SELECT COUNT(*) FROM payments_payment p JOIN payments_payment o ON o.id=p.adjustment_of_id WHERE o.adjustment_of_id IS NOT NULL OR o.student_id<>p.student_id OR p.date<o.date",
        "over_reversed_payment": "SELECT COUNT(*) FROM (SELECT o.id FROM payments_payment o LEFT JOIN payments_payment a ON a.adjustment_of_id=o.id WHERE o.adjustment_of_id IS NULL GROUP BY o.id,o.amount HAVING o.amount+COALESCE(SUM(a.amount),0)<0) v",
        "invalid_receipt_format": "SELECT COUNT(*) FROM payments_payment WHERE receipt_no NOT REGEXP '^R[0-9]{11}$'",
        "duplicate_receipt": "SELECT COUNT(*) FROM (SELECT receipt_no FROM payments_payment GROUP BY receipt_no HAVING COUNT(*)>1) v",
    }
    connection = connect(database, name)
    try:
        with connection.cursor() as cursor:
            cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT, READ ONLY")
            violations = {}
            for check, query in queries.items():
                cursor.execute(query)
                violations[check] = int(cursor.fetchone()[0])
            cursor.execute(
                "SELECT COUNT(*), COALESCE(MAX(CAST(SUBSTRING(receipt_no,2) AS UNSIGNED)),0), COALESCE(MIN(CAST(SUBSTRING(receipt_no,2) AS UNSIGNED)),0) FROM payments_payment"
            )
            count, maximum, minimum = map(int, cursor.fetchone())
            cursor.execute("SELECT id,`last_value` FROM payments_receiptsequence")
            sequence = cursor.fetchall()
            violations["receipt_sequence_or_gap"] = int(
                len(sequence) != 1
                or sequence[0] != (1, maximum)
                or count != maximum
                or (count > 0 and minimum != 1)
            )
            connection.rollback()
            return {
                "violations": violations,
                "all_consistency_checks_pass": not any(violations.values()),
                "receipt_count": count,
                "last_receipt_value": maximum,
            }
    finally:
        connection.close()


def backup(output, dump_exe, connection_file=None):
    database = source_settings(connection_file)
    output = private_destination(output)
    protect_directory(output)
    started = datetime.now(UTC)
    folder = output / started.strftime("%Y%m%dT%H%M%S%fZ")
    protect_directory(folder)
    dump = folder / "hms.sql"
    before = snapshot(database, "hms")
    with client_options(database, output) as options:
        with dump.open("xb") as stream:
            subprocess.run(
                [
                    str(dump_exe),
                    f"--defaults-extra-file={options}",
                    "--single-transaction",
                    "--quick",
                    "--skip-lock-tables",
                    "--no-tablespaces",
                    "--set-gtid-purged=OFF",
                    "--column-statistics=0",
                    "hms",
                ],
                stdout=stream,
                stderr=subprocess.PIPE,
                check=True,
            )
    validate_dump_sql(dump)
    after = snapshot(database, "hms")
    completed = datetime.now(UTC)
    manifest = {
        "operation": "read-only hms backup",
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "dump_sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
        "dump_bytes": dump.stat().st_size,
        "consistent_snapshot_option": True,
        "source_before": before,
        "source_after": after,
        "source_quiescent_during_backup": before == after,
        "status": "PASS",
    }
    write_json(folder / "manifest.json", manifest)
    write_json(
        output / "latest.json",
        {"backup_directory": folder.name, "completed_at": completed.isoformat()},
    )
    return {
        "operation": "backup",
        "status": "PASS",
        "completed_at": completed.isoformat(),
        "source_quiescent_during_backup": before == after,
        "private_backup_directory": folder.name,
    }


def recover(output, mysql_exe, connection_file=None, evidence_dir=None):
    database = source_settings(connection_file)
    validate_target(database["NAME"], TARGET)
    output = private_destination(output)
    results = output if evidence_dir is None else private_destination(evidence_dir)
    if evidence_dir is not None:
        if results.exists() and any(results.iterdir()):
            raise SafetyError("Choose a new empty recovery evidence directory.")
        protect_directory(results)
    latest = json.loads((output / "latest.json").read_text(encoding="utf-8"))
    folder = (output / latest["backup_directory"]).resolve()
    if folder.parent != output or not folder.is_dir():
        raise SafetyError("The backup pointer leaves its private storage directory.")
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    completed = datetime.fromisoformat(manifest["completed_at"])
    now = datetime.now(UTC)
    age = now - completed
    if age < timedelta() or age > timedelta(hours=24):
        raise SafetyError(
            "Recovery requires a backup completed within the last 24 hours."
        )
    if not manifest["source_quiescent_during_backup"]:
        raise SafetyError(
            "Source changed during backup; repeat the verification backup while writes are paused."
        )
    source_before = snapshot(database, "hms")
    if source_before != manifest["source_after"]:
        raise SafetyError(
            "Source changed since backup; use a fresh stable backup for exact comparison."
        )
    if any(
        manifest["source_after"].get(name, {}).get("rows", 0) == 0
        for name in REQUIRED_TABLES
    ):
        raise SafetyError(
            "Populated students, beds, allocations, payments and audit tables are required."
        )
    dump = folder / "hms.sql"
    if hashlib.sha256(dump.read_bytes()).hexdigest() != manifest["dump_sha256"]:
        raise SafetyError("Backup integrity failed.")
    validate_dump_sql(dump)
    connection = connect(database)
    created = False
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT SCHEMA_NAME FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME=%s",
                [TARGET],
            )
            if cursor.fetchone():
                raise SafetyError(
                    "test_hms already exists; stop other suites and do not overwrite it."
                )
            cursor.execute(
                "CREATE DATABASE `test_hms` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
            created = True
        with client_options(database, output) as options:
            with dump.open("rb") as stream:
                subprocess.run(
                    [
                        str(mysql_exe),
                        f"--defaults-extra-file={options}",
                        "--binary-mode",
                        "test_hms",
                    ],
                    stdin=stream,
                    capture_output=True,
                    check=True,
                )
        restored = snapshot(database, TARGET)
        source_after = snapshot(database, "hms")
        if restored != manifest["source_after"] or source_before != source_after:
            raise SafetyError(
                "Restored/source table digests differ; retain private evidence and investigate."
            )
        logical = consistency(database, TARGET)
        write_json(results / "recovery-consistency.json", logical)
        if not logical["all_consistency_checks_pass"]:
            raise SafetyError(
                "The restored database failed logical consistency checks."
            )
        report = {
            "case": "TC-OPS-01",
            "operation": "populated separate-database restore",
            "observed_at": datetime.now(UTC).isoformat(),
            "backup_completed_at": manifest["completed_at"],
            "backup_age_seconds": round(age.total_seconds(), 3),
            "source": "hms",
            "restore_target": TARGET,
            "source_unchanged": True,
            "all_table_counts_rows_and_schema_match": True,
            "logical_consistency": logical,
            "python_version": platform.python_version(),
            "recovery_script_sha256": hashlib.sha256(
                Path(__file__).read_bytes()
            ).hexdigest(),
            "required_populated_tables": list(REQUIRED_TABLES),
            "tables": restored,
            "dump_sha256": manifest["dump_sha256"],
            "data_loss_at_comparison": "none; all rows and schema digests match the unchanged source",
            "recovery_status": "PASS",
            "daily_schedule_status": "requires separate real Task Scheduler evidence",
        }
        write_json(results / "recovery-results.json", report)
        return report
    finally:
        try:
            if created:
                with connection.cursor() as cursor:
                    cursor.execute("DROP DATABASE `test_hms`")
        finally:
            connection.close()


def powershell_json(script):
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout)


def ps_literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def schedule_status():
    return powershell_json("""$ErrorActionPreference='Stop'
try {
  $t=Get-ScheduledTask -TaskName 'HMS-Issue40-DailyBackup' -ErrorAction Stop
  $i=Get-ScheduledTaskInfo -TaskName $t.TaskName
  $x=[xml](Export-ScheduledTask -TaskName $t.TaskName)
  [ordered]@{exists=$true;task_name=$t.TaskName;state=[string]$t.State;last_run=$i.LastRunTime.ToString('o');last_result=$i.LastTaskResult;next_run=$i.NextRunTime.ToString('o');daily_interval=[string]$x.Task.Triggers.CalendarTrigger.ScheduleByDay.DaysInterval;executable=$t.Actions[0].Execute;arguments=$t.Actions[0].Arguments}|ConvertTo-Json -Compress
} catch {
  [ordered]@{exists=$false;error_type=$_.Exception.GetType().Name;error_id=$_.FullyQualifiedErrorId}|ConvertTo-Json -Compress
}
""")


def install_schedule(output, dump_exe, delay, connection_file=None):
    if os.name != "nt" or not 1 <= delay <= 10:
        raise SafetyError(
            "A Windows daily trigger with a one-to-ten-minute first-run delay is required."
        )
    source_settings(connection_file)
    output = private_destination(output)
    protect_directory(output)
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.is_file():
        raise SafetyError("The hidden Python interpreter is unavailable.")
    # list2cmdline quotes Windows paths; arguments contain no credentials.
    command = [
        str(Path(__file__).resolve()),
        "backup",
        "--output-dir",
        str(output),
        "--dump-exe",
        str(dump_exe.resolve()),
    ]
    if connection_file is not None:
        command.extend(["--connection-file", str(Path(connection_file).resolve())])
    arguments = subprocess.list2cmdline(command)
    script = f"""$ErrorActionPreference='Stop'
try {{
  if(Get-ScheduledTask -TaskName {ps_literal(TASK_NAME)} -ErrorAction SilentlyContinue) {{ throw 'Task already exists; refusing to overwrite it.' }}
  $id=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  $a=New-ScheduledTaskAction -Execute {ps_literal(pythonw)} -Argument {ps_literal(arguments)} -WorkingDirectory {ps_literal(ROOT)}
  $t=New-ScheduledTaskTrigger -Daily -At (Get-Date).AddMinutes({delay})
  $p=New-ScheduledTaskPrincipal -UserId $id -LogonType Interactive -RunLevel Limited
  $s=New-ScheduledTaskSettingsSet -Hidden -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
  Register-ScheduledTask -TaskName {ps_literal(TASK_NAME)} -Action $a -Trigger $t -Principal $p -Settings $s -Description 'Private daily read-only HMS database backup; issue 40 TC-OPS-01'|Out-Null
  [ordered]@{{registered=$true;task_name={ps_literal(TASK_NAME)};first_trigger_minutes={delay};frequency='daily';logon='interactive current user; computer and session must be available'}}|ConvertTo-Json -Compress
}} catch {{
  [ordered]@{{registered=$false;error_type=$_.Exception.GetType().Name;error_id=$_.FullyQualifiedErrorId}}|ConvertTo-Json -Compress
}}
"""
    result = powershell_json(script)
    write_json(output / "schedule-registration.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "operation",
        choices=("backup", "recover", "install-schedule", "schedule-status"),
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--dump-exe", type=Path, default=MYSQL_BIN / "mysqldump.exe")
    parser.add_argument("--mysql-exe", type=Path, default=MYSQL_BIN / "mysql.exe")
    parser.add_argument(
        "--connection-file",
        type=Path,
        help="Private local-sandbox connection settings outside Git.",
    )
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        help="New private recovery evidence directory; preserve earlier results.",
    )
    parser.add_argument("--first-run-delay-minutes", type=int, default=2)
    args = parser.parse_args()
    if args.operation != "schedule-status" and args.output_dir is None:
        parser.error("A private --output-dir outside the repository is required.")
    try:
        if args.operation == "backup":
            result = backup(args.output_dir, args.dump_exe, args.connection_file)
        elif args.operation == "recover":
            result = recover(
                args.output_dir, args.mysql_exe, args.connection_file, args.evidence_dir
            )
        elif args.operation == "install-schedule":
            result = install_schedule(
                args.output_dir,
                args.dump_exe,
                args.first_run_delay_minutes,
                args.connection_file,
            )
        else:
            result = schedule_status()
        if sys.stdout is not None:
            print(json.dumps(result, indent=2))
        return 1 if result.get("registered") is False else 0
    except Exception as error:
        # Driver/subprocess messages can contain SQL or secrets: never print them.
        result = {
            "operation": args.operation,
            "status": "ERROR",
            "error_type": type(error).__name__,
        }
        if isinstance(error, SafetyError):
            result["reason"] = str(error)
        if args.output_dir is not None:
            try:
                output = private_destination(args.output_dir)
                protect_directory(output)
                write_json(output / "last-error.json", result)
            except Exception:
                pass
        if sys.stdout is not None:
            print(json.dumps(result))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
