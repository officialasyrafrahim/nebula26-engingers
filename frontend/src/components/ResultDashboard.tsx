import type {
  NetworkResponse,
  ScheduleResponse,
  ValidatorReport,
} from "../api/types";
import type { ActivitySelection } from "../lib/schematic";
import ActivityTimeline from "./ActivityTimeline";
import AssurancePanel from "./AssurancePanel";
import ContractTable from "./ContractTable";
import DownloadPanel from "./DownloadPanel";
import EcloPanel from "./EcloPanel";
import ExplanationsPanel from "./ExplanationsPanel";
import HotspotsPanel from "./HotspotsPanel";
import PossessionDrawer from "./PossessionDrawer";
import ScorePanel from "./ScorePanel";
import TrackSchematic from "./TrackSchematic";
import ValidatorGate from "./ValidatorGate";
import ViolationsPanel from "./ViolationsPanel";

interface ResultDashboardProps {
  section: "validate" | "explain" | "export";
  runId: string;
  jobId: string;
  scenario: string;
  schedule: ScheduleResponse;
  report: ValidatorReport;
  network: NetworkResponse;
  selection: ActivitySelection | null;
  onSelect: (selection: ActivitySelection) => void;
  onClearSelection: () => void;
}

export default function ResultDashboard({
  section,
  runId,
  jobId,
  scenario,
  schedule,
  report,
  network,
  selection,
  onSelect,
  onClearSelection,
}: ResultDashboardProps) {
  const selectedActivityId = selection?.activityId ?? null;

  if (section === "validate") {
    return (
      <div className="dashboard" aria-label={`Scenario ${scenario} validation dashboard`}>
        <AssurancePanel report={report} physicalChecks={schedule.physical_checks} />

        <div className="dashboard__gates">
          <ValidatorGate report={report} />
          <ScorePanel scores={report.soft_scores} scenario={scenario} />
        </div>

        <ViolationsPanel violations={report.hard_violations} />

        <HotspotsPanel
          hotspots={report.detail.capacity_hotspots}
          scenario={schedule.scenario}
          hardViolations={report.hard_violations}
        />
      </div>
    );
  }

  if (section === "export") {
    return (
      <div className="dashboard" aria-label={`Scenario ${scenario} export`}>
        <DownloadPanel
          runId={runId}
          jobId={jobId}
          scenario={scenario}
          report={report}
        />
      </div>
    );
  }

  return (
    <div className="dashboard" aria-label={`Scenario ${scenario} schedule evidence`}>
      <ContractTable
        results={schedule.results}
        contracts={network.contracts}
        scenario={scenario}
      />

      <TrackSchematic
        network={network}
        schedule={schedule}
        scenario={scenario}
        selection={selection}
        onSelect={onSelect}
      />

      <ActivityTimeline
        access={schedule.access}
        activities={network.activities}
        occupancy={schedule.occupancy}
        selectedActivityId={selectedActivityId}
        onSelect={onSelect}
      />

      <EcloPanel
        access={schedule.access}
        activities={network.activities}
        detail={report.detail}
        scenario={scenario}
      />

      <ExplanationsPanel
        explanations={schedule.explanations}
        selectedActivityId={selectedActivityId}
        onSelect={onSelect}
      />

      {selection ? (
        <PossessionDrawer
          selection={selection}
          network={network}
          schedule={schedule}
          scenario={scenario}
          onClose={onClearSelection}
          onSelect={onSelect}
        />
      ) : null}
    </div>
  );
}
