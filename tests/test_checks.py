"""Verification must reject incomplete evidence and preserve earlier runs."""

import io
import json
import os
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase

from scripts import run_checks


class VerificationRunnerTests(SimpleTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.output = self.root / "evidence"
        for target, value in (
            ("ROOT", self.root),
            ("git_output", lambda *args: None),
            ("version", lambda name: "test-version"),
            ("server_version", lambda: "test-mysql"),
        ):
            context = patch.object(run_checks, target, value)
            context.start()
            self.addCleanup(context.stop)

    def run_with_evidence(
        self, *, failed_step=None, tests=2, failures=0, omit_junit=False
    ):
        environments = []

        def step(name, arguments, output, environment):
            environments.append(environment.copy())
            if name == "test-results" and not omit_junit:
                (output / "junit").mkdir()
                (output / "junit" / "TEST-example.xml").write_text(
                    f'<testsuite tests="{tests}" failures="{failures}" errors="0" skipped="0"/>',
                    encoding="utf-8",
                )
            if name == "coverage-json":
                (output / "coverage.json").write_text(
                    json.dumps({"totals": {"percent_covered": 90}}), encoding="utf-8"
                )
            return {"name": name, "exit_code": int(name == failed_step)}

        with (
            patch.object(run_checks, "run_step", side_effect=step),
            redirect_stdout(io.StringIO()),
        ):
            result = run_checks.main(
                ["--output-dir", str(self.output.relative_to(self.root))]
            )
        evidence = json.loads((self.output / "run.json").read_text(encoding="utf-8"))
        return result, evidence, environments

    def test_success_requires_all_gates_and_writes_root_relative_evidence(self):
        with patch.dict(os.environ, {"COVERAGE_RUN": "true"}):
            result, evidence, environments = self.run_with_evidence()
        self.assertEqual(result, 0)
        self.assertTrue(evidence["success"])
        self.assertEqual(evidence["tests"]["tests"], 2)
        self.assertEqual(evidence["junit_files"], 1)
        self.assertEqual(evidence["mysql"], "test-mysql")
        self.assertIsNone(evidence["git_dirty"])
        self.assertTrue(environments)
        self.assertTrue(all("COVERAGE_RUN" not in env for env in environments))
        self.assertTrue(
            all(
                env["HMS_TEST_OUTPUT_DIR"] == str(self.output / "junit")
                for env in environments
            )
        )

    def test_git_status_distinguishes_clean_and_dirty_trees(self):
        for label, status in (("clean", ""), ("dirty", " M example.py")):
            with self.subTest(status=label):
                self.output = self.root / label
                with patch.object(run_checks, "git_output", return_value=status):
                    _, evidence, _ = self.run_with_evidence()
                self.assertIs(evidence["git_dirty"], bool(status))

    def test_failed_gate_cannot_report_success(self):
        for name, _ in run_checks.verification_steps(self.output):
            with self.subTest(gate=name):
                self.output = self.root / name
                result, evidence, _ = self.run_with_evidence(failed_step=name)
                self.assertEqual(result, 1)
                self.assertFalse(evidence["success"])

    def test_missing_empty_or_failed_test_evidence_cannot_report_success(self):
        for label, options in (
            ("missing", {"omit_junit": True}),
            ("empty", {"tests": 0}),
            ("failed", {"failures": 1}),
        ):
            with self.subTest(label=label):
                self.output = self.root / label
                result, evidence, _ = self.run_with_evidence(**options)
                self.assertEqual(result, 1)
                self.assertFalse(evidence["success"])

    def test_setup_failure_saves_failure_without_exception_message(self):
        console = io.StringIO()
        with (
            patch.object(
                run_checks, "version", side_effect=RuntimeError("private-value")
            ),
            redirect_stdout(console),
            redirect_stderr(console),
        ):
            result = run_checks.main(["--output-dir", "evidence"])
        raw = (self.output / "run.json").read_text(encoding="utf-8")
        evidence = json.loads(raw)
        self.assertEqual(result, 1)
        self.assertFalse(evidence["success"])
        self.assertEqual(evidence["setup_error_type"], "RuntimeError")
        self.assertNotIn("private-value", raw + console.getvalue())

    def test_occupied_output_is_not_overwritten(self):
        self.output.mkdir()
        marker = self.output / "run.json"
        marker.write_text("earlier evidence", encoding="utf-8")
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            run_checks.main(["--output-dir", "evidence"])
        self.assertEqual(error.exception.code, 2)
        self.assertEqual(marker.read_text(encoding="utf-8"), "earlier evidence")

    def test_subprocess_failure_is_captured_in_log_and_exit_code(self):
        self.output.mkdir()
        with redirect_stdout(io.StringIO()):
            result = run_checks.run_step(
                "example",
                ["-c", "print('diagnostic'); raise SystemExit(3)"],
                self.output,
                os.environ.copy(),
            )
        self.assertEqual(result["exit_code"], 3)
        self.assertIn(
            "diagnostic", (self.output / "example.txt").read_text(encoding="utf-8")
        )
