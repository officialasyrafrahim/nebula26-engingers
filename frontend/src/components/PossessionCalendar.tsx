import { useEffect, useState } from "react";
import { downloadCalendar, getCalendar, listJobs, publishCalendar } from "../api/client";
import type { CalendarPossession, PossessionCalendar as Calendar, ScenarioJob } from "../api/types";
import { calendarAuthorityBadge, calendarMatches, compareCalendars, locationLabel } from "../lib/calendar";
import ExplanationsPanel from "./ExplanationsPanel";
import "../styles/calendar.css";

export default function PossessionCalendar({ runId, jobId }: { runId: string; jobId: string }) {
  const [data, setData] = useState<Calendar | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [week, setWeek] = useState(1);
  const [mapped, setMapped] = useState(false);
  const [selected, setSelected] = useState<CalendarPossession | null>(null);
  const [dates, setDates] = useState<Record<string, string>>({});
  const [jobs, setJobs] = useState<ScenarioJob[]>([]);
  const [compareId, setCompareId] = useState("");
  const [comparison, setComparison] = useState<Calendar | null>(null);
  const [compareError, setCompareError] = useState("");
  const [provisionalAck, setProvisionalAck] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setData(null); setSelected(null); setError(""); setDates({}); setProvisionalAck(false);
    getCalendar(runId, jobId).then(value => {
      if (!cancelled && calendarMatches(jobId, jobId, value) && value.run_id === runId) {
        setData(value); setWeek(Math.min(...value.events.map(e => e.week)));
      }
    }).catch(err => { if (!cancelled) setError(String(err)); });
    listJobs(runId).then(value => { if (!cancelled) setJobs(value); }).catch(() => {});
    return () => { cancelled = true; };
  }, [runId, jobId]);
  useEffect(() => {
    let cancelled = false;
    setComparison(null); setCompareError("");
    if (compareId) getCalendar(runId, compareId).then(value => {
      if (!cancelled && value.job_id === compareId) setComparison(value);
    }).catch(err => { if (!cancelled) setCompareError(String(err)); });
    return () => { cancelled = true; };
  }, [runId, compareId]);
  if (error && !data) return <div className="notice notice--danger" role="alert">Calendar unavailable: {error}</div>;
  if (!calendarMatches(jobId, jobId, data) || !data) return <p role="status">Checking persisted witness and validation…</p>;
  const visible = data.events.filter(e => e.week === week);
  const weeks = [...new Set(data.events.map(e => e.week))].sort((a,b) => a-b);
  const slots = [...new Set(data.events.map(e => `${e.week}:${e.physical_night}`))];
  const authority = calendarAuthorityBadge(data.validator_authority);
  const provisional = authority.provisional;
  const canPublish = !provisional || provisionalAck;
  const day = (offset: number) => new Date(Date.parse(data.horizon_start + "T00:00:00Z") + ((week-1)*7+offset)*86400000).toISOString().slice(0,10);
  const action = async (fn: () => Promise<void>) => {
    setBusy(true); setError("");
    try { await fn(); } catch (err) { setError(String(err)); } finally { setBusy(false); }
  };
  const card = (event: CalendarPossession) => <button key={event.possession_id} type="button"
    className={`possession-card ${event.eclo ? "possession-card--eclo" : ""}`}
    onClick={() => setSelected(event)} aria-pressed={selected?.possession_id === event.possession_id}>
    <span className="possession-card__meta">Physical night {event.physical_night} · {event.access_type.join(" + ")}</span>
    <strong>{locationLabel(event.location_ids[0], mapped)}</strong>
    <span>{event.location_ids.length} locations · {event.activity_ids.length} activities</span>
    <span>{event.activity_ids.join(" · ")}</span><span>{event.contract_numbers.join(" · ")}</span>
    <span className="calendar-chip">{event.eclo ? "ECLO · " : ""}{event.validator_status} · {event.co_share_group}</span>
  </button>;
  const diff = comparison && comparison.job_id === compareId ? compareCalendars(data, comparison) : null;
  return <section className="possession-calendar" aria-label="Validated possession calendar">
    <header className="calendar-header"><div><p className="calendar-eyebrow">OPERATIONS / SCENARIO {data.scenario}</p>
      <h2>Possession calendar</h2><p>One card per physical possession. Co-shared work stays together.</p></div>
      <div className="calendar-header__badges">
        <span className="calendar-badge">{data.status} · {data.validator_authority}</span>
        {provisional ? <span className="calendar-badge calendar-badge--provisional">{authority.label}</span> : null}
      </div></header>
    {provisional ? (
      <div className="calendar-authority-warning" role="alert">
        <strong>PROVISIONAL</strong>
        <span>{authority.warning}</span>
      </div>
    ) : null}
    <div className="calendar-stats"><div><strong>{data.events.length}</strong> possessions</div>
      <div><strong>{new Set(data.events.flatMap(e => e.activity_ids)).size}</strong> activities</div>
      <div><strong>{data.events.filter(e => e.eclo).length}</strong> ECLO possessions</div>
      <div><strong>0</strong> hard violations</div></div>
    <div className="calendar-toolbar"><label>Planning week <select value={week} onChange={e => { setWeek(Number(e.target.value)); setSelected(null); }}>
      {weeks.map(w => <option key={w} value={w}>Week {w}</option>)}</select></label>
      <strong>{day(0)} — {day(6)}</strong>
      <label><input type="checkbox" checked={mapped} onChange={e => setMapped(e.target.checked)} /> DTL/CCL demo labels</label></div>
    {data.status === "PUBLISHED" || data.status === "SUPERSEDED" ? <div className="calendar-grid">
      {Array.from({length:7}, (_,i) => <div className="calendar-day" key={i}><h3>{["Mon","Tue","Wed","Thu","Fri","Sat","Sun"][new Date(day(i)+"T00:00:00Z").getUTCDay() === 0 ? 6 : new Date(day(i)+"T00:00:00Z").getUTCDay()-1]} <small>{day(i)}</small></h3>
        {visible.filter(e => e.date === day(i)).map(card)}</div>)}</div> : <>
      <p className="calendar-note">Dates are unassigned. These are validated physical slots, not weekdays. Confirm dates below to publish.</p>
      <div className="calendar-slots">{[...new Set(visible.map(e => e.physical_night))].sort((a,b)=>a-b).map(n =>
        <div key={n}><h3>Physical night {n}</h3>{visible.filter(e => e.physical_night === n).map(card)}</div>)}</div></>}
    {selected && <aside className="calendar-evidence"><button className="btn" onClick={() => setSelected(null)}>Close possession details</button>
      <h3>{selected.activity_ids.join(" + ")} · Physical night {selected.physical_night}</h3>
      <p>{selected.nature_of_works.join(" / ")} · {selected.status} · {selected.validator_status}</p>
      <ul>{selected.location_ids.map(id => <li key={id}>{locationLabel(id, mapped)} {mapped && <code>{id}</code>}</li>)}</ul>
      <p>Contract-local access indices (not physical nights): {Object.entries(selected.local_access_nights).map(([a,n])=>`${a}: ${n}`).join(" · ")}</p>
      <p>Evidence below is inherited from Main’s activity explanations; it is not a new causal analysis.</p>
      <ExplanationsPanel explanations={selected.evidence} /></aside>}
    <details className="calendar-publish"><summary>Publication & ICS export</summary>
      <p>Version {data.schedule_version}. Export uses date-only events: operating start/end times are not in the witness.</p>
      {provisional ? (
        <label className="calendar-ack">
          <input type="checkbox" checked={provisionalAck} onChange={e=>setProvisionalAck(e.target.checked)} />
          <span>I acknowledge this calendar carries fallback (provisional) validation, not official acceptance, and I choose to publish or export it anyway.</span>
        </label>
      ) : null}
      {data.status === "VALIDATED" && <><p>Confirm each physical slot’s operating date within its planning week. Published bindings are immutable.</p>
        <div className="calendar-bindings">{slots.map(key => { const w=Number(key.split(":")[0]); const start=new Date(Date.parse(data.horizon_start+"T00:00:00Z")+(w-1)*7*86400000); return <label key={key}>Week {w} · physical night {key.split(":")[1]}
          <input type="date" value={dates[key] ?? ""} min={start.toISOString().slice(0,10)} max={new Date(+start+6*86400000).toISOString().slice(0,10)} onChange={e=>setDates({...dates,[key]:e.target.value})}/></label>; })}</div>
        {provisional ? (
          <p className="calendar-authority-warning calendar-authority-warning--inline" role="alert">Fallback validation, not official acceptance. Publishing stays disabled until the acknowledgement is ticked.</p>
        ) : null}
        <button className="btn" disabled={busy || slots.some(k=>!dates[k]) || !canPublish} onClick={()=>void action(async()=>setData(await publishCalendar(runId,jobId,dates)))}>Publish confirmed dates</button></>}
      {provisional ? (
        <p className="calendar-authority-warning calendar-authority-warning--inline" role="alert">ICS export under fallback validation is provisional and not official acceptance. Export stays disabled until the acknowledgement is ticked.</p>
      ) : null}
      <button className="btn" disabled={busy || data.status !== "PUBLISHED" || !canPublish} onClick={()=>void action(()=>downloadCalendar(runId,jobId))}>Download ICS</button>
      <p>Import the downloaded file into Outlook, Google Calendar or Apple Calendar. This does not connect or sync an account.</p></details>
    {error && <p role="alert">{error}</p>}
    <details className="calendar-compare"><summary>Compare another validated scenario</summary>
      <select aria-label="Compare job" value={compareId} onChange={e=>setCompareId(e.target.value)}><option value="">Choose a completed job</option>
        {jobs.filter(j=>j.state === "COMPLETED" && j.id !== jobId).map(j=><option key={j.id} value={j.id}>{j.scenario} · {j.id.slice(0,8)}</option>)}</select>
      {compareError && <p role="alert">{compareError}</p>}
      {diff && <><p>Compared with scenario {comparison?.scenario}. Assignment counts compare activity occurrences; grouping can change between scenarios.</p>
        <dl className="calendar-diff">{Object.entries(diff).map(([k,v])=><div key={k}><dt>{k}</dt><dd>{v}</dd></div>)}</dl>
        <p>Score differences across scenarios use different objective formulas and do not imply a direct ranking.</p></>}
    </details>
  </section>;
}
