import type {
  NetworkResponse,
  ScheduleResponse,
  ValidatorReport,
} from "../api/types";
import ActivityTimeline from "./ActivityTimeline";
import ContractTable from "./ContractTable";
import DownloadPanel from "./DownloadPanel";
import EcloPanel from "./EcloPanel";
import HotspotsPanel from "./HotspotsPanel";
import ScorePanel from "./ScorePanel";
import ValidatorGate from "./ValidatorGate";
import ViolationsPanel from "./ViolationsPanel";

interface ResultDashboardProps {
  runId: string;
  jobId: string;
  scenario: string;
  schedule: ScheduleResponse;
  report: ValidatorReport;
  network: NetworkResponse;
}

export default function ResultDashboard({
  runId,
  jobId,
  scenario,
  schedule,
  report,
  network,
}: ResultDashboardProps) {
  return (
    <div className="dashboard" aria-label={`Scenario ${scenario} result dashboard`}>
      <div className="dashboard__gates">
        <ValidatorGate report={report} />
        <ScorePanel scores={report.soft_scores} scenario={scenario} />
      </div>

      <ViolationsPanel violations={report.hard_violations} />

      <HotspotsPanel hotspots={report.detail.capacity_hotspots} />

      <ContractTable
        results={schedule.results}
        contracts={network.contracts}
        scenario={scenario}
      />

      <ActivityTimeline access={schedule.access} activities={network.activities} />

      <EcloPanel
        access={schedule.access}
        activities={network.activities}
        detail={report.detail}
        scenario={scenario}
      />

      <DownloadPanel
        runId={runId}
        jobId={jobId}
        scenario={scenario}
        report={report}
      />
    </div>
  );
}
