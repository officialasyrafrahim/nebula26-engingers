import type { CapacityHotspot, HardViolation } from "../api/types";
import Panel from "./Panel";

interface HotspotsPanelProps {
  hotspots: CapacityHotspot[];
  scenario?: string;
  hardViolations?: HardViolation[];
}

type HotspotSeverity = "soft" | "hard";

// Scenario A treats supply as hard. Scenario C allows exactly one soft excess
// per location-week; beyond that it is a hard violation. Scenario B excess is
// soft and only contributes to the excess score. An explicit capacity hard
// violation always wins over the policy inference.
function hotspotSeverity(
  hotspot: CapacityHotspot,
  scenario: string | undefined,
  hardViolations: HardViolation[],
): HotspotSeverity {
  const flagged = hardViolations.some(
    (violation) =>
      violation.rule === "capacity" &&
      violation.detail.startsWith(
        `week ${hotspot.week} ${hotspot.location_id}:`,
      ),
  );
  if (flagged) return "hard";
  if (scenario === "A") return "hard";
  if (scenario === "C") return hotspot.excess > 1 ? "hard" : "soft";
  return "soft";
}

function HotspotRow({
  hotspot,
  severity,
}: {
  hotspot: CapacityHotspot;
  severity: HotspotSeverity;
}) {
  return (
    <tr>
      <th scope="row">
        <code>{hotspot.location_id}</code>
      </th>
      <td>W{hotspot.week}</td>
      <td>{hotspot.used}</td>
      <td>{hotspot.capacity}</td>
      <td className={severity === "hard" ? "cell--danger" : "cell--warn"}>
        +{hotspot.excess}
      </td>
    </tr>
  );
}

export default function HotspotsPanel({
  hotspots,
  scenario,
  hardViolations = [],
}: HotspotsPanelProps) {
  const totalExcess = hotspots.reduce((sum, spot) => sum + spot.excess, 0);
  const hardSet = new Set(
    hotspots
      .filter(
        (spot) => hotspotSeverity(spot, scenario, hardViolations) === "hard",
      )
      .map((spot) => `${spot.location_id}-${spot.week}`),
  );
  const hardCount = hardSet.size;
  const softCount = hotspots.length - hardCount;
  const tone = hardCount > 0 ? "danger" : hotspots.length > 0 ? "warn" : "ok";
  return (
    <Panel
      title="Capacity hotspots"
      eyebrow="Location-weeks under strain"
      tone={tone}
      actions={
        <span className="panel__meter">
          {hotspots.length} location{hotspots.length === 1 ? "" : "s"} · excess {totalExcess}
        </span>
      }
    >
      {hotspots.length === 0 ? (
        <p className="empty empty--ok">
          No location-week exceeds its nominal supply capacity.
        </p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <caption className="sr-only">
              Location-week capacity hotspots and excess possessions
            </caption>
            <thead>
              <tr>
                <th scope="col">Location</th>
                <th scope="col">Week</th>
                <th scope="col">Groups used</th>
                <th scope="col">Supply</th>
                <th scope="col">Excess</th>
              </tr>
            </thead>
            <tbody>
              {hotspots.map((hotspot) => (
                <HotspotRow
                  key={`${hotspot.location_id}-${hotspot.week}`}
                  hotspot={hotspot}
                  severity={
                    hardSet.has(`${hotspot.location_id}-${hotspot.week}`)
                      ? "hard"
                      : "soft"
                  }
                />
              ))}
            </tbody>
          </table>
        </div>
      )}

      {hotspots.length > 0 ? (
        <p className="hotspots__legend">
          {softCount > 0
            ? "Amber excess is soft within the scenario allowance and does not block export."
            : null}
          {softCount > 0 && hardCount > 0 ? " " : ""}
          {hardCount > 0
            ? "Red excess is a hard capacity violation and blocks submission."
            : null}
        </p>
      ) : null}
    </Panel>
  );
}
