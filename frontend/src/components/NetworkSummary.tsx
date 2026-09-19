import type { Activity, NetworkResponse } from "../api/types";
import {
  lineDisplay,
  locationDisplay,
  MAPPING_NOTE,
  sectorDisplay,
  stationDisplay,
} from "../lib/networkNames";
import Panel from "./Panel";

interface NetworkSummaryProps {
  network: NetworkResponse;
}

// Presentation only. The raw location id stays the title and the source for the
// platform/sector styling; the visible text may be a real station name.
function RouteStop({ locationId }: { locationId: string }) {
  const display = locationDisplay(locationId);
  const parts = locationId.split(":");
  const bound = parts.length >= 4 ? parts[parts.length - 1] : null;
  return (
    <li
      className={`track__stop${
        locationId.startsWith("PLAT:") ? " track__stop--platform" : ""
      }${display.mapped ? "" : " track__stop--unmapped"}`}
      title={
        display.mapped
          ? `${display.text} · ${locationId}`
          : `${locationId} · no mapping available`
      }
    >
      {display.text}
      {bound ? <span className="track__stop-bound"> · {bound}</span> : null}
    </li>
  );
}

function RouteTrack({ locationIds }: { locationIds: string[] }) {
  return (
    <ol className="track" aria-label="Expanded route locations">
      {locationIds.map((locationId, index) => (
        <RouteStop key={`${locationId}-${index}`} locationId={locationId} />
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

  // Every identifier with no real-network entry. Hidden instances keep the raw
  // solver ids, and the panel says so instead of inventing a name.
  const unmappedNames = [
    ...new Set([
      ...network.stations
        .filter((station) => !stationDisplay(station.line_code, station.station_id).mapped)
        .map((station) => station.station_id),
      ...network.sectors
        .filter((sector) => !sectorDisplay(sector.line_code, sector.sector_id).mapped)
        .map((sector) => sector.sector_id),
    ]),
  ].sort();

  return (
    <Panel
      title="Network summary"
      eyebrow="Stage 2 · Inspect · parsed topology"
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
              const info = lineDisplay(line.line_code);
              return (
                <li key={line.line_code} className="linelist__item">
                  <span
                    className="linelist__code"
                    title={
                      info.mapped
                        ? `${info.text} · solver line ${line.line_code}`
                        : line.line_code
                    }
                  >
                    {info.text}
                  </span>
                  <span className="linelist__name">{info.name}</span>
                  <span className="linelist__meta">
                    {stations} stations · {sectors} sectors
                    {info.mapped ? ` · solver ${line.line_code}` : ""}
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
                    <span
                      className="routelist__span"
                      title={`${activity.start_location_id} → ${activity.end_location_id}`}
                    >
                      {locationDisplay(activity.start_location_id).text} →{" "}
                      {locationDisplay(activity.end_location_id).text}
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

      <p className="network-names__note">
        {unmappedNames.length > 0 ? (
          <>
            No real-network mapping is available for {unmappedNames.join(", ")}.
            Those labels keep the raw solver identifier.{" "}
          </>
        ) : null}
        {MAPPING_NOTE}
      </p>
    </Panel>
  );
}
