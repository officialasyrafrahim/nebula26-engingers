import type { CapacityHotspot, HardViolation } from "../api/types";
import type { CapacityReading } from "../lib/schematic";
import Panel from "./Panel";

interface HotspotsPanelProps {
  hotspots: CapacityHotspot[];
  atCapacity?: CapacityReading[];
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
  atCapacity = [],
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

  // The validator's hotspot feed only lists location-weeks strictly above
  // supply. Exactly-at-capacity rows are projected from the published occupancy
  // and the supply table, never invented, so the board can show the last drop of
  // headroom disappearing.
  const atCapacityRows = atCapacity.filter(
    (reading) => reading.used > 0 && reading.used === reading.capacity,
  );

  const tone =
    hardCount > 0
      ? "danger"
      : hotspots.length > 0 || atCapacityRows.length > 0
        ? "warn"
        : "ok";

  return (
    <Panel
      title="Capacity hotspots"
      eyebrow="Location-weeks under strain"
      tone={tone}
      actions={
        <span className="panel__meter">
          {hotspots.length} over · {atCapacityRows.length} at capacity · excess{" "}
          {totalExcess}
        </span>
      }
    >
      {hotspots.length === 0 && atCapacityRows.length === 0 ? (
        <p className="empty empty--ok">
          No location-week reaches or exceeds its nominal supply capacity.
        </p>
      ) : null}

      {hotspots.length > 0 ? (
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
      ) : null}

      {atCapacityRows.length > 0 ? (
        <div className="hotspots__at-capacity">
          <h3 className="subhead">At capacity · no headroom left</h3>
          <ul className="hotspots__pills" aria-label="Location-weeks at supply capacity">
            {atCapacityRows.map((reading) => (
              <li
                key={`${reading.locationId}-${reading.week}`}
                className="hotspots__pill"
              >
                <code>{reading.locationId}</code>
                <span className="hotspots__pill-week">W{reading.week}</span>
                <span className="hotspots__pill-count">
                  {reading.used}/{reading.capacity}
                </span>
              </li>
            ))}
          </ul>
          <p className="hotspots__source">
            Derived from the published schedule occupancy and the supply table.
            The validator hotspot feed reports only location-weeks above supply,
            so at-capacity rows would otherwise be invisible.
          </p>
        </div>
      ) : null}

      {hotspots.length > 0 || atCapacityRows.length > 0 ? (
        <p className="hotspots__legend">
          {softCount > 0
            ? "Amber excess is soft within the scenario allowance and does not block export."
            : null}
          {softCount > 0 && hardCount > 0 ? " " : ""}
          {hardCount > 0
            ? "Red excess is a hard capacity violation and blocks submission."
            : null}
          {atCapacityRows.length > 0
            ? `${softCount > 0 || hardCount > 0 ? " " : ""}At-capacity rows use the full supply with no spare possession.`
            : null}
        </p>
      ) : null}
    </Panel>
  );
}
