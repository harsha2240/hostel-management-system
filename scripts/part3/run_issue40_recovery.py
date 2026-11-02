"""Demonstrate #40 recovery using a private, populated MySQL sandbox.

The installed application database is never seeded or restored. The temporary
MySQL server uses a new private datadir and an unused loopback port. Observe a
natural daily Task Scheduler trigger against the sandbox, restore its backup,
then replace only that exact owned task with a read-only daily live hms backup.
Credentials, SQL dumps and raw scheduler actions remain outside Git.
"""

import argparse
import hashlib
import io
import json
import os
import platform
import secrets
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from backup_issue40 import (
    MYSQL_BIN,
    ROOT,
    TASK_NAME,
    SafetyError,
    connect,
    powershell_json,
    private_destination,
    protect_directory,
    ps_literal,
    source_settings,
    write_json,
)


def command(arguments, *, environment=None):
    result = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).with_name("backup_issue40.py")),
            *arguments,
        ],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
        timeout=180,
    )
    try:
        data = json.loads(result.stdout)
    except (json.JSONDecodeError, TypeError) as error:
        raise SafetyError(
            "The backup operation did not return sanitized JSON."
        ) from error
    if result.returncode:
        # The backup CLI intentionally removes driver messages and credentials.
        raise SafetyError(f"Backup operation failed: {data}")
    return data


def register_and_observe(output, connection_file, environment):
    args = [
        "install-schedule",
        "--output-dir",
        str(output),
        "--first-run-delay-minutes",
        "1",
    ]
    if connection_file is not None:
        args.extend(["--connection-file", str(connection_file)])
    action = [
        str(Path(__file__).with_name("backup_issue40.py").resolve()),
        "backup",
        "--output-dir",
        str(output),
        "--dump-exe",
        str((MYSQL_BIN / "mysqldump.exe").resolve()),
    ]
    if connection_file is not None:
        action.extend(["--connection-file", str(connection_file.resolve())])
    owned = {
        "executable": str(Path(sys.executable).with_name("pythonw.exe")),
        "arguments": subprocess.list2cmdline(action),
    }
    handed_off = False
    try:
        registered_at = datetime.now(UTC)
        registration = command(args, environment=environment)
        write_json(output / "registration-evidence.json", registration)
        deadline = time.monotonic() + 150
        while time.monotonic() < deadline:
            status = command(["schedule-status"], environment=environment)
            latest_file = output / "latest.json"
            if (
                status.get("state") == "Ready"
                and status.get("last_result") == 0
                and latest_file.is_file()
            ):
                last_run = datetime.fromisoformat(status["last_run"])
                if last_run.astimezone(UTC) >= registered_at:
                    latest = json.loads(latest_file.read_text(encoding="utf-8"))
                    completed = datetime.fromisoformat(latest["completed_at"])
                    if completed >= registered_at:
                        status["registration_observed_at"] = registered_at.isoformat()
                        status["backup_completed_at"] = latest["completed_at"]
                        status["observed_natural_trigger"] = True
                        if status.get("daily_interval") != "1":
                            raise SafetyError(
                                "The observed task is not a daily backup."
                            )
                        if any(
                            status.get(key) != value for key, value in owned.items()
                        ):
                            raise SafetyError("The observed daily task action changed.")
                        write_json(output / "scheduler-observation.json", status)
                        handed_off = True
                        return status
            time.sleep(2)
        raise SafetyError(
            "The daily backup did not complete successfully within 150 seconds."
        )
    finally:
        if not handed_off:
            remove_owned_task(owned)


def remove_owned_task(expected):
    # Exact executable and complete argument equality protects another task with
    # the same display name from being removed after a concurrent replacement.
    result = powershell_json(f"""$ErrorActionPreference='Stop'
$t=Get-ScheduledTask -TaskName {ps_literal(TASK_NAME)}
if($t.Actions.Count -ne 1 -or $t.Actions[0].Execute -ne {ps_literal(expected["executable"])} -or $t.Actions[0].Arguments -ne {ps_literal(expected["arguments"])}) {{throw 'Task ownership changed; refusing removal.'}}
Unregister-ScheduledTask -TaskName $t.TaskName -Confirm:$false
[ordered]@{{removed=$true;task_name=$t.TaskName}}|ConvertTo-Json -Compress
""")
    if not result.get("removed"):
        raise SafetyError("The owned sandbox backup task was not removed.")


def validate_owned_process(process, private, datadir, port):
    """Account for Windows mysqld's monitor process and its direct child."""
    pid_file = private / "mysql.pid"
    server_pid = int(pid_file.read_text().strip())
    metadata = powershell_json(f"""$ErrorActionPreference='Stop'
$server=Get-CimInstance Win32_Process -Filter 'ProcessId = {server_pid}'
$launcher=Get-CimInstance Win32_Process -Filter 'ProcessId = {process.pid}'
[ordered]@{{server=[ordered]@{{pid=$server.ProcessId;parent=$server.ParentProcessId;executable=$server.ExecutablePath;command=$server.CommandLine}};launcher=[ordered]@{{pid=$launcher.ProcessId;executable=$launcher.ExecutablePath;command=$launcher.CommandLine}}}}|ConvertTo-Json -Compress -Depth 3
""")
    server, launcher = metadata["server"], metadata["launcher"]
    executable = (MYSQL_BIN / "mysqld.exe").resolve()
    if server["pid"] != server_pid or launcher["pid"] != process.pid:
        raise SafetyError("The owned MySQL processes could not be identified.")
    if server_pid != process.pid and server["parent"] != process.pid:
        raise SafetyError("The MySQL server is not the owned launcher's direct child.")
    for item in (server, launcher):
        if Path(item["executable"]).resolve() != executable:
            raise SafetyError("The owned MySQL executable changed.")
        if (
            "--no-defaults" not in item["command"]
            or f"--port={port}" not in item["command"]
            or f"--datadir={datadir}" not in item["command"]
        ):
            raise SafetyError("The owned MySQL command changed.")


def validate_connected_server(connection, datadir, port):
    with connection.cursor() as cursor:
        cursor.execute("SELECT @@port, @@datadir")
        actual_port, actual_datadir = cursor.fetchone()
        if int(actual_port) != port or Path(actual_datadir).resolve() != datadir:
            raise SafetyError("The connected server is not the private sandbox.")


def shutdown_owned_server(process, database, private, datadir, port):
    if process.poll() is not None:
        if (private / "mysql.pid").exists():
            raise SafetyError("The launcher exited but a sandbox PID file remains.")
        return
    validate_owned_process(process, private, datadir, port)
    connection = connect(database, "mysql")
    try:
        validate_connected_server(connection, datadir, port)
        with connection.cursor() as cursor:
            cursor.execute("SHUTDOWN")
    finally:
        connection.close()
    process.wait(timeout=30)


def cleanup_resources(
    sandbox_task, process, database, private, datadir, port, report, results_dir=None
):
    errors = []
    if sandbox_task is not None:
        try:
            remove_owned_task(sandbox_task)
        except Exception as error:
            errors.append(
                {"resource": "sandbox task", "error_type": type(error).__name__}
            )
    if process is not None:
        try:
            shutdown_owned_server(process, database, private, datadir, port)
            report["owned_sandbox_stopped"] = True
        except Exception as error:
            errors.append(
                {"resource": "sandbox server", "error_type": type(error).__name__}
            )
    if errors:
        report["cleanup_errors"] = errors
        report["status"] = "ERROR"
    report["completed_at"] = datetime.now(UTC).isoformat()
    write_json((results_dir or private) / "ops-results.json", report)


def seed_sandbox(connection_file):
    database = source_settings(connection_file)
    from django.core.management import call_command
    from django.db import connection

    if str(connection.settings_dict["PORT"]) != str(database["PORT"]):
        raise SafetyError("Django is not connected to the private sandbox.")
    call_command("migrate", interactive=False, stdout=io.StringIO(), verbosity=0)
    from accounts.models import User
    from allocations.services import allocate, release
    from hostels.models import Bed, Hostel
    from payments.models import Payment
    from tests.factories import make_room, make_student

    actor = User.objects.create_user(
        username="issue40-ops-warden",
        password=secrets.token_urlsafe(24),
        role=User.Role.WARDEN,
    )
    students = [make_student(700 + index) for index in range(3)]
    hostel = Hostel.objects.create(name="Issue40 Recovery Boys", hostel_type="Boys")
    room = make_room("OPS40", hostel=hostel, capacity=4, fee_amount="10000.00")
    beds = list(room.beds.all())
    allocate(student=students[0], bed=beds[0], actor=actor)
    historical = allocate(student=students[1], bed=beds[1], actor=actor)
    release(allocation_id=historical.pk, actor=actor)
    beds[3].status = Bed.BedStatus.MAINTENANCE
    beds[3].save(update_fields=["status"])
    original = Payment.objects.create(
        student=students[0], amount="1000.00", mode="Cash"
    )
    Payment.objects.create(
        student=students[0],
        amount="-100.00",
        mode="Cash",
        adjustment_of=original,
        adjustment_reason="Synthetic recovery verification",
    )
    connection.close()
    return database


def resume(private):
    """Rerun restoration/cleanup only; preserve existing daily task and evidence."""
    private = private_destination(private)
    datadir = (private / "mysql-data").resolve()
    connection_file = private / "sandbox-connection.json"
    if (
        not datadir.is_dir()
        or datadir.parent != private
        or not connection_file.is_file()
    ):
        raise SafetyError("The existing private sandbox failed its containment check.")
    if (private / "mysql.pid").exists():
        raise SafetyError(
            "The private sandbox already has a PID file; do not overwrite a running instance."
        )
    original_environment = dict(os.environ)
    database = source_settings(connection_file)
    port = int(database["PORT"])
    if port == 3306:
        raise SafetyError("The sandbox port must differ from the live server port.")
    with socket.socket() as port_check:
        port_check.bind(("127.0.0.1", port))
    results = private / datetime.now(UTC).strftime("rerun-%Y%m%dT%H%M%S%fZ")
    protect_directory(results)
    report = {
        "case": "TC-OPS-01",
        "operation": "post-fix populated recovery and monitor-child cleanup rerun",
        "started_at": datetime.now(UTC).isoformat(),
        "scope": "same isolated populated synthetic MySQL source and original naturally scheduled backup; existing live daily task unchanged",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "working_tree_dirty": bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=ROOT, text=True
            ).strip()
        ),
        "source_script_sha256": hashlib.sha256(
            Path(__file__).with_name("backup_issue40.py").read_bytes()
        ).hexdigest(),
        "runner_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "sandbox_port": port,
        "sandbox_bind": "127.0.0.1",
        "live_application_database_seeded_or_restored": False,
    }
    process = None
    try:
        with (results / "server-console.log").open("xb") as log:
            process = subprocess.Popen(
                [
                    str(MYSQL_BIN / "mysqld.exe"),
                    "--no-defaults",
                    f"--datadir={datadir}",
                    "--bind-address=127.0.0.1",
                    f"--port={port}",
                    "--mysqlx=0",
                    "--skip-log-bin",
                    f"--log-error={results / 'mysql-error.log'}",
                    f"--pid-file={private / 'mysql.pid'}",
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        import MySQLdb

        deadline = time.monotonic() + 60
        while True:
            if process.poll() is not None:
                raise SafetyError(
                    "The existing private MySQL server stopped during startup."
                )
            try:
                control = connect(database, "mysql")
                break
            except MySQLdb.OperationalError:
                if time.monotonic() >= deadline:
                    raise SafetyError(
                        "The existing private MySQL server did not start."
                    ) from None
                time.sleep(0.25)
        try:
            validate_owned_process(process, private, datadir, port)
            validate_connected_server(control, datadir, port)
            with control.cursor() as cursor:
                cursor.execute("SELECT VERSION()")
                report["mysql_version"] = cursor.fetchone()[0]
        finally:
            control.close()
        import django

        report["django_version"] = django.get_version()
        report["mysql_client_version"] = (
            subprocess.check_output(
                [str(MYSQL_BIN / "mysql.exe"), "--version"], text=True
            )
            .strip()
            .split("  Ver ")[-1]
        )
        report["populated_recovery"] = command(
            [
                "recover",
                "--output-dir",
                str(private / "sandbox-backups"),
                "--connection-file",
                str(connection_file),
                "--evidence-dir",
                str(results / "recovery"),
            ],
            environment=original_environment,
        )
        observed = command(["schedule-status"], environment=original_environment)
        expected = json.loads(
            (private / "live-backups/scheduler-observation.json").read_text(
                encoding="utf-8"
            )
        )
        if any(
            observed.get(key) != expected.get(key)
            for key in ("executable", "arguments")
        ):
            raise SafetyError("The existing live daily task action changed.")
        if (
            observed.get("state") != "Ready"
            or observed.get("last_result") != 0
            or observed.get("daily_interval") != "1"
        ):
            raise SafetyError(
                "The existing live daily task is not Ready with a successful daily run."
            )
        report["live_daily_schedule"] = {
            key: value
            for key, value in observed.items()
            if key not in ("executable", "arguments")
        }
        report["live_daily_schedule"]["action_sha256"] = hashlib.sha256(
            (observed["executable"] + "\n" + observed["arguments"]).encode()
        ).hexdigest()
        control = connect(database, "mysql")
        try:
            with control.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME='test_hms'"
                )
                report["owned_restore_target_removed"] = cursor.fetchone()[0] == 0
        finally:
            control.close()
        if not report["owned_restore_target_removed"]:
            raise SafetyError("The disposable restore target was not removed.")
        report["status"] = "PASS"
    except Exception as error:
        report["status"] = "ERROR"
        report["error_type"] = type(error).__name__
        if isinstance(error, SafetyError):
            report["reason"] = str(error)
    finally:
        cleanup_resources(
            None, process, database, private, datadir, port, report, results_dir=results
        )
        print(
            json.dumps(
                {
                    "case": "TC-OPS-01",
                    "status": report.get("status"),
                    "private_results_file": str(results / "ops-results.json"),
                },
                indent=2,
            )
        )
    return 0 if report.get("status") == "PASS" else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--private-dir", type=Path)
    mode.add_argument("--resume-private-dir", type=Path)
    args = parser.parse_args()
    if args.resume_private_dir is not None:
        return resume(args.resume_private_dir)
    private = private_destination(args.private_dir)
    if private.exists():
        parser.error(
            "Choose a previously absent private directory to preserve evidence."
        )
    protect_directory(private)
    original_environment = dict(os.environ)
    source = Path(__file__).with_name("backup_issue40.py")
    initial = command(["schedule-status"], environment=original_environment)
    if initial.get("exists"):
        raise SafetyError("A daily task already exists; refusing to replace it.")
    datadir = (private / "mysql-data").resolve()
    if datadir.parent != private or datadir.exists():
        raise SafetyError("The new sandbox datadir failed its containment check.")
    with socket.socket() as port_selection:
        port_selection.bind(("127.0.0.1", 0))
        port = port_selection.getsockname()[1]
    if port == 3306:
        raise SafetyError("The selected sandbox port conflicts with the live database.")
    mysqld = MYSQL_BIN / "mysqld.exe"
    with (private / "initialize.log").open("xb") as log:
        subprocess.run(
            [
                str(mysqld),
                "--no-defaults",
                "--initialize-insecure",
                f"--datadir={datadir}",
            ],
            stdout=log,
            stderr=subprocess.STDOUT,
            check=True,
            timeout=180,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    process = None
    database = None
    sandbox_task = None
    report = {
        "case": "TC-OPS-01",
        "started_at": datetime.now(UTC).isoformat(),
        "scope": "isolated synthetic populated recovery plus separate live read-only daily backup",
        "source_script_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "runner_script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "sandbox_bind": "127.0.0.1",
        "sandbox_port": port,
        "live_application_database_seeded_or_restored": False,
    }
    try:
        with (private / "server-console.log").open("xb") as log:
            process = subprocess.Popen(
                [
                    str(mysqld),
                    "--no-defaults",
                    f"--datadir={datadir}",
                    "--bind-address=127.0.0.1",
                    f"--port={port}",
                    "--mysqlx=0",
                    "--skip-log-bin",
                    f"--log-error={private / 'mysql-error.log'}",
                    f"--pid-file={private / 'mysql.pid'}",
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        import MySQLdb

        database = {"HOST": "127.0.0.1", "PORT": port, "USER": "root", "PASSWORD": ""}
        deadline = time.monotonic() + 60
        while True:
            if process.poll() is not None:
                raise SafetyError("The private MySQL server stopped during startup.")
            try:
                bootstrap = MySQLdb.connect(
                    host="127.0.0.1", port=port, user="root", passwd="", autocommit=True
                )
                break
            except MySQLdb.OperationalError:
                if time.monotonic() >= deadline:
                    raise SafetyError(
                        "The private MySQL server did not start."
                    ) from None
                time.sleep(0.25)
        password = secrets.token_urlsafe(32)
        validate_owned_process(process, private, datadir, port)
        validate_connected_server(bootstrap, datadir, port)
        with bootstrap.cursor() as cursor:
            cursor.execute("ALTER USER CURRENT_USER() IDENTIFIED BY %s", [password])
            database["PASSWORD"] = password
            cursor.execute(
                "CREATE DATABASE `hms` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
        bootstrap.close()
        connection_file = private / "sandbox-connection.json"
        write_json(
            connection_file,
            {
                "DB_NAME": "hms",
                "DB_HOST": "127.0.0.1",
                "DB_PORT": port,
                "DB_USER": "root",
                "DB_PASSWORD": password,
            },
        )
        database = seed_sandbox(connection_file)
        sandbox_output = private / "sandbox-backups"
        protect_directory(sandbox_output)
        sandbox_task = register_and_observe(
            sandbox_output, connection_file, original_environment
        )
        report["sandbox_schedule"] = {
            key: value
            for key, value in sandbox_task.items()
            if key not in ("executable", "arguments")
        }
        report["sandbox_schedule"]["action_sha256"] = hashlib.sha256(
            (sandbox_task["executable"] + "\n" + sandbox_task["arguments"]).encode()
        ).hexdigest()
        report["populated_recovery"] = command(
            [
                "recover",
                "--output-dir",
                str(sandbox_output),
                "--connection-file",
                str(connection_file),
            ],
            environment=original_environment,
        )
        remove_owned_task(sandbox_task)
        sandbox_task = None
        live_output = private / "live-backups"
        protect_directory(live_output)
        live = register_and_observe(live_output, None, original_environment)
        report["live_daily_schedule"] = {
            key: value
            for key, value in live.items()
            if key not in ("executable", "arguments")
        }
        report["live_daily_schedule"]["action_sha256"] = hashlib.sha256(
            (live["executable"] + "\n" + live["arguments"]).encode()
        ).hexdigest()
        latest = json.loads((live_output / "latest.json").read_text(encoding="utf-8"))
        manifest = json.loads(
            (live_output / latest["backup_directory"] / "manifest.json").read_text(
                encoding="utf-8"
            )
        )
        report["live_backup"] = {
            "completed_at": manifest["completed_at"],
            "dump_sha256": manifest["dump_sha256"],
            "source_unchanged": manifest["source_quiescent_during_backup"],
            "table_row_counts": {
                name: table["rows"] for name, table in manifest["source_after"].items()
            },
            "populated_restore_scope": "the live source has no domain rows; populated restore is demonstrated only in the separate sandbox",
        }
        if not report["live_backup"]["source_unchanged"]:
            raise SafetyError("The live source changed while its read-only backup ran.")
        report["daily_schedule_limitation"] = (
            "Current Windows user must be logged in and computer/MySQL running; StartWhenAvailable handles a missed trigger when available."
        )
        report["status"] = "PASS"
    except Exception as error:
        report["status"] = "ERROR"
        report["error_type"] = type(error).__name__
        if isinstance(error, SafetyError):
            report["reason"] = str(error)
    finally:
        cleanup_resources(
            sandbox_task, process, database, private, datadir, port, report
        )
        print(
            json.dumps(
                {
                    "case": "TC-OPS-01",
                    "status": report.get("status"),
                    "private_results_file": str(private / "ops-results.json"),
                },
                indent=2,
            )
        )
    return 0 if report.get("status") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
