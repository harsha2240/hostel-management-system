# Part 3: testing, reports and team delivery

This is the team work plan for **2-6 November 2026**. The assigned contributors
execute their cases and prepare their own evidence; their assignments remain
open. Vaishnavi coordinates QA, Devansh leads development/coverage, and Sreeharsha
coordinates integration and final readiness.

## Instructions and baseline

The [Part 3 instructions](part3/SE_Mini_Project_Delivereables_Part-3.pdf), page 1,
require updated test cases and the Test Case Document, all testing according to
the submitted Test Plan, and four reports uploaded to `docs/`. Sprint 3 is
optional for actual development spillover, with testing/reporting in parallel.
The PDF gives the **2-6 November** window but no submission hour or report format.
The year 2026 follows the Part 1/2 project schedule. Intermediate dates,
estimates, Markdown filenames and the milestone are team planning choices.
The milestone represents the 6 November date, not a faculty-specified cutoff time.

Use these source documents together:

- [Test Plan](../Test_Plan_Hostel_Management_System.docx), especially sections 5,
  5.1, 6, 9, 13-15, and its [PDF](../pdf/Test_Plan_Hostel_Management_System.pdf).
- [SRS](../SRS_Hostel_Management_System.docx) and
  [SAD](../SAD_Hostel_Management_System.docx), with their copies under `pdf/`.
- [Work Distribution](../HMS_Part1_Work_Distribution.docx) and
  [Sprint Backlog](../HMS_Part1_Sprint_Backlog.docx) for existing ownership.
- [Sprint 1 testing](SPRINT1_TESTING.md), [Sprint 2 notes](SPRINT2.md) and the
  [submission checklist](SUBMISSION_CHECKLIST.md).

The original Test Plan contains **33 planned case IDs** and an RTM for
**36 requirements** (REQ-1 through REQ-24, NFR-1 through NFR-12), plus quality
attributes. The updated Test Case Document must retain these IDs, explain
revisions, add sprint regression cases and map automated methods to them.
Priorities need review because the original case table lacks priority fields.
Resolve the old TC-AUTH-03 lockout-message wording against SRS REQ-2's generic
credential-error requirement while preserving the five-attempt/15-minute test.

[PR #36](https://github.com/Sreeharsha2240/hostel-management-system/pull/36)
was still open at setup on 2 November; `main` was `0abb29a` and the verified code
candidate was `d77a1c0`. Its [CI baseline](https://github.com/Sreeharsha2240/hostel-management-system/actions/runs/41334260491)
recorded 185 mixed unit/integration/system methods, one expected timing skip
under coverage followed by a separate timing pass, 94.28% statement coverage,
85.57% branch coverage and 92.63% combined coverage. Final reports must identify
the accepted submission revision and its own evidence; the baseline does not
establish execution of all planned cases.

## Assigned backlog

All seven tasks belong to the [Part 3 milestone](https://github.com/Sreeharsha2240/hostel-management-system/milestone/1). Estimates
are initial planning values for team review, not historical effort or an
instructor requirement. The historical Sprint 1/2 issues stay closed.

| Work | Accountable contributor | Initial points | Dependency / output |
|---|---|---:|---|
| [HMS-15 / #37](https://github.com/Sreeharsha2240/hostel-management-system/issues/37) | Vaishnavi (`VaishnaviCH6`) | 3 | Updated Test Case Document and RTM; all members contribute their cases |
| [HMS-16 / #38](https://github.com/Sreeharsha2240/hostel-management-system/issues/38) | Sreeharsha (`harsha2240`) | 8 | 12 auth/user/security cases; System Validation Report integrates other owners' evidence with QA |
| [HMS-17 / #39](https://github.com/Sreeharsha2240/hostel-management-system/issues/39) | Vaishnavi (`VaishnaviCH6`) | 5 | 8 student/hostel/quality cases; feeds System Validation Report |
| [HMS-18 / #40](https://github.com/Sreeharsha2240/hostel-management-system/issues/40) | Devansh (`DevaOnL`) | 8 | 13 allocation/payment/report/performance/recovery cases; feeds System Validation Report |
| [HMS-19 / #41](https://github.com/Sreeharsha2240/hostel-management-system/issues/41) | Vaishnavi (`VaishnaviCH6`) | 3 | Unit Test Report; module owners provide unit results; parallel with system execution |
| [HMS-20 / #42](https://github.com/Sreeharsha2240/hostel-management-system/issues/42) | Devansh (`DevaOnL`) | 3 | Two distinct coverage reports from the same accepted revision/run |
| [HMS-21 / #43](https://github.com/Sreeharsha2240/hostel-management-system/issues/43) | Sreeharsha (`harsha2240`) | 2 | Final review, publication, actual approvals and submission confirmation |

Original execution ownership is preserved:

| Owner | Existing case IDs | Count |
|---|---|---:|
| Sreeharsha | TC-AUTH-01 to TC-AUTH-04; TC-USR-01; TC-SEC-01 to TC-SEC-07 | 12 |
| Vaishnavi | TC-STU-01 to TC-STU-05; TC-HST-01 to TC-HST-02; TC-QUAL-01 | 8 |
| Devansh | TC-ALC-01 to TC-ALC-06; TC-PAY-01 to TC-PAY-02; TC-RPT-01; TC-PERF-01 to TC-PERF-03; TC-OPS-01 | 13 |

Vaishnavi coordinates the case register, execution summaries and QA review;
Sreeharsha coordinates the integrated System Validation Report and PO readiness;
Devansh supports unit tests, coverage, triage and technical fixes. Each author
opens their own focused PR and receives independent teammate review as described
in [README](../README.md#team-collaboration-hms-03). Record actual contributors
and approvals; preserve truthful contribution/signature histories.

GitHub Project synchronization is **blocked**: the current token lacks
`read:project` scope. Issues, labels and the milestone are the published planning
view. The final coordination task tracks adding these issues to the existing
Project and setting Status, Estimate and Part 3 iteration when access is available.
Preserve Sprint 1/2 history and record the Project update only once it happens.

## Order and dates

| Date | Internal team plan |
|---|---|
| 2 November | Confirm accepted test build/environment and access; start case review, unit/coverage work, deployment/load/backup setup and execution of reviewed cases |
| 3 November | Target initial reviewed Test Case Document/RTM; continue all three owners' execution in parallel |
| 3-5 November | Functional, security, performance/recovery and quality testing; log owned defects, fix and retest affected cases; draft reports continuously |
| 6 November | Finish report reconciliation, independent review, QA/Dev/PO approvals, guide acceptance walkthrough and publication/submission checks |

Only real development spillover or newly discovered defects justify Sprint 3.
Create owned, estimated defect/spillover issues linked to the failed case and
parent execution task; record dependencies and rerun evidence. Add a Sprint 3
milestone/iteration if needed for that scope. Continue testing and report
preparation in parallel during 2-6 November. Pending report writing alone does
not establish another development sprint. Confirm the exact submission channel,
cutoff and export requirements with the instructor through the normal team process.

## Deliverable destinations and completion evidence

The following files are **planned outputs**, to be created by the assigned
contributors. They are paths until they exist; update this index with links when
each reviewed deliverable is committed. Markdown is the team's working format;
confirm whether the instructor also needs PDF/DOCX exports.

| Output under `docs/` | Owner / contributors | Required content |
|---|---|---|
| `docs/part3/Test_Case_Document.md` | Vaishnavi; all original case owners | Revision history, retained/new case IDs, priority, requirement/RTM, level/type, owner, prerequisites/data, steps, expected/actual results, status, tested commit, evidence and defects/retests |
| `docs/part3/Unit_Test_Report.md` | Vaishnavi; each module owner supplies unit results | Environment/SHA/commands, per-module unit scope and results, mixed-level suite classification, failures/skips, defects/retests and durable evidence |
| `docs/part3/System_Validation_Report.md` | Sreeharsha integrates; QA consolidates; all owners execute | Entry/exit criteria, all planned functional/security/performance/recovery/quality cases, RTM, observed results, execution/pass/fail/requirement percentages, defect density/aging, blockers, deviations, readiness and actual approvals |
| `docs/part3/Code_Coverage_Report.md` | Devansh; independent reviewer | Per-module/total measured, executed and missing statements, statement percentages, application-logic scope, omissions and SRS coverage assessment |
| `docs/part3/Branch_Coverage_Report.md` | Devansh; independent reviewer | Per-module/total measured, covered, missing and partial branches, branch percentages, gaps/exclusions and interpretation |

Keep four distinct reports. Every report names the exact tested commit/tree,
run date, tool/environment versions, data/setup, reproducible commands/steps,
results and limits. Store relevant sanitized supporting logs/metrics under
`docs/part3/evidence/`, with links from reports and the case register. Record
PASS, FAIL, BLOCKED and NOT RUN accurately. Include owned defects and rerun
results after changes. Preserve historical evidence under `test-evidence/`;
its October scope statements do not waive the submitted Test Plan for Part 3.

## Execution and acceptance checks

Existing automation is available. Use the documented MySQL environment and run
**one database suite at a time** against the disposable test database:

```sh
python scripts/run_checks.py
```

Inspect all 12 gates and the matching JUnit, `coverage.json`, `coverage.xml`,
`run.json` and `timing-smoke.txt` under `test-results/<run>/`. The runner records
a timing skip under coverage and runs that check separately without tracing.
Classify actual unit results; the complete Django suite includes integration,
concurrency and system tests. Reuse a matching verified run between unit and
coverage reports, coordinating execution rather than launching competing suites.
The `.coveragerc` gate is **70% combined statement/branch coverage**; the SRS
requires **unit tests to cover at least 70% of application logic**. Define and
review the unit-test scope in #41/#42 and measure or separately attribute its
coverage; record the target as unproven if that evidence is unavailable. The
mixed-suite percentage alone cannot establish this unit-test target. Report
statements and branches separately with scope/denominators. The Part 3 PDF specifies no separate branch
percentage threshold. Coverage alone does not establish RTM/system acceptance.

Download the final revision's Python 3.11/3.14 MySQL CI artifacts before their
30-day expiry. Save durable sanitized evidence in the repository; temporary
artifacts and links alone do not satisfy the four required reports. Record
differences from the original Test Plan environment/tools (for example MySQL 8.4
versus its 8.0 baseline) and their rationale. Use synthetic students and isolated
test resources; keep credentials, real student data, database dumps and
unredacted scan/load data private.

The assigned execution issues explicitly cover these acceptance areas:

- Security: generic credential errors, five-attempt/15-minute lockout, role and
  own-record isolation, CSRF/injection/XSS handling, audit retention/attribution,
  ZAP/deployment checks, actual TLS 1.2+ and secure session behavior.
- Performance: 50 concurrent users for 10 minutes, at least 95% of page requests
  within 2 seconds with no errors in the normal workload; 20 allocation timings under 3 seconds including save and
  concurrent-conflict correctness; 5,000 students/2,000 beds and search within
  2 seconds. Repeat the post-pagination load comparison; earlier failed/blocked
  attempts remain evidence pending a current rerun.
- Recovery: actual daily backup execution, a last-24-hour backup, populated
  restore into a separate database, completeness/consistency and at most
  24 hours of data loss. A one-off dump does not demonstrate scheduling.
- Quality: latest two Chrome/Firefox/Edge versions, Windows/Linux server
  portability, a real mobile client, a new-warden guide task within 5 minutes,
  and the at-least-99% availability target during 8 AM-8 PM on working days
  with an observation method/period and stated limits.

Test Plan section 5 requires reviewed cases, an approved SRS, a deployed test
build and loaded data before execution. Its exit criteria are: **100% of planned
cases executed, all High-priority cases passed, zero critical/high defects open,
and every RTM requirement covered by a passed case**. Missing access, failed
thresholds and unexecuted cases remain explicit blockers with owners/next steps.
Record actual QA/Dev/PO approvals and the guide acceptance walkthrough; an
unmet original criterion means not ready against the submitted Test Plan. Record
any instructor-approved requirement/criterion change separately with its
authority, date and rationale, retaining the original outcome. Failed, blocked
and not-run cases keep their actual statuses. Never infer a pass from an old issue's closed state.

The final coordination task also checks inherited Part 2 obligations: the
one-minute Sprint 1 and two-minute Sprint 2 outcome videos were not found in
tracked files at setup. Locate/publish genuine recordings or record the gap.
Keep the original documents, diagrams, historical charts and evidence intact;
record changes and confirm DOCX/PDF pairs and any final instructor packaging rules.
