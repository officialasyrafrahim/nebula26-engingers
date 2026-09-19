import { useEffect, useMemo, useState } from "react";

import type { NetworkResponse, ScheduleResponse } from "../api/types";
import { formatNumber } from "../lib/format";
import {
  activeActivityIds,
  nightSourceLabel,
  nightsForWeek,
  scheduledWeeks,
  type ActivitySelection,
} from "../lib/schematic";
import {
  attentionLabel,
  tonightSummary,
  type AttentionKind,
  type TonightHandback,
} from "../lib/tonight";
import Panel from "./Panel";
import PossessionDrawer from "./PossessionDrawer";
import SignalLamp, { type LampTone } from "./SignalLamp";

interface TonightPanelProps {
  network: NetworkResponse;
  schedule: ScheduleResponse;
  scenario: string;
  selection: ActivitySelection | null;
  onSelect: (selection: ActivitySelection) => void;
  onClearSelection: () => void;
  onExit: () => void;
}

const ATTENTION_TONES: Record<AttentionKind, LampTone> = {
  buffer: "warn",
  mirror: "warn",
  interchange: "info",
  capacity: "danger",
};

function HandbackList({
  items,
  empty,
  label,
}: {
  items: TonightHandback[];
  empty: string;
  label: string;
}) {
  return (
    <section className="tonight__handback" aria-label={label}>
      <h3 className="subhead">{label}</h3>
      {items.length === 0 ? (
        <p className="empty">{empty}</p>
      ) : (
        <ul className="tonight__handback-list">
          {items.map((item) => (
            <li key={item.activityId} className="tonight__handback-item">
              <code>{item.activityId}</code>
              <span className="tonight__handback-contract">
                {item.contractNumber}
              </span>
              <span className="tonight__handback-week">
                W{item.week}
                {item.night != null ? ` · n${item.night}` : ""}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export default function TonightPanel({
  network,
  schedule,
  scenario,
  selection,
  onSelect,
  onClearSelection,
  onExit,
}: TonightPanelProps) {
  const weeks = useMemo(() => scheduledWeeks(schedule.access), [schedule.access]);
  const [week, setWeek] = useState<number | null>(null);
  const activeWeek =
    week != null && weeks.includes(week) ? week : (weeks[0] ?? 1);

  const [night, setNight] = useState<number | "all">("all");
  const nights = useMemo(
    () => nightsForWeek(schedule.access, activeWeek),
    [schedule.access, activeWeek],
  );
  const activeNight = night === "all" || !nights.includes(night) ? null : night;

  useEffect(() => {
    setWeek(null);
    setNight("all");
  }, [schedule.job_id]);

  // Selections from the schematic, timeline or drawer carry a week and often a
  // night. Tonight mode follows them so the handover view and the linked
  // evidence never describe different work.
  useEffect(() => {
    if (!selection) return;
    if (selection.week != null) setWeek(selection.week);
    if (selection.night != null && selection.week != null) {
      const validNights = nightsForWeek(schedule.access, selection.week);
      setNight(validNights.includes(selection.night) ? selection.night : "all");
    }
  }, [selection?.activityId, selection?.week, selection?.night, schedule.access]);

  const summary = useMemo(
    () => tonightSummary(network, schedule, activeWeek, activeNight, scenario),
    [network, schedule, activeWeek, activeNight, scenario],
  );

  const activeCount = useMemo(
    () => activeActivityIds(schedule.access, activeWeek, activeNight).size,
    [schedule.access, activeWeek, activeNight],
  );

  const selectedActivityId = selection?.activityId ?? null;

  return (
    <div className="tonight" aria-label="Tonight controller mode">
      <div className="tonight__bar">
        <div className="tonight__bar-heading">
          <p className="tonight__eyebrow">Tonight controller mode</p>
          <h2>
            Shift handover · {summary.workfronts.length} contracts ·{" "}
            {formatNumber(activeCount)} workfronts in view
          </h2>
          <p className="tonight__sub">
            Planning chrome is hidden. This view reads the persisted schedule
            only.
          </p>
        </div>
        <div className="tonight__bar-controls">
          <div className="schematic__control">
            <label htmlFor="tonight-week">Week</label>
            <select
              id="tonight-week"
              value={activeWeek}
              onChange={(event) => {
                setWeek(Number(event.target.value));
                setNight("all");
              }}
            >
              {weeks.map((value) => (
                <option key={value} value={value}>
                  Week {value}
                </option>
              ))}
            </select>
          </div>
          <div className="schematic__control">
            <label htmlFor="tonight-night">Night</label>
            <select
              id="tonight-night"
              value={activeNight == null ? "all" : String(activeNight)}
              onChange={(event) =>
                setNight(
                  event.target.value === "all" ? "all" : Number(event.target.value),
                )
              }
            >
              <option value="all">All nights</option>
              {nights.map((value) => (
                <option key={value} value={value}>
                  Night {value}
                </option>
              ))}
            </select>
          </div>
          <button type="button" className="btn btn--ghost" onClick={onExit}>
            Exit tonight mode
          </button>
        </div>
      </div>

      <p className="schematic__note">
        Night numbers use {nightSourceLabel(summary.nightSource)}. The slot is an
        internal planning fact, not evidence of live personnel presence on site.
      </p>

      <Panel
        title="Workfronts active"
        eyebrow={`Week ${activeWeek}${
          activeNight == null ? " · all nights" : ` · night ${activeNight}`
        }`}
        actions={
          <span className="panel__meter">
            {summary.workfronts.length} contracts · {formatNumber(activeCount)} workfronts
          </span>
        }
      >
        {summary.workfronts.length === 0 ? (
          <p className="empty">No workfront is placed in this selection.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <caption className="sr-only">
                Contracts and activities placed in the selected week and night
              </caption>
              <thead>
                <tr>
                  <th scope="col">Contract</th>
                  <th scope="col">Description</th>
                  <th scope="col">Access</th>
                  <th scope="col">Workfronts</th>
                  <th scope="col">Activities</th>
                </tr>
              </thead>
              <tbody>
                {summary.workfronts.map((workfront) => (
                  <tr key={workfront.contractNumber}>
                    <th scope="row">
                      <code>{workfront.contractNumber}</code>
                    </th>
                    <td className="cell--wrap">
                      {workfront.contractDescription}
                      <span className="cell__sub">{workfront.nature}</span>
                    </td>
                    <td>{workfront.accessType}</td>
                    <td>
                      {workfront.activityIds.length}/
                      {workfront.concurrentWorkfronts}
                    </td>
                    <td>
                      <span className="tonight__activities">
                        {workfront.activityIds.map((activityId) => (
                          <button
                            key={activityId}
                            type="button"
                            className={`tonight__activity${
                              selectedActivityId === activityId
                                ? " tonight__activity--selected"
                                : ""
                            }`}
                            onClick={() =>
                              onSelect({
                                activityId,
                                week: activeWeek,
                                night: activeNight,
                              })
                            }
                          >
                            {activityId}
                          </button>
                        ))}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Panel>

      <Panel
        title="Attention items"
        eyebrow="Buffers · mirror · interchange · capacity"
        tone={summary.attention.length > 0 ? "warn" : "ok"}
        actions={
          <span className="panel__meter">
            {summary.attention.length} item
            {summary.attention.length === 1 ? "" : "s"}
          </span>
        }
      >
        {summary.attention.length === 0 ? (
          <p className="empty empty--ok">
            No buffer, mirror, interchange or capacity attention recorded for this
            selection.
          </p>
        ) : (
          <ul className="tonight__attention" aria-label="Attention items">
            {summary.attention.map((item) => (
              <li
                key={`${item.kind}-${item.locationId}`}
                className="tonight__attention-item"
              >
                <SignalLamp
                  tone={ATTENTION_TONES[item.kind]}
                  size="sm"
                  label={attentionLabel(item.kind)}
                />
                <span className="tonight__attention-kind">
                  {attentionLabel(item.kind)}
                </span>
                <code
                  className={`tonight__attention-loc${
                    item.mapped ? "" : " tonight__attention-loc--raw"
                  }`}
                  title={
                    item.mapped
                      ? `${item.label} · ${item.locationId}`
                      : `${item.locationId} · no mapping available`
                  }
                >
                  {item.label}
                </code>
                <span className="tonight__attention-detail">{item.detail}</span>
                {item.activityIds.length > 0 ? (
                  <span className="tonight__attention-acts">
                    {item.activityIds.map((activityId) => (
                      <button
                        key={activityId}
                        type="button"
                        className="tonight__activity"
                        onClick={() =>
                          onSelect({
                            activityId,
                            week: activeWeek,
                            night: activeNight,
                          })
                        }
                      >
                        {activityId}
                      </button>
                    ))}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel
        title="Next handbacks"
        eyebrow="What finishes and what starts next"
        className="tonight__handbacks-panel"
      >
        <div className="tonight__handbacks">
          <HandbackList
            label="Finishing this week"
            empty="No activity places its last access in this week."
            items={summary.finishing}
          />
          <HandbackList
            label="Starting next week"
            empty="No activity places its first access in the following week."
            items={summary.startingNext}
          />
        </div>
      </Panel>

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
