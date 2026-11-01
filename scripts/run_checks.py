"""Run Django/MySQL verification and save reproducible, secret-free evidence.

Usage: python scripts/run_checks.py [--output-dir test-results/ci]
The test runner creates its separate test database; this never migrates the
configured application database. Do not run two instances against the same DB.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]


def git_output(*args):
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    started = datetime.now(timezone.utc)
    output = args.output_dir or Path("test-results") / started.strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    output = output.resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error(
            "Choose a new, empty output directory so earlier evidence is preserved."
        )
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    # Coverage sets this only in its child; the timing check must run normally.
    environment.pop("COVERAGE_RUN", None)
    environment.update(
        {
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "COVERAGE_FILE": str(output / ".coverage"),
            "HMS_TEST_OUTPUT_DIR": str(output / "junit"),
        }
    )
    evidence = {
        "started_at": started.isoformat(),
        "commit": git_output("rev-parse", "HEAD"),
        "git_dirty": bool(git_output("status", "--porcelain")),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "dependencies": {
            name: version(name)
            for name in (
                "Django",
                "mysqlclient",
                "reportlab",
                "pypdf",
                "coverage",
                "unittest-xml-reporting",
                "ruff",
            )
        },
        "steps": [],
    }

    def run(name, arguments):
        command = [sys.executable, *arguments]
        print(f"\nRunning {name}...", flush=True)
        step_started = time.monotonic()
        with (output / f"{name}.txt").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=ROOT,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
            code = process.wait()
        evidence["steps"].append(
            {
                "name": name,
                "arguments": arguments,
                "exit_code": code,
                "seconds": round(time.monotonic() - step_started, 3),
            }
        )
        return code

    try:
        run("lint", ["-m", "ruff", "check", "."])
        # Record only the server version, never connection settings or secrets.
        sys.path.insert(0, str(ROOT))
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hms.settings")
        import django

        django.setup()
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            evidence["mysql"] = cursor.fetchone()[0]
        connection.close()

        run("django-checks", ["manage.py", "check", "--database", "default"])
        run(
            "migration-consistency",
            ["manage.py", "makemigrations", "--check", "--dry-run"],
        )
        run(
            "test-results",
            [
                "-m",
                "coverage",
                "run",
                "manage.py",
                "test",
                "--noinput",
                "--testrunner=xmlrunner.extra.djangotestrunner.XMLTestRunner",
            ],
        )
        junit = [
            ElementTree.parse(path).getroot()
            for path in (output / "junit").glob("TEST-*.xml")
        ]
        evidence["tests"] = {
            key: sum(int(suite.get(key, 0)) for suite in junit)
            for key in ("tests", "failures", "errors", "skipped")
        }
        evidence["junit_files"] = len(junit)
        run("coverage", ["-m", "coverage", "report"])
        run(
            "coverage-xml",
            ["-m", "coverage", "xml", "-o", str(output / "coverage.xml")],
        )
        run(
            "coverage-json",
            ["-m", "coverage", "json", "-o", str(output / "coverage.json")],
        )
        run(
            "timing-smoke",
            [
                "manage.py",
                "test",
                "accounts.tests.AuthenticationTests.test_login_and_role_dashboard_respond_within_two_seconds",
                "--noinput",
            ],
        )
        if (output / "coverage.json").exists():
            evidence["coverage"] = json.loads(
                (output / "coverage.json").read_text(encoding="utf-8")
            )["totals"]
    except Exception as error:
        # A database connection exception may contain settings; keep it private.
        evidence["setup_error_type"] = type(error).__name__
        print(
            f"Verification could not complete ({type(error).__name__}). Check the local configuration.",
            file=sys.stderr,
        )
    finally:
        evidence["completed_at"] = datetime.now(timezone.utc).isoformat()
        evidence["success"] = (
            len(evidence["steps"]) == 8
            and evidence.get("tests", {}).get("tests", 0) > 0
            and "setup_error_type" not in evidence
            and all(step["exit_code"] == 0 for step in evidence["steps"])
        )
        (output / "run.json").write_text(
            json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\nEvidence saved in {output}")
    return 0 if evidence["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
