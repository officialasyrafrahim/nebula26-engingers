import type { NetworkResponse } from "../api/types";
import SandboxPanel from "./SandboxPanel";
import ScheduleQueryPanel from "./ScheduleQueryPanel";

interface BonusAreaProps {
  runId: string;
  jobId: string;
  scenario: string;
  network: NetworkResponse;
}

// The clearly labelled bonus area for F-BONUS-002 and F-BONUS-003. Both tools
// are advisory and exploratory. They read the completed job's persisted
// evidence and never rewrite its three published CSVs or validated result.
export default function BonusArea({
  runId,
  jobId,
  scenario,
  network,
}: BonusAreaProps) {
  return (
    <section className="bonus" aria-label="Bonus advisory tools">
      <header className="bonus__intro">
        <p className="panel__eyebrow">Bonus · advisory and exploratory</p>
        <h2 className="bonus__title">Sandbox and schedule queries</h2>
        <p className="bonus__note">
          These tools explore the completed schedule. They never change the
          source job&apos;s published CSVs or validated result. Every what-if and
          every answer is computed server-side from persisted evidence.
        </p>
      </header>

      <SandboxPanel
        runId={runId}
        jobId={jobId}
        scenario={scenario}
        network={network}
      />
      <ScheduleQueryPanel
        runId={runId}
        jobId={jobId}
        scenario={scenario}
        network={network}
      />
    </section>
  );
}
