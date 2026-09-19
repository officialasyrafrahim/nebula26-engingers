# RAO physical possession calendar

Based on `feature/ps1-core-control-board` at commit `46abcf8`. This is an additive
implementation for that branch, not the earlier Colab runner. The solver is unchanged.

## Run the complete demo (Python 3.12+ and Node 22+)

From the repository root, in Codespaces or another environment that can load OR-Tools:

```sh
python -m pip install -e 'backend[dev,solver]'
python scripts/demo_calendar.py --demo-dates
```

The script uploads the eight small synthetic CSVs in `data/calendar-demo`, solves
A/B/C using the real solver/worker, independently validates the physical witness,
publishes explicit demo dates, exports CSV ZIPs and ICS, and parses ICS back with an
independent iCalendar library. The PC+C+C work groups into one or more possession
events per scenario, for example B and C co-share one footprint while A splits it
across physical nights.
It creates `calendar-demo-output/demo.db` and result files. Use `--output NEW_FOLDER`
when running again; it never overwrites a previous demo database.

`--demo-dates` is an explicit synthetic demonstration convention: physical slot 1
is the first day of its planning week, slot 2 the next day, etc. This is NOT inferred
from contract-local access_night and is NOT a claim about actual operating nights.
Without this flag, the script generates validated week/slot calendars and CSV only.
For another instance use `--instance data/public-instance --seconds 30`; a solve
that times out or fails assurance stops the demo instead of publishing old results.

To inspect the persisted demo in the actual UI, start two terminals at repo root:

Terminal 1 (Linux / Codespaces):
```sh
export RAO_DATABASE_URL="sqlite:///$(pwd)/calendar-demo-output/demo.db"
python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

Terminal 1 (PowerShell):
```powershell
$env:RAO_DATABASE_URL = "sqlite:///" + (Join-Path (Get-Location) 'calendar-demo-output/demo.db').Replace('\', '/')
python -m uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000
```

Terminal 2:
```sh
cd frontend
npm ci
npm run dev -- --host 0.0.0.0
```

Open port 5173 (the Codespaces Ports tab can open it). Choose the saved run, open
Optimise and inspect A, B or C, then select the Calendar tab. Choose a week, click a
possession card for Main's evidence, and use Publication & ICS export. CSV export
remains in the Export stage. The DTL/CCL checkbox is an opt-in presentation alias;
raw location IDs remain in event details and ICS. Unknown IDs display unchanged.

## Publication and API contract

The existing API uses separate run and job identifiers. Calendar routes extend it:

- `GET /api/v1/runs/{run_id}/jobs/{job_id}/calendar`
- `GET /api/v1/runs/{run_id}/jobs/{job_id}/calendar/events` (same versioned envelope)
- `POST /api/v1/runs/{run_id}/jobs/{job_id}/calendar/publish`
- `GET /api/v1/runs/{run_id}/jobs/{job_id}/calendar/ics`

Publication body: `{"date_bindings":{"1:1":"2027-01-04","1:2":"2027-01-05"}}`.
Keys are `week:physical_night`. Supply exactly the used slots, distinct dates for
distinct slots, and dates within the corresponding seven-day planning week.
The UI provides date inputs; it does not decide or optimise dates.

Read requests recheck persisted job completion, stored validator acceptance, full
workload, and a fresh independent physical witness and fallback validation. An
unknown, timed-out, failed, incomplete or missing-witness job returns 409. The
response retains validator authority (`fallback` is never labelled `official`).

Calendar events group occupancy by week, physical slot and co-share group, then
join footprints connected by common activities. Reused group labels at disconnected
locations do not merge. PC+C+C at one footprint is one event. A multi-location
possession retains every occupied location. Local access indices are separate data.

An unpublished, assured view has a deterministic VALIDATED version ID. Publishing
stores an immutable snapshot in the additive `calendar_versions` table, with audited
DRAFT → VALIDATED → PUBLISHED transitions. A later publication supersedes the prior
version only for the same run and scenario. Superseded versions can be inspected
but cannot be exported or republished. A modified source/witness cannot reuse its
published version; it needs a new solve/job. The unique publication index also
protects concurrent publishing. Existing databases get the new table at startup.

ICS uses one VEVENT per stored projected possession, stable UID
`schedule_version.possession_id@rao`, UTF-8 octet folding, CRLF, escaped text,
exclusive DTEND, and deterministic DTSTAMP. Events are explicitly date-only with
TRANSP:TRANSPARENT because Main does not provide operating hours or a timezone.
They are not authoritative timed track-access bookings.

## Acceptance walkthrough

1. Run the demo or upload your own PS1 files and solve from the UI.
2. Confirm workload, physical witness and validator gates are green.
3. Inspect Calendar; PC+C+C should be one card with three member activities.
4. Confirm operating dates and publish; download CSV ZIP and ICS.
5. Import ICS into a separate test calendar in Outlook/Google Calendar/Apple Calendar.
6. Compare each imported UID with the JSON event's version and possession ID.
7. Switch to another job, including a failed/timed-out job: the old calendar disappears.

The automated demo verifies the file round-trip and exact UID/event correspondence.
An actual import into an external calendar account is a manual acceptance step and
has not been performed here. No account credentials, OAuth or external sync is used.

## Scope and follow-up

Milestone 1: integrated possession view, assurance gate and selected-job isolation.
Milestone 2: versioned publication, date-only ICS, optional DTL/CCL aliases and a
scenario comparison summary (assignment movement, extra access, ECLO, delays, score).
Possession movement matches an identical member/location/access-type footprint across
physical slots. A changed footprint is counted as removed/added, not guessed to be
the same possession. Activity occurrence differences are reported separately.
Scores from different scenarios have different formulas and are not directly ranked.
Milestone 3 remains future work: authoritative replanning diffs, provider publishing,
sync conflict resolution and external cancellation messages. Reimported files may be
handled differently by providers; stable UIDs are not a promise of automatic sync.
Calendar edits must become requests for a new solve/witness/validation/version.

The original branch still uses development authentication. This demo does not
turn it into a production identity or external publishing service.

## Tests

```sh
cd backend
python -m pytest -q
python -m ruff check app/modules/calendar tests/test_calendar.py
cd ../frontend
npm test
npm run build
```

New regression coverage checks co-share grouping, disconnected footprints, failed
states, unknown status, missing witnesses, stale green reports, missing workload,
cross-run access, date bindings, immutable versions, scenario-specific supersession,
RFC 5545 parsing/UTF-8 folding, selected-job guards and presentation fallbacks.

Validation performed in this handoff: full backend suite 224 passed, followed by
the expanded 15-test calendar suite including three additional version tests (227
distinct backend tests covered); frontend 10 tests and production build passed.
The real synthetic A/B/C demo completed, exported CSV/ICS and verified UIDs by parsing
the exported ICS. Browser visual verification was attempted but Chromium could not
be downloaded in this environment. External calendar-account import remains manual.
