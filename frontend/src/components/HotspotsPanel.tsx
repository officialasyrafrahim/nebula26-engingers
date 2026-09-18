import type { CapacityHotspot } from "../api/types";
import Panel from "./Panel";

interface HotspotsPanelProps {
  hotspots: CapacityHotspot[];
}

function HotspotRow({ hotspot }: { hotspot: CapacityHotspot }) {
  return (
    <tr>
      <th scope="row">
        <code>{hotspot.location_id}</code>
      </th>
      <td>W{hotspot.week}</td>
      <td>{hotspot.used}</td>
      <td>{hotspot.capacity}</td>
      <td className={hotspot.excess > 0 ? "cell--danger" : ""}>
        {hotspot.excess > 0 ? `+${hotspot.excess}` : "0"}
      </td>
    </tr>
  );
}

export default function HotspotsPanel({ hotspots }: HotspotsPanelProps) {
  const totalExcess = hotspots.reduce((sum, spot) => sum + spot.excess, 0);
  return (
    <Panel
      title="Capacity hotspots"
      eyebrow="Location-weeks under strain"
      tone={hotspots.length > 0 ? "danger" : "ok"}
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
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}
