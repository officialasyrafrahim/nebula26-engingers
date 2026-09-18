import type { Activity, NetworkResponse } from "../api/types";
import Panel from "./Panel";

interface NetworkSummaryProps {
  network: NetworkResponse;
}

function shortLocation(locationId: string): string {
  const parts = locationId.split(":");
  if (parts[0] === "PLAT" && parts.length >= 4) {
    return `${parts[2]}·${parts[3]}`;
  }
  if (parts[0] === "SEC" && parts.length >= 4) {
    return `${parts[2]}·${parts[3]}`;
  }
  return locationId;
}

function RouteTrack({ locationIds }: { locationIds: string[] }) {
  return (
    <ol className="track" aria-label="Expanded route locations">
      {locationIds.map((locationId, index) => (
        <li
          key={`${locationId}-${index}`}
          className={`track__stop${locationId.startsWith("PLAT:") ? " track__stop--platform" : ""}`}
          title={locationId}
        >
          {shortLocation(locationId)}
        </li>
      ))}
    </ol>
  );
}

export default function NetworkSummary({ network }: NetworkSummaryProps) {
  const activities: Activity[] = network.activities ?? [];
  const routes = network.routes ?? {};
  const routeEntries = activities
    .map((activity) => ({
      activity,
      locations: routes[activity.activity_id] ?? [],
    }))
    .sort((a, b) => b.locations.length - a.locations.length);

  const capacities = (network.locations ?? []).map(
    (location) => location.supply_capacity,
  );
  const minCapacity = capacities.length ? Math.min(...capacities) : null;
  const maxCapacity = capacities.length ? Math.max(...capacities) : null;
  const avgCapacity = capacities.length
    ? capacities.reduce((sum, value) => sum + value, 0) / capacities.length
    : null;

  const interchange = network.stations.filter((s) => s.is_interchange).length;
  const shared = network.sectors.filter((s) => s.is_shared).length;
  const totalRouteStops = routeEntries.reduce(
    (sum, entry) => sum + entry.locations.length,
    0,
  );
  const longestRoute = routeEntries[0]?.locations.length ?? 0;

  return (
    <Panel
      title="Network summary"
      eyebrow="Parsed topology · /network"
      actions={
        <span className="panel__meter">
          {Object.keys(routes).length} expanded routes
        </span>
      }
    >
      <ul className="counts counts--wide" aria-label="Network counts">
        <li className="counts__cell">
          <span className="counts__value">{network.lines.length}</span>
          <span className="counts__label">Lines</span>
        </li>
        <li className="counts__cell">
          <span className="counts__value">{network.stations.length}</span>
          <span className="counts__label">Stations · {interchange} interchange</span>
        </li>
        <li className="counts__cell">
          <span className="counts__value">{network.sectors.length}</span>
          <span className="counts__label">Sectors · {shared} shared</span>
        </li>
        <li className="counts__cell">
          <span className="counts__value">{network.locations.length}</span>
          <span className="counts__label">Locations</span>
        </li>
        <li className="counts__cell">
          <span className="counts__value">{network.buffer_rules.length}</span>
          <span className="counts__label">Buffer rules</span>
        </li>
        <li className="counts__cell">
          <span className="counts__value">{network.contracts.length}</span>
          <span className="counts__label">Contracts</span>
        </li>
        <li className="counts__cell">
          <span className="counts__value">{activities.length}</span>
          <span className="counts__label">Activities</span>
        </li>
        <li className="counts__cell">
          <span className="counts__value">
            {minCapacity ?? "—"}–{maxCapacity ?? "—"}
          </span>
          <span className="counts__label">
            Supply min–max · avg {(avgCapacity ?? 0).toFixed(1)}
          </span>
        </li>
      </ul>

      <div className="network-split">
        <div className="network-lines">
          <h3 className="subhead">Lines</h3>
          <ul className="linelist">
            {network.lines.map((line) => {
              const stations = network.stations.filter(
                (station) => station.line_code === line.line_code,
              ).length;
              const sectors = network.sectors.filter(
                (sector) => sector.line_code === line.line_code,
              ).length;
              return (
                <li key={line.line_code} className="linelist__item">
                  <span className="linelist__code">{line.line_code}</span>
                  <span className="linelist__name">{line.line_name}</span>
                  <span className="linelist__meta">
                    {stations} stations · {sectors} sectors
                  </span>
                </li>
              );
            })}
          </ul>
          <h3 className="subhead">Buffer rules</h3>
          <ul className="linelist">
            {network.buffer_rules.map((rule) => (
              <li key={rule.nature_of_works} className="linelist__item">
                <span className="linelist__name">{rule.nature_of_works}</span>
                <span className="linelist__meta">
                  ±{rule.up_to_buffer_sectors} sectors
                  {rule.opposite_bound_required ? " · opposite bound" : ""}
                </span>
              </li>
            ))}
          </ul>
        </div>

        <div className="network-routes">
          <h3 className="subhead">
            Expanded routes{" "}
            <span className="subhead__meter">
              avg {(totalRouteStops / Math.max(routeEntries.length, 1)).toFixed(1)} ·
              longest {longestRoute} stops
            </span>
          </h3>
          <div className="scroller scroller--routes">
            <ul className="routelist">
              {routeEntries.map(({ activity, locations }) => (
                <li key={activity.activity_id} className="routelist__item">
                  <div className="routelist__head">
                    <span className="routelist__id">{activity.activity_id}</span>
                    <span className="routelist__contract">
                      {activity.contract_number}
                    </span>
                    <span className="routelist__span">
                      {shortLocation(activity.start_location_id)} →{" "}
                      {shortLocation(activity.end_location_id)}
                    </span>
                  </div>
                  {locations.length > 0 ? (
                    <RouteTrack locationIds={locations} />
                  ) : (
                    <p className="routelist__empty">No expanded route</p>
                  )}
                </li>
              ))}
            </ul>
          </div>
        </div>
      </div>
    </Panel>
  );
}
