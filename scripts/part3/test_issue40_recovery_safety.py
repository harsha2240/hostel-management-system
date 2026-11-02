"""Offline safety checks: no database, scheduled task or process is mutated."""

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import nullcontext
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import backup_issue40 as backup
import run_issue40_recovery as recovery


class RecoverySafetyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.private = Path(self.folder.name).resolve()
        self.datadir = self.private / "mysql-data"
        self.port = 58040
        self.process = Mock(pid=100)
        self.process.poll.return_value = None
        (self.private / "mysql.pid").write_text("101", encoding="ascii")

    def test_restore_rejects_live_or_unexpected_database(self):
        for source, target in (("hms", "hms"), ("other", "test_hms"), ("hms", "other")):
            with (
                self.subTest(source=source, target=target),
                self.assertRaises(backup.SafetyError),
            ):
                backup.validate_target(source, target)

    def test_backup_storage_rejects_repository(self):
        with self.assertRaises(backup.SafetyError):
            backup.private_destination(backup.ROOT / "test-results")

    def test_private_connection_rejects_live_port_and_nonlocal_host(self):
        path = self.private / "connection.json"
        values = {
            "DB_NAME": "hms",
            "DB_USER": "synthetic",
            "DB_PASSWORD": "synthetic",
            "DB_HOST": "127.0.0.1",
            "DB_PORT": 58040,
        }
        for update in (
            {"DB_PORT": 3306},
            {"DB_HOST": "remote.example.test"},
            {"DB_NAME": "other"},
        ):
            path.write_text(json.dumps({**values, **update}), encoding="utf-8")
            with self.subTest(update=update), self.assertRaises(backup.SafetyError):
                backup.source_settings(path)

    def test_dump_rejects_database_selection(self):
        path = self.private / "dump.sql"
        for statement in ("USE hms;", "CREATE DATABASE hms;", "DROP DATABASE hms;"):
            path.write_text(statement, encoding="ascii")
            with (
                self.subTest(statement=statement),
                self.assertRaises(backup.SafetyError),
            ):
                backup.validate_dump_sql(path)

    def metadata(self):
        executable = str((backup.MYSQL_BIN / "mysqld.exe").resolve())
        command = (
            f'"{executable}" --no-defaults --port={self.port} --datadir={self.datadir}'
        )
        return {
            "server": {
                "pid": 101,
                "parent": 100,
                "executable": executable,
                "command": command,
            },
            "launcher": {"pid": 100, "executable": executable, "command": command},
        }

    def test_windows_monitor_direct_child_is_owned(self):
        with patch.object(recovery, "powershell_json", return_value=self.metadata()):
            recovery.validate_owned_process(
                self.process, self.private, self.datadir, self.port
            )

    def test_process_ownership_rejects_unrelated_child_executable_or_command(self):
        for field, value in (
            ("parent", 999),
            ("executable", "C:/Windows/system32/cmd.exe"),
            ("command", "mysqld --port=3306"),
        ):
            metadata = self.metadata()
            metadata["server"][field] = value
            with (
                self.subTest(field=field),
                patch.object(recovery, "powershell_json", return_value=metadata),
                self.assertRaises(backup.SafetyError),
            ):
                recovery.validate_owned_process(
                    self.process, self.private, self.datadir, self.port
                )

    def connection(self, port=None, folder=None):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = (port or self.port, str(folder or self.datadir))
        return connection, cursor

    def test_server_identity_rejects_other_datadir_before_any_write(self):
        connection, cursor = self.connection(folder=self.private / "other-data")
        with self.assertRaises(backup.SafetyError):
            recovery.validate_connected_server(connection, self.datadir, self.port)
        self.assertEqual(
            cursor.execute.call_args_list[0].args, ("SELECT @@port, @@datadir",)
        )
        self.assertEqual(cursor.execute.call_count, 1)

    def test_shutdown_is_authenticated_and_uses_owned_child(self):
        connection, cursor = self.connection()
        with (
            patch.object(recovery, "powershell_json", return_value=self.metadata()),
            patch.object(recovery, "connect", return_value=connection),
        ):
            recovery.shutdown_owned_server(
                self.process, {}, self.private, self.datadir, self.port
            )
        self.assertEqual(
            [call.args[0] for call in cursor.execute.call_args_list],
            ["SELECT @@port, @@datadir", "SHUTDOWN"],
        )
        self.process.wait.assert_called_once_with(timeout=30)

    def test_shutdown_does_not_write_after_identity_mismatch(self):
        connection, cursor = self.connection(port=3306)
        with (
            patch.object(recovery, "powershell_json", return_value=self.metadata()),
            patch.object(recovery, "connect", return_value=connection),
            self.assertRaises(backup.SafetyError),
        ):
            recovery.shutdown_owned_server(
                self.process, {}, self.private, self.datadir, self.port
            )
        self.assertFalse(
            any(call.args[0] == "SHUTDOWN" for call in cursor.execute.call_args_list)
        )

    def test_task_cleanup_failure_still_stops_server_and_writes_report(self):
        report = {"status": "PASS"}
        with (
            patch.object(
                recovery,
                "remove_owned_task",
                side_effect=backup.SafetyError("injected"),
            ),
            patch.object(recovery, "shutdown_owned_server") as shutdown,
        ):
            recovery.cleanup_resources(
                {"arguments": "owned"},
                self.process,
                {},
                self.private,
                self.datadir,
                self.port,
                report,
            )
        shutdown.assert_called_once()
        saved = json.loads((self.private / "ops-results.json").read_text())
        self.assertEqual(saved["status"], "ERROR")
        self.assertTrue(saved["owned_sandbox_stopped"])
        self.assertEqual(saved["cleanup_errors"][0]["resource"], "sandbox task")

    def test_shutdown_refusal_is_saved_as_error(self):
        report = {"status": "PASS"}
        with patch.object(
            recovery,
            "shutdown_owned_server",
            side_effect=backup.SafetyError("injected"),
        ):
            recovery.cleanup_resources(
                None, self.process, {}, self.private, self.datadir, self.port, report
            )
        saved = json.loads((self.private / "ops-results.json").read_text())
        self.assertEqual(saved["status"], "ERROR")
        self.assertNotIn("owned_sandbox_stopped", saved)
        self.assertEqual(saved["cleanup_errors"][0]["resource"], "sandbox server")

    def scheduled_action(self):
        action = [
            str(Path(recovery.__file__).with_name("backup_issue40.py").resolve()),
            "backup",
            "--output-dir",
            str(self.private),
            "--dump-exe",
            str((backup.MYSQL_BIN / "mysqldump.exe").resolve()),
        ]
        return {
            "executable": str(Path(sys.executable).with_name("pythonw.exe")),
            "arguments": subprocess.list2cmdline(action),
        }

    def schedule_status(self, interval="1"):
        when = (datetime.now(UTC) + timedelta(seconds=10)).isoformat()
        (self.private / "latest.json").write_text(
            json.dumps({"completed_at": when}), encoding="utf-8"
        )
        return {
            **self.scheduled_action(),
            "last_result": 0,
            "state": "Ready",
            "last_run": when,
            "daily_interval": interval,
        }

    def test_scheduler_status_error_removes_owned_task(self):
        with (
            patch.object(
                recovery,
                "command",
                side_effect=[{"registered": True}, ValueError("injected status error")],
            ),
            patch.object(recovery, "remove_owned_task") as remove,
            self.assertRaises(ValueError),
        ):
            recovery.register_and_observe(self.private, None, {})
        remove.assert_called_once_with(self.scheduled_action())

    def test_invalid_daily_trigger_removes_owned_task(self):
        status = self.schedule_status(interval="2")
        with (
            patch.object(
                recovery, "command", side_effect=[{"registered": True}, status]
            ),
            patch.object(recovery, "remove_owned_task") as remove,
            self.assertRaises(backup.SafetyError),
        ):
            recovery.register_and_observe(self.private, None, {})
        remove.assert_called_once_with(self.scheduled_action())

    def test_successful_schedule_hands_off_task_without_removing_it(self):
        status = self.schedule_status()
        with (
            patch.object(
                recovery, "command", side_effect=[{"registered": True}, status]
            ),
            patch.object(recovery, "remove_owned_task") as remove,
        ):
            result = recovery.register_and_observe(self.private, None, {})
        self.assertTrue(result["observed_natural_trigger"])
        remove.assert_not_called()

    def test_running_task_with_zero_result_is_not_accepted_as_complete(self):
        ready = self.schedule_status()
        running = {**ready, "state": "Running"}
        with (
            patch.object(
                recovery, "command", side_effect=[{"registered": True}, running, ready]
            ) as command,
            patch.object(recovery, "remove_owned_task") as remove,
            patch.object(recovery.time, "sleep") as sleep,
        ):
            result = recovery.register_and_observe(self.private, None, {})
        self.assertEqual(result["state"], "Ready")
        self.assertEqual(command.call_count, 3)
        sleep.assert_called_once_with(2)
        remove.assert_not_called()

    def test_registration_evidence_failure_still_removes_owned_task(self):
        with (
            patch.object(recovery, "command", return_value={"registered": True}),
            patch.object(
                recovery,
                "write_json",
                side_effect=OSError("injected evidence write failure"),
            ),
            patch.object(recovery, "remove_owned_task") as remove,
            self.assertRaises(OSError),
        ):
            recovery.register_and_observe(self.private, None, {})
        remove.assert_called_once_with(self.scheduled_action())

    def prepared_backup(self):
        folder = self.private / "synthetic-backup"
        folder.mkdir()
        dump = folder / "hms.sql"
        dump.write_text("-- synthetic fixture\n", encoding="ascii")
        snapshot = {table: {"rows": 1} for table in backup.REQUIRED_TABLES}
        manifest = {
            "completed_at": datetime.now(UTC).isoformat(),
            "source_quiescent_during_backup": True,
            "source_after": snapshot,
            "dump_sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
        }
        (folder / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (self.private / "latest.json").write_text(
            json.dumps({"backup_directory": folder.name}), encoding="utf-8"
        )
        return snapshot, folder

    def test_existing_restore_target_is_never_overwritten_or_dropped(self):
        snapshot, _ = self.prepared_backup()
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = ("test_hms",)
        with (
            patch.object(backup, "source_settings", return_value={"NAME": "hms"}),
            patch.object(backup, "snapshot", return_value=snapshot),
            patch.object(backup, "connect", return_value=connection),
            patch.object(backup.subprocess, "run") as run,
            self.assertRaises(backup.SafetyError),
        ):
            backup.recover(self.private, Path("mysql.exe"))
        run.assert_not_called()
        self.assertEqual(cursor.execute.call_count, 1)
        self.assertTrue(
            cursor.execute.call_args.args[0].startswith("SELECT SCHEMA_NAME")
        )

    def test_failed_import_drops_only_new_owned_test_database(self):
        snapshot, _ = self.prepared_backup()
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None
        with (
            patch.object(backup, "source_settings", return_value={"NAME": "hms"}),
            patch.object(backup, "snapshot", return_value=snapshot),
            patch.object(backup, "connect", return_value=connection),
            patch.object(
                backup,
                "client_options",
                return_value=nullcontext(self.private / "private.cnf"),
            ),
            patch.object(
                backup.subprocess,
                "run",
                side_effect=subprocess.CalledProcessError(1, "mysql"),
            ),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            backup.recover(self.private, Path("mysql.exe"))
        mutations = [
            call.args[0]
            for call in cursor.execute.call_args_list
            if not call.args[0].startswith("SELECT")
        ]
        self.assertEqual(
            mutations,
            [
                "CREATE DATABASE `test_hms` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci",
                "DROP DATABASE `test_hms`",
            ],
        )

    def test_tampered_dump_is_refused_before_target_connection(self):
        snapshot, folder = self.prepared_backup()
        (folder / "hms.sql").write_text("-- tampered\n", encoding="ascii")
        with (
            patch.object(backup, "source_settings", return_value={"NAME": "hms"}),
            patch.object(backup, "snapshot", return_value=snapshot),
            patch.object(backup, "connect") as connect,
            self.assertRaises(backup.SafetyError),
        ):
            backup.recover(self.private, Path("mysql.exe"))
        connect.assert_not_called()

    def test_recovery_fails_on_logical_inconsistency_and_still_drops_owned_target(self):
        snapshot, _ = self.prepared_backup()
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchone.return_value = None
        logical = {
            "all_consistency_checks_pass": False,
            "violations": {"orphan_payment_student": 1},
        }
        with (
            patch.object(backup, "source_settings", return_value={"NAME": "hms"}),
            patch.object(backup, "snapshot", return_value=snapshot),
            patch.object(backup, "connect", return_value=connection),
            patch.object(
                backup,
                "client_options",
                return_value=nullcontext(self.private / "private.cnf"),
            ),
            patch.object(backup.subprocess, "run"),
            patch.object(backup, "consistency", return_value=logical),
            self.assertRaises(backup.SafetyError),
        ):
            backup.recover(self.private, Path("mysql.exe"))
        self.assertEqual(cursor.execute.call_args.args, ("DROP DATABASE `test_hms`",))
        self.assertEqual(
            json.loads((self.private / "recovery-consistency.json").read_text()),
            logical,
        )

    def test_mysql_decimal_receipt_aggregates_are_serializable(self):
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value

        def fetchone():
            if cursor.execute.call_args.args[0].startswith("SELECT COUNT(*), COALESCE"):
                return 2, Decimal("2"), Decimal("1")
            return (Decimal("0"),)

        cursor.fetchone.side_effect = fetchone
        cursor.fetchall.return_value = ((1, 2),)
        with patch.object(backup, "connect", return_value=connection):
            result = backup.consistency({}, "test_hms")
        self.assertTrue(result["all_consistency_checks_pass"])
        self.assertEqual(result["last_receipt_value"], 2)
        self.assertIs(type(result["last_receipt_value"]), int)
        json.dumps(result)


if __name__ == "__main__":
    unittest.main()
