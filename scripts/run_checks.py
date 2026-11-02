"""Run repository and Django/MySQL checks with reproducible, secret-free evidence.

Usage: python scripts/run_checks.py [--output-dir test-results/ci]
Relative output paths are resolved from the repository root. Tests use a separate
database; no check migrates or populates the application database. Run one suite
at a time against the configured MySQL test database.
"""

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCIES = (
    "Django",
    "mysqlclient",
    "python-dotenv",
    "reportlab",
    "pypdf",
    "coverage",
    "unittest-xml-reporting",
    "ruff",
)


def git_output(*args):
    try:
        result = subprocess.run(
            ["git", *args], cwd=ROOT, capture_output=True, text=True, check=False
        )
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def server_version():
    """Read only the server version, never connection settings or credentials."""
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hms.settings")
    import django

    django.setup()
    from django.db import connection

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT VERSION()")
            return cursor.fetchone()[0]
    finally:
        connection.close()


def verification_steps(output):
    """Keep the execution plan and completeness gate in one place."""
    return (
        ("lint", ["-m", "ruff", "check", "."]),
        ("format", ["-m", "ruff", "format", "--check", "."]),
        ("dependencies", ["-m", "pip", "check"]),
        ("django-checks", ["manage.py", "check", "--database", "default"]),
        ("applied-migrations", ["manage.py", "migrate", "--check"]),
        (
            "migration-consistency",
            ["manage.py", "makemigrations", "--check", "--dry-run"],
        ),
        (
            "staticfiles",
            [
                "manage.py",
                "collectstatic",
                "--dry-run",
                "--noinput",
                "--verbosity",
                "0",
            ],
        ),
        (
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
        ),
        ("coverage", ["-m", "coverage", "report"]),
        ("coverage-xml", ["-m", "coverage", "xml", "-o", str(output / "coverage.xml")]),
        (
            "coverage-json",
            ["-m", "coverage", "json", "-o", str(output / "coverage.json")],
        ),
        (
            "timing-smoke",
            [
                "manage.py",
                "test",
                "accounts.tests.AuthenticationTests.test_login_and_role_dashboard_respond_within_two_seconds",
                "--noinput",
            ],
        ),
    )


def run_step(name, arguments, output, environment):
    print(f"\nRunning {name}...", flush=True)
    started = time.monotonic()
    with (output / f"{name}.txt").open("w", encoding="utf-8") as log:
        with subprocess.Popen(
            [sys.executable, *arguments],
            cwd=ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        ) as process:
            for line in process.stdout:
                print(line, end="", flush=True)
                log.write(line)
            code = process.wait()
    return {
        "name": name,
        "arguments": arguments,
        "exit_code": code,
        "seconds": round(time.monotonic() - started, 3),
    }


def read_test_results(output):
    suites = [
        ElementTree.parse(path).getroot()
        for path in (output / "junit").glob("TEST-*.xml")
    ]
    totals = {
        key: sum(int(suite.get(key, 0)) for suite in suites)
        for key in ("tests", "failures", "errors", "skipped")
    }
    return totals, len(suites)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    started = datetime.now(UTC)
    output = args.output_dir or Path("test-results") / started.strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    output = (ROOT / output).resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        parser.error(
            "Choose a new, empty output directory so earlier evidence is preserved."
        )
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    # Coverage sets this in its child; the separate timing check runs normally.
    environment.pop("COVERAGE_RUN", None)
    environment.update(
        {
            "PYTHONUNBUFFERED": "1",
            "PYTHONIOENCODING": "utf-8",
            "COVERAGE_FILE": str(output / ".coverage"),
            "HMS_TEST_OUTPUT_DIR": str(output / "junit"),
        }
    )
    plan = verification_steps(output)
    git_status = git_output("status", "--porcelain")
    evidence = {
        "started_at": started.isoformat(),
        "commit": git_output("rev-parse", "HEAD"),
        "git_dirty": None if git_status is None else bool(git_status),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "steps": [],
    }
    try:
        evidence["dependencies"] = {name: version(name) for name in DEPENDENCIES}
        for name, arguments in plan:
            if name == "django-checks":
                evidence["mysql"] = server_version()
            evidence["steps"].append(run_step(name, arguments, output, environment))
        evidence["tests"], evidence["junit_files"] = read_test_results(output)
        evidence["coverage"] = json.loads(
            (output / "coverage.json").read_text(encoding="utf-8")
        )["totals"]
    except Exception as error:
        # Exceptions can contain credentials: record their type, never the text.
        evidence["setup_error_type"] = type(error).__name__
        print(
            f"Verification could not complete ({type(error).__name__}). Check the local configuration.",
            file=sys.stderr,
        )
    finally:
        evidence["completed_at"] = datetime.now(UTC).isoformat()
        tests = evidence.get("tests", {})
        evidence["success"] = (
            [step["name"] for step in evidence["steps"]] == [name for name, _ in plan]
            and all(step["exit_code"] == 0 for step in evidence["steps"])
            and tests.get("tests", 0) > 0
            and tests.get("failures", 0) == tests.get("errors", 0) == 0
            and "setup_error_type" not in evidence
        )
        (output / "run.json").write_text(
            json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
        )
        print(f"\nEvidence saved in {output}")
    return 0 if evidence["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
