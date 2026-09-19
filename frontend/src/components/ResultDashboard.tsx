import type {
  NetworkResponse,
  ScheduleResponse,
  ValidatorReport,
} from "../api/types";
import type { ScenarioCompareEntry } from "../lib/compare";
import { capacityReadings, isAtCapacity, type ActivitySelection } from "../lib/schematic";
import ActivityTimeline from "./ActivityTimeline";
import AssurancePanel from "./AssurancePanel";
import BonusArea from "./BonusArea";
import ContractTable from "./ContractTable";
import DownloadPanel from "./DownloadPanel";
import EcloPanel from "./EcloPanel";
import ExplanationsPanel from "./ExplanationsPanel";
import HotspotsPanel from "./HotspotsPanel";
import PossessionDrawer from "./PossessionDrawer";
import ReplanPanel from "./ReplanPanel";
import ScenarioCompare from "./ScenarioCompare";
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
  compareEntries?: ScenarioCompareEntry[];
  compareLoading?: boolean;
  compareError?: string | null;
  onLoadOthers?: () => void;
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
  compareEntries = [],
  compareLoading = false,
  compareError = null,
  onLoadOthers,
}: ResultDashboardProps) {
  const selectedActivityId = selection?.activityId ?? null;

  if (section === "validate") {
    const atCapacity = capacityReadings(
      network,
      schedule.occupancy,
      schedule.scenario,
    ).filter(isAtCapacity);
    return (
      <div className="dashboard" aria-label={`Scenario ${scenario} validation dashboard`}>
        <AssurancePanel report={report} physicalChecks={schedule.physical_checks} />

        <div className="dashboard__gates">
          <ValidatorGate report={report} />
          <ScorePanel scores={report.soft_scores} scenario={scenario} />
        </div>

        <ViolationsPanel
          violations={report.hard_violations}
          authority={report.authority}
        />

        <HotspotsPanel
          hotspots={report.detail.capacity_hotspots}
          atCapacity={atCapacity}
          scenario={schedule.scenario}
          hardViolations={report.hard_violations}
        />

        <ReplanPanel
          runId={runId}
          jobId={jobId}
          scenario={scenario}
          network={network}
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

      <ScenarioCompare
        entries={compareEntries}
        loading={compareLoading}
        error={compareError}
        activeScenario={schedule.scenario}
        onLoadOthers={onLoadOthers}
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
        network={network}
        detail={report.detail}
        scenario={scenario}
      />

      <ExplanationsPanel
        explanations={schedule.explanations}
        selectedActivityId={selectedActivityId}
        onSelect={onSelect}
      />

      <BonusArea
        runId={runId}
        jobId={jobId}
        scenario={scenario}
        network={network}
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
