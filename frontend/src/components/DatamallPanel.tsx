import { useEffect, useMemo, useState } from "react";

import { getDatamallContext } from "../api/client";
import type {
  CrowdDensityRecord,
  DatamallNetworkContext,
  DatamallSourceStatus,
  NetworkResponse,
  PassengerVolumeRecord,
  TrainAlertRecord,
} from "../api/types";
import {
  contextUnavailable,
  crowdLevelLabel,
  crowdLevelTone,
  datamallContextForNetwork,
  DATAMALL_ADVISORY_LABEL,
  DATAMALL_MAPPING_NOTE,
  DATAMALL_UNAVAILABLE_REASON,
} from "../lib/datamall";
import { formatDateTime, formatNumber } from "../lib/format";
import Panel from "./Panel";
import SignalLamp, { type LampTone } from "./SignalLamp";

interface DatamallPanelProps {
  network: NetworkResponse;
}

function errorMessage(caught: unknown): string {
  return caught instanceof Error ? caught.message : String(caught);
}

function sourceTone(source: DatamallSourceStatus): LampTone {
  switch (source.state) {
    case "ok":
      return "ok";
    case "error":
      return "danger";
    case "empty":
      return "info";
    default:
      return "idle";
  }
}

function sourceStatusText(source: DatamallSourceStatus): string {
  if (source.reason) return source.reason;
  return source.available ? "available" : source.state;
}

function freshness(source: DatamallSourceStatus): string {
  if (!source.retrieved_at) return "not retrieved";
  const when = formatDateTime(source.retrieved_at);
  return source.cached ? `${when} · cached` : when;
}

function DemandRow({
  record,
  max,
}: {
  record: PassengerVolumeRecord;
  max: number;
}) {
  const total = record.total_weekday ?? 0;
  const width = max > 0 ? Math.max(4, Math.round((total / max) * 100)) : 4;
  return (
    <li className="datamall__demand-row">
      <div className="datamall__demand-head">
        <span className="datamall__station">
          {record.station_name ?? record.station_code}
        </span>
        <span className="datamall__code">{record.station_code}</span>
        <span className="datamall__volume">{formatNumber(total)} trips</span>
      </div>
      <div className="datamall__bar" aria-hidden="true">
        <span className="datamall__bar-fill" style={{ width: `${width}%` }} />
      </div>
      <div className="datamall__demand-meta">
        <span>weekday tap in {formatNumber(record.tap_in_weekday)}</span>
        <span>tap out {formatNumber(record.tap_out_weekday)}</span>
      </div>
    </li>
  );
}

function CrowdChips({ records }: { records: CrowdDensityRecord[] }) {
  if (records.length === 0) {
    return <p className="empty">No crowd density returned for the mapped stations.</p>;
  }
  return (
    <ul className="datamall__chips" aria-label="Station crowd density">
      {records.map((record) => (
        <li
          key={`${record.station_code}-${record.interval_start ?? ""}`}
          className={`datamall__chip datamall__chip--${crowdLevelTone(record.crowd_level)}`}
        >
          <span className="datamall__chip-name">
            {record.station_name ?? record.station_code}
          </span>
          <span className="datamall__chip-code">{record.station_code}</span>
          <span className="datamall__chip-level">
            {crowdLevelLabel(record.crowd_level)}
          </span>
        </li>
      ))}
    </ul>
  );
}

function AlertList({ records }: { records: TrainAlertRecord[] }) {
  if (records.length === 0) {
    return (
      <p className="empty">
        No train service disruption reported for the mapped lines.
      </p>
    );
  }
  return (
    <ul className="datamall__alerts">
      {records.map((record, index) => (
        <li key={`${record.line ?? "line"}-${index}`} className="datamall__alert">
          <span className="datamall__alert-line">{record.line ?? "Unknown line"}</span>
          {record.direction ? (
            <span className="datamall__alert-meta">towards {record.direction}</span>
          ) : null}
          {record.stations.length > 0 ? (
            <span className="datamall__alert-stations">
              {record.stations.join(", ")}
            </span>
          ) : null}
          {record.message ? (
            <span className="datamall__alert-message">{record.message}</span>
          ) : null}
        </li>
      ))}
    </ul>
  );
}

export default function DatamallPanel({ network }: DatamallPanelProps) {
  const context = useMemo(() => datamallContextForNetwork(network), [network]);
  const [data, setData] = useState<DatamallNetworkContext | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!context.supported || !context.network) {
      setData(null);
      setError(null);
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    getDatamallContext(context.network)
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((caught) => {
        if (!cancelled) setError(errorMessage(caught));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [context.supported, context.network]);

  const eyebrow = "Stage 2 · Inspect · advisory context";

  if (!context.supported) {
    return (
      <Panel title="LTA DataMall context" eyebrow={eyebrow} tone="warn">
        <div className="notice notice--warn" role="status">
          <span className="notice__title">
            {DATAMALL_UNAVAILABLE_REASON}
          </span>
          <p>
            This network is not the mapped DTL/CCL demonstration network, so no
            station code is sent to LTA and no advisory context is shown.
          </p>
          {context.unmapped.length > 0 ? (
            <p className="datamall__note">
              Unmapped identifiers: {context.unmapped.join(", ")}
            </p>
          ) : null}
        </div>
        <p className="datamall__note">{DATAMALL_MAPPING_NOTE}</p>
      </Panel>
    );
  }

  const advisory = data?.advisory;
  const unavailable = data ? contextUnavailable(data) : false;
  const demand = [...(data?.passenger_volume ?? [])].sort(
    (a, b) => (b.total_weekday ?? 0) - (a.total_weekday ?? 0),
  );
  const maxDemand = demand.reduce(
    (max, record) => Math.max(max, record.total_weekday ?? 0),
    0,
  );
  const topOd = data?.od_volume ?? [];

  return (
    <Panel
      title="LTA DataMall context"
      eyebrow={eyebrow}
      tone={unavailable ? "warn" : "default"}
      actions={
        <span className="panel__meter">
          {advisory ? DATAMALL_ADVISORY_LABEL : "Advisory only"}
        </span>
      }
    >
      <div className="datamall__advisory" role="note">
        <span className="datamall__advisory-tag">{DATAMALL_ADVISORY_LABEL}</span>
        <p>
          {advisory?.disclaimer ??
            "Passenger volume and crowding are advisory context only. They never change supply, validation, scoring, feasibility or the published CSVs."}
        </p>
        <p className="datamall__note">
          {advisory?.measurement_note ??
            "DataMall provides passenger tap volumes and a coarse crowding band, not train capacity or onboard occupancy."}
        </p>
      </div>

      {loading ? (
        <p className="empty" role="status" aria-live="polite">
          Loading advisory DataMall context…
        </p>
      ) : null}

      {error && !loading ? (
        <div className="notice notice--danger" role="alert">
          <span className="notice__title">Advisory context failed to load</span>
          <p>{error}</p>
        </div>
      ) : null}

      {data && !loading && !error ? (
        <>
          <div>
            <h3 className="subhead">Source status</h3>
            <ul className="datamall__sources">
              {data.sources.map((source, index) => (
                <li key={`${source.dataset}-${index}`} className="datamall__source">
                  <SignalLamp
                    tone={sourceTone(source)}
                    size="sm"
                    label={`${source.dataset} ${source.state}`}
                  />
                  <span className="datamall__source-name">{source.source}</span>
                  <span className="datamall__source-meta">{source.dataset}</span>
                  <span className="datamall__source-meta">{freshness(source)}</span>
                  <span className="datamall__source-reason">
                    {sourceStatusText(source)}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          {unavailable ? (
            <p className="empty">
              LTA DataMall is not available for this deployment or is currently
              unreachable. The control board is unaffected; this panel is
              advisory only.
            </p>
          ) : (
            <>
              <div>
                <h3 className="subhead">
                  Passenger demand by station
                  <span className="subhead__meter">
                    {data.passenger_volume.length} mapped stations
                  </span>
                </h3>
                {demand.length > 0 ? (
                  <ul className="datamall__demand" aria-label="Passenger demand">
                    {demand.slice(0, 12).map((record) => (
                      <DemandRow
                        key={record.station_code}
                        record={record}
                        max={maxDemand}
                      />
                    ))}
                  </ul>
                ) : (
                  <p className="empty">
                    No passenger volume returned for the mapped stations.
                  </p>
                )}
              </div>

              <div>
                <h3 className="subhead">
                  Station crowd density · real time
                  <span className="subhead__meter">
                    low / moderate / high
                  </span>
                </h3>
                <CrowdChips records={data.crowd_density} />
              </div>

              <div>
                <h3 className="subhead">Top mapped origin-destination trips</h3>
                {topOd.length > 0 ? (
                  <ul className="datamall__od" aria-label="Origin destination trips">
                    {topOd.slice(0, 6).map((record) => (
                      <li
                        key={`${record.origin_code}-${record.destination_code}`}
                        className="datamall__od-row"
                      >
                        <span>
                          {record.origin_name ?? record.origin_code} →{" "}
                          {record.destination_name ?? record.destination_code}
                        </span>
                        <span className="datamall__volume">
                          {formatNumber(record.weekday_trips)} weekday trips
                        </span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="empty">No mapped origin-destination trips returned.</p>
                )}
              </div>

              <div>
                <h3 className="subhead">Train service alerts</h3>
                <AlertList records={data.alerts} />
              </div>
            </>
          )}
        </>
      ) : null}

      <p className="datamall__note">{DATAMALL_MAPPING_NOTE}</p>
    </Panel>
  );
}
