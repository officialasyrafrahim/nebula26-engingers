import { useEffect, useMemo, useState, type CSSProperties } from "react";

import type {
  NetworkResponse,
  ScheduleResponse,
} from "../api/types";
import {
  activeActivityIds,
  buildSchematic,
  capacityStatus,
  locationCapacity,
  nightSourceLabel,
  nightSourceOf,
  nightsForWeek,
  occupancyForWeek,
  scheduledWeeks,
  spanOverlays,
  type ActivitySelection,
  type CapacityReading,
  type CoShareGrouping,
  type SchematicNode,
  type SpanLayer,
} from "../lib/schematic";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface TrackSchematicProps {
  network: NetworkResponse;
  schedule: ScheduleResponse;
  scenario: string;
  selection: ActivitySelection | null;
  onSelect: (selection: ActivitySelection) => void;
}

interface LayerState {
  possession: boolean;
  buffer: boolean;
  mirror: boolean;
  interchange: boolean;
  capacity: boolean;
}

const LAYER_LABELS: Record<keyof LayerState, string> = {
  possession: "Possession",
  buffer: "Safety buffer",
  mirror: "Opposite-bound mirror",
  interchange: "Interchange",
  capacity: "Capacity",
};

function hueFor(value: string): number {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = (hash * 31 + value.charCodeAt(index)) % 360;
  }
  return hash;
}

function SchematicCell({
  node,
  groups,
  reading,
  layers,
  spanLayers,
  spansAvailable,
  routeHighlight,
  selectedActivityId,
  week,
  night,
  onSelect,
}: {
  node: SchematicNode;
  groups: CoShareGrouping[];
  reading: CapacityReading;
  layers: LayerState;
  spanLayers: ReadonlySet<SpanLayer>;
  spansAvailable: boolean;
  routeHighlight: boolean;
  selectedActivityId: string | null;
  week: number;
  night: number | null;
  onSelect: (selection: ActivitySelection) => void;
}) {
  const possessed = groups.length > 0;
  const selected = groups.some((group) =>
    group.members.some((member) => member.activityId === selectedActivityId),
  );
  const classes = ["schematic__cell", `schematic__cell--${node.kind}`];
  if (node.isInterchange) classes.push("schematic__cell--interchange");
  if (node.isShared) classes.push("schematic__cell--shared");
  if (possessed) classes.push("schematic__cell--possessed");
  else if (routeHighlight) classes.push("schematic__cell--route");
  if (selected) classes.push("schematic__cell--selected");

  return (
    <li className={classes.join(" ")} title={node.locationId}>
      {spansAvailable && layers.buffer && spanLayers.has("buffer") ? (
        <span className="schematic__mark schematic__mark--buffer" title="Safety buffer" />
      ) : null}
      {spansAvailable && layers.mirror && spanLayers.has("mirror") ? (
        <span className="schematic__mark schematic__mark--mirror" title="Opposite-bound mirror" />
      ) : null}
      {spansAvailable && layers.interchange && spanLayers.has("interchange") ? (
        <span
          className="schematic__mark schematic__mark--interchange"
          title="Interchange closure"
        />
      ) : null}

      <span className="schematic__node-label">{node.label}</span>

      {layers.capacity && reading.used > 0 ? (
        <span
          className={`schematic__cap schematic__cap--${reading.status}`}
          title={`W${reading.week} · ${reading.used} possessions against supply ${reading.capacity}`}
        >
          {reading.used}/{reading.capacity}
        </span>
      ) : null}

      {layers.possession && possessed ? (
        <span className="schematic__possessions">
          {groups.map((group) => (
            <span
              key={group.group}
              className="possession-group"
              title={`Co-share group ${group.group}`}
            >
              {group.members.map((member) => (
                <button
                  key={member.activityId}
                  type="button"
                  className={`possession-chip${member.eclo ? " possession-chip--eclo" : ""}${
                    selectedActivityId === member.activityId
                      ? " possession-chip--selected"
                      : ""
                  }`}
                  style={{ "--chip-hue": hueFor(member.activityId) } as CSSProperties}
                  onClick={() =>
                    onSelect({ activityId: member.activityId, week, night })
                  }
                  title={`${member.activityId}${
                    member.night != null ? ` · night ${member.night}` : ""
                  }${member.eclo ? " · ECLO" : ""}`}
                >
                  {member.activityId}
                </button>
              ))}
            </span>
          ))}
        </span>
      ) : null}
    </li>
  );
}

export default function TrackSchematic({
  network,
  schedule,
  scenario,
  selection,
  onSelect,
}: TrackSchematicProps) {
  const weeks = useMemo(() => scheduledWeeks(schedule.access), [schedule.access]);
  const [week, setWeek] = useState<number | null>(null);
  const activeWeek =
    week != null && weeks.includes(week) ? week : (weeks[0] ?? 1);

  const [night, setNight] = useState<number | "all">("all");
  const nights = useMemo(
    () => nightsForWeek(schedule.access, activeWeek),
    [schedule.access, activeWeek],
  );
  const activeNight =
    night === "all" || !nights.includes(night) ? null : night;

  const [layers, setLayers] = useState<LayerState>({
    possession: true,
    buffer: true,
    mirror: true,
    interchange: true,
    capacity: true,
  });

  useEffect(() => {
    setWeek(null);
    setNight("all");
  }, [schedule.job_id]);

  const schematic = useMemo(() => buildSchematic(network), [network]);

  const groupsByLocation = useMemo(
    () =>
      occupancyForWeek(schedule.occupancy, schedule.access, activeWeek, activeNight),
    [schedule.occupancy, schedule.access, activeWeek, activeNight],
  );

  const weekGroups = useMemo(() => {
    const map = new Map<string, Set<string>>();
    for (const row of schedule.occupancy) {
      if (row.week !== activeWeek) continue;
      const set = map.get(row.location_id) ?? new Set<string>();
      set.add(row.co_share_group || "—");
      map.set(row.location_id, set);
    }
    return map;
  }, [schedule.occupancy, activeWeek]);

  const activeIds = useMemo(
    () => activeActivityIds(schedule.access, activeWeek, activeNight),
    [schedule.access, activeWeek, activeNight],
  );

  const spans = useMemo(() => spanOverlays(network, activeIds), [network, activeIds]);

  const routeLocations = useMemo(() => {
    const set = new Set<string>();
    for (const activityId of activeIds) {
      for (const locationId of network.routes?.[activityId] ?? []) {
        set.add(locationId);
      }
    }
    return set;
  }, [activeIds, network.routes]);

  const nightSource = useMemo(() => nightSourceOf(schedule.access), [schedule.access]);

  const readingFor = (node: SchematicNode): CapacityReading => {
    const used = weekGroups.get(node.locationId)?.size ?? 0;
    const capacity = locationCapacity(network, node.locationId);
    return {
      locationId: node.locationId,
      week: activeWeek,
      used,
      capacity,
      excess: Math.max(0, used - capacity),
      status: capacityStatus(used, capacity, scenario),
    };
  };

  const toggleLayer = (key: keyof LayerState) =>
    setLayers((current) => ({ ...current, [key]: !current[key] }));

  const selectedActivityId = selection?.activityId ?? null;

  return (
    <Panel
      title="Track access control board"
      eyebrow={`Scenario ${scenario} · linked schematic`}
      actions={
        <span className="panel__meter">
          W{String(activeWeek).padStart(2, "0")} ·{" "}
          {activeNight == null ? "all nights" : `night ${activeNight}`} ·{" "}
          {nightSourceLabel(nightSource)}
        </span>
      }
    >
      <div className="schematic__toolbar">
        <div className="schematic__control">
          <label htmlFor="schematic-week">Week</label>
          <select
            id="schematic-week"
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
          <label htmlFor="schematic-night">Night</label>
          <select
            id="schematic-night"
            value={night === "all" ? "all" : String(night)}
            onChange={(event) =>
              setNight(event.target.value === "all" ? "all" : Number(event.target.value))
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

        <div className="schematic__layers" role="group" aria-label="Overlay layers">
          {(Object.keys(LAYER_LABELS) as (keyof LayerState)[]).map((key) => {
            const spanLayer =
              key === "buffer" || key === "mirror" || key === "interchange";
            const disabled = spanLayer && !spans.available;
            return (
              <button
                key={key}
                type="button"
                className={`layer-toggle${layers[key] ? " layer-toggle--on" : ""}`}
                aria-pressed={layers[key]}
                disabled={disabled}
                title={
                  disabled
                    ? "Compiled spans are unavailable for this run"
                    : `Toggle ${LAYER_LABELS[key]} overlay`
                }
                onClick={() => toggleLayer(key)}
              >
                {LAYER_LABELS[key]}
              </button>
            );
          })}
        </div>
      </div>

      {nightSource === "local" ? (
        <p className="schematic__note">
          This schedule publishes no physical slot, so the night filter uses
          contract-local <code>access_night</code> indices. Night numbers are not
          comparable across contracts.
        </p>
      ) : null}

      {!spans.available ? (
        <p className="schematic__note">
          Compiled closure, opposite-bound mirror and interchange spans are not
          published for this run. Those three layers stay hidden; the board does not
          infer them in the browser.
        </p>
      ) : null}

      <div className="schematic__board">
        {schematic.map((line) => (
          <section key={line.lineCode} className="schematic__line">
            <header className="schematic__line-head">
              <span className="schematic__line-code">{line.lineCode}</span>
              <span className="schematic__line-name">{line.lineName}</span>
            </header>
            {line.bounds.map((bound) => (
              <div key={bound.bound} className="schematic__bound">
                <span className="schematic__bound-tag">{bound.bound}</span>
                <ol
                  className="schematic__track"
                  aria-label={`${line.lineCode} ${bound.bound} track`}
                >
                  {bound.nodes.map((node) => (
                    <SchematicCell
                      key={node.key}
                      node={node}
                      groups={groupsByLocation.get(node.locationId) ?? []}
                      reading={readingFor(node)}
                      layers={layers}
                      spanLayers={spans.byLocation.get(node.locationId) ?? new Set<SpanLayer>()}
                      spansAvailable={spans.available}
                      routeHighlight={routeLocations.has(node.locationId)}
                      selectedActivityId={selectedActivityId}
                      week={activeWeek}
                      night={activeNight}
                      onSelect={onSelect}
                    />
                  ))}
                </ol>
              </div>
            ))}
          </section>
        ))}
      </div>

      <div className="schematic__legend" aria-label="Overlay legend">
        <span>
          <i className="legend-swatch legend-swatch--possession" /> possession
        </span>
        <span>
          <i className="legend-swatch legend-swatch--buffer" /> safety buffer
        </span>
        <span>
          <i className="legend-swatch legend-swatch--mirror" /> opposite-bound mirror
        </span>
        <span>
          <i className="legend-swatch legend-swatch--interchange" /> interchange
        </span>
        <span className="schematic__legend-cap">
          capacity
          <SignalLamp tone="ok" size="sm" label="within supply" /> ok
          <SignalLamp tone="danger" size="sm" label="at or over hard capacity" />{" "}
          blocked
          <SignalLamp tone="warn" size="sm" label="soft excess" /> excess
          <SignalLamp tone="info" size="sm" label="elastic possession" /> elastic
        </span>
      </div>

      <p className="schematic__foot">
        {activeIds.size} activities in view · {weekGroups.size} locations occupied in
        week {activeWeek} · selected {selection?.activityId ?? "none"}
      </p>
    </Panel>
  );
}
