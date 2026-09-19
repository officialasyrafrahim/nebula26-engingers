"""Real solver -> persisted witness -> validator -> calendar -> CSV/ICS demo.

Run from the repository root after installing backend[dev,solver]. The default
small synthetic instance intentionally places PC+C+C work on one footprint.
"""
import argparse
import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instance", type=Path, default=ROOT / "data/calendar-demo")
    parser.add_argument("--output", type=Path, default=ROOT / "calendar-demo-output")
    parser.add_argument("--seconds", type=int, default=5)
    parser.add_argument("--demo-dates", action="store_true",
                        help="Explicitly map physical slots 1..7 to week-start + 0..6 days for this synthetic demo.")
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    os.environ["RAO_DATABASE_URL"] = "sqlite:///" + str(out / "demo.db")
    os.environ["RAO_START_INPROCESS_WORKER"] = "false"
    os.environ["RAO_QUEUE_BACKEND"] = "memory"
    from app.main import create_app
    from app.workers.rail_solver_worker import process_next_job
    from fastapi.testclient import TestClient
    from icalendar import Calendar

    def require(response):
        if response.status_code >= 400:
            raise RuntimeError(f"{response.status_code}: {response.text}")
        return response

    with TestClient(create_app()) as client:
        files = [("files", (p.name, p.read_bytes(), "text/csv"))
                 for p in sorted(args.instance.glob("*.csv"))]
        run = require(client.post("/api/v1/runs", files=files)).json()
        results = []
        for scenario in "ABC":
            job = require(client.post(f'/api/v1/runs/{run["id"]}/jobs', json={
                "scenario": scenario, "time_limit_seconds": args.seconds,
            })).json()
            print(f"Solving {scenario}…", flush=True)
            process_next_job(timeout=0)
            base = f'/api/v1/runs/{run["id"]}/jobs/{job["id"]}'
            state = require(client.get(base)).json()
            if state["state"] != "COMPLETED":
                raise RuntimeError(f"Job did not complete: {state}")
            calendar = require(client.get(base + "/calendar")).json()
            if args.demo_dates:
                bindings = {}
                start = date.fromisoformat(calendar["horizon_start"])
                for event in calendar["events"]:
                    if not 1 <= event["physical_night"] <= 7:
                        raise RuntimeError("Physical slots exceed seven: explicit operational dates required.")
                    key = f'{event["week"]}:{event["physical_night"]}'
                    bindings[key] = str(start + timedelta(
                        weeks=event["week"] - 1, days=event["physical_night"] - 1))
                calendar = require(client.post(base + "/calendar/publish", json={
                    "date_bindings": bindings,
                })).json()
                raw = require(client.get(base + "/calendar/ics")).content
                parsed = Calendar.from_ical(raw).walk("VEVENT")
                expected = {f'{calendar["schedule_version"]}.{e["possession_id"]}@rao'
                            for e in calendar["events"]}
                assert len(parsed) == len(expected)
                assert {str(e["UID"]) for e in parsed} == expected
                (out / f"scenario-{scenario}.ics").write_bytes(raw)
            (out / f"scenario-{scenario}.zip").write_bytes(require(client.get(base + "/export")).content)
            (out / f"calendar-{scenario}.json").write_text(json.dumps(calendar, indent=2))
            row = {"scenario": scenario, "job_id": job["id"],
                   "possessions": len(calendar["events"]), "status": calendar["status"]}
            results.append(row)
            print(row, flush=True)
        (out / "SUMMARY.json").write_text(json.dumps({"run_id": run["id"], "jobs": results}, indent=2))
    print(f"Outputs and persisted database: {out}")
    print("To inspect this run in the UI, start the backend with RAO_DATABASE_URL="
          + os.environ["RAO_DATABASE_URL"])


if __name__ == "__main__":
    main()
