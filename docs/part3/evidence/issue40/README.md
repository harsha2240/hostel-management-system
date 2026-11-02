# Issue #40: candidate execution checkpoint

Owner: Devansh Gupta (`DevaOnL`). Date: 2 November 2026.
Scope: [HMS-18 / #40](https://github.com/Sreeharsha2240/hostel-management-system/issues/40)
only. This contributes owned execution evidence to the [Part 3 plan](../../../PART3.md);
the Unit, System Validation and Coverage reports remain their assigned work.

## Status and tested source

**Candidate checkpoint; final case/build acceptance is pending.** The updated
case register in #37 and PR #36 were still awaiting team acceptance at this run.
The observations below do not close #40 or establish the full Test Plan exit
criteria. No other contributor's execution issue or coverage issue #42 was
completed by this checkpoint.

The focused MySQL regression run tested candidate `c991e8827c97cfcb469e2868d152c544429a9d32`;
the browser run used `33491e3aa92f16781f3161733d2daadc510961d6`. Existing application,
test and template source was identical between those revisions. Both runs
truthfully record a dirty working tree while the documentation/manual harness
was being prepared. The browser evidence records SHA-256 hashes for the exact
three harness files used; these match the committed files. Preserve these facts
and rerun against the eventual accepted submission revision.

Environment: Windows; Python 3.14.7, Django 5.2.18, MySQL 8.4.9, Microsoft Edge
156.0.4314.58, Node.js 26.8.1 and Playwright 1.64.1. The browser harness uses a
threaded Django test server on loopback with a fresh disposable `test_hms`, real
HTTP requests and real commits, outside coverage instrumentation. This is a local
test-host observation, not deployed/concurrent-load acceptance.

## Evidence and original case mapping

- [Focused regression results](candidate-regressions.json): 60 unique methods,
  all passed, no errors/failures/skips. Includes MySQL concurrency/constraints,
  allocation and audit rollback, payment adjustments/immutability/PDF details,
  report exports and the integrated staff-to-student journey.
- [Browser/HTTP results](candidate-browser.json): real form actions, rendered
  rejection reasons, intermediate bed states, preserved history, PDF fields
  including date, downloaded CSVs, independent MySQL reconciliation, twenty
  allocation timings and overlapping conflict requests. Fixture data is synthetic.

| Original case | Candidate observation | Remaining acceptance work |
|---|---|---|
| TC-ALC-01 | Browser allocated an active male student to an available Boys-hostel bed, stored today's date, displayed confirmation and showed Occupied | Reviewed-case/final-build rerun |
| TC-ALC-02 | Another student's stale form was rejected with the occupied-bed reason; no duplicate allocation | Reviewed-case/final-build rerun |
| TC-ALC-03 | A student's second stale allocation form was rejected; original allocation ID/bed remained unchanged | Reviewed-case/final-build rerun |
| TC-ALC-04 | Female student/Boys hostel submission showed the gender-mismatch reason and wrote no allocation | Reviewed-case/final-build rerun |
| TC-ALC-05 | Browser transfer made the old bed Available and new bed Occupied, preserving history. Companion forced-save-failure regression passed with rollback | Browser JSON retains PARTIAL for its missing fault-injection step; the companion method below supplies that separate evidence. Reviewed-case/final-build rerun remains |
| TC-ALC-06 | Release stored the vacate date, made both released beds Available and displayed ordered historical rows | Reviewed-case/final-build rerun |
| TC-PAY-01 | Recorded INR 5,000 UPI payment; zero/negative submissions reached server validation without extra receipts; sequential numbering and downloaded PDF receipt fields matched | Reviewed-case/final-build rerun |
| TC-PAY-02 | Browser displayed Pending, Partial and Paid; final fee/paid/due values were INR 10,000 / 10,000 / 0 | Reviewed-case/final-build rerun |
| TC-RPT-01 | Filtered both reports and downloaded CSVs; HTML/CSV matched independently queried MySQL counts, room fees and payments | Reviewed-case/final-build rerun |
| TC-PERF-01 | NOT RUN: 50-user, ten-minute normal workload is outstanding | JMeter login/search/bed workload; at least 95% within two seconds and no errors |
| TC-PERF-02 | Twenty real committed HTTP allocations passed the under-three-second target; overlapping same-bed requests returned one 201 and one 409, with one active database row | Reviewed-case/final-build rerun; do not generalize local timings to 50-user load |
| TC-PERF-03 | NOT RUN: full 5,000-student/2,000-bed load execution is outstanding | Seed isolated synthetic volume and repeat the planned load/search measurement |
| TC-OPS-01 | NOT RUN: daily scheduling and populated separate-database recovery were not executed here | Demonstrate actual daily job, last-24-hour backup, separate populated restore and completeness/loss criteria |

The ALC-05 companion is
`allocations.test_workflows.AllocationWorkflowTests.test_transfer_failure_rolls_back_both_beds_and_history`.
Its passing result is in `candidate-regressions.json`; it deliberately fails the
target-bed save in a separate fixture and verifies the original active allocation,
both bed states, history count and absence of a committed transfer audit event.
The browser's own PARTIAL observation is preserved rather than rewritten.

Allocation timing: 20 samples, minimum **25.41 ms**, median **27.94 ms**, maximum
**36.35 ms**. Timing begins before each real HTTP POST and ends after its response
body; MySQL rows are checked independently after commits. Conflict-request client
intervals overlapped and the persisted bed had exactly one active allocation.
Raw samples, intervals and versions are in the browser JSON.

For the report fixture, the selected hostel had five beds: one occupied, three
available, one under maintenance, and 20.00% occupancy. The two student rows
showed one fully paid student and one pending resident. Other timing fixtures
used a separate hostel so they did not contaminate this filter's totals.

## Reproduce serially

Follow the repository's documented MySQL setup. Run only one Django/MySQL suite
at a time; do not point this harness at an application or recovery database.
The wrapper accepts only the documented MySQL `hms` configuration and lets
Django create/drop `test_hms`; custom or mirrored test databases are rejected.
The harness uses only synthetic fixtures and transmits ephemeral credentials to
the local browser process through stdin, without saving them in evidence.

Focused regression command:

```sh
python manage.py test allocations payments reports hms.test_system_journey --noinput --testrunner=xmlrunner.extra.djangotestrunner.XMLTestRunner
```

Set `HMS_TEST_OUTPUT_DIR` to a new ignored `test-results/` directory when saving
JUnit output. Inspect the exit status and XML totals; do not copy historical counts.

The explicit browser runner additionally needs Node.js, installed Microsoft Edge
and optional Playwright. It is intentionally separate from the normal CI suite.
For example, from the repository root in PowerShell:

```powershell
npm install --prefix .tmp/issue40-browser playwright@1.64.1
$env:NODE_PATH = (Resolve-Path .tmp/issue40-browser/node_modules).Path
python scripts/part3/run_issue40_browser.py
```

An already-installed private Playwright package may supply `NODE_PATH`; that was
used for this checkpoint. Dependencies stay outside tracked source. Each browser
run requires a fresh output directory and saves `browser-results.json` under
ignored `test-results/issue40-browser/`. Preserve failure console logs if a run
stops before producing JSON. Review and sanitize new evidence before publishing.

Before final acceptance, obtain the reviewed owned-case batch and accepted build,
complete PERF-01/PERF-03/OPS-01, log owned defects and retest, and supply the final
execution results to #38 and #37. MySQL client/dump binaries are installed locally;
the recovery target's permissions and a real daily scheduling arrangement still
need confirmation. No backup/scheduling pass is inferred from that preflight.
