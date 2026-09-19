import { useEffect, useMemo, useState } from "react";

import { ApiError, querySchedule } from "../api/client";
import type { NetworkResponse, ScheduleQueryResponse } from "../api/types";
import {
  buildQueryExamples,
  classifyQueryResponse,
  parseLocalQuery,
  MAX_QUERY_LENGTH,
  projectCitations,
  projectEvidence,
  queryOutcomeLabel,
  queryOutcomeTone,
  QUERY_GRAMMAR_HELP,
} from "../lib/scheduleQuery";
import Panel from "./Panel";
import SignalLamp from "./SignalLamp";

interface ScheduleQueryPanelProps {
  runId: string;
  jobId: string;
  scenario: string;
  network: NetworkResponse;
}

const KIND_LABELS: Record<string, string> = {
  why_moved: "Why moved",
  downstream_risk: "Downstream risk",
  capacity_check: "Capacity check",
  milestone_brief: "Milestone brief",
};

function errorMessage(caught: unknown): string {
  return caught instanceof ApiError
    ? caught.message
    : caught instanceof Error
      ? caught.message
      : String(caught);
}

function sortedUnique(values: string[]): string[] {
  return [...new Set(values)].sort((a, b) => a.localeCompare(b));
}

function QueryAnswer({
  result,
  scenario,
}: {
  result: ScheduleQueryResponse;
  scenario: string;
}) {
  const citations = projectCitations(result.citations);
  const evidence = projectEvidence(result.evidence);
  const tone = queryOutcomeTone(classifyQueryResponse(result, false, false));

  return (
    <div className="query__result">
      <div
        className={`notice notice--${tone === "ok" ? "ok" : "warn"}`}
        role="status"
        aria-live="polite"
      >
        <span className="notice__title">
          <SignalLamp
            tone={tone}
            size="sm"
            label={result.answerable ? "Answerable" : "Unanswerable"}
          />
          <span>
            {" "}
            {result.answerable ? "Answered" : "Unanswerable"} ·{" "}
            {KIND_LABELS[result.kind] ?? result.kind} · scenario {scenario}
          </span>
        </span>
        <p className="query__answer">{result.answer}</p>
        {!result.answerable ? (
          <p className="query__caveat">
            The layer will not guess. A missing activity, contract or location is
            reported as unanswerable rather than invented.
          </p>
        ) : null}
      </div>

      {evidence.length > 0 ? (
        <div className="query__section">
          <h3 className="subhead">
            Evidence
            <span className="subhead__meter">{evidence.length} facts</span>
          </h3>
          <dl className="query__facts">
            {evidence.map((field) => (
              <div key={field.key}>
                <dt>{field.key}</dt>
                <dd>{field.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : null}

      <div className="query__section">
        <h3 className="subhead">
          Citations
          <span className="subhead__meter">
            {citations.length} persisted {citations.length === 1 ? "row" : "rows"}
          </span>
        </h3>
        {citations.length === 0 ? (
          <p className="empty">
            No citations. An unanswerable query is grounded in nothing.
          </p>
        ) : (
          <ul className="query__citations">
            {citations.map((citation, index) => (
              <li key={`${citation.source}-${index}`} className="query__citation">
                <code className="query__citation-source">{citation.source}</code>
                <dl className="query__citation-fields">
                  {citation.fields.map((field) => (
                    <div key={field.key}>
                      <dt>{field.key}</dt>
                      <dd>{field.value}</dd>
                    </div>
                  ))}
                </dl>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default function ScheduleQueryPanel({
  runId,
  jobId,
  scenario,
  network,
}: ScheduleQueryPanelProps) {
  const [text, setText] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<ScheduleQueryResponse | null>(null);
  const [rejected, setRejected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  // A different job has different persisted evidence and vocabulary.
  useEffect(() => {
    setText("");
    setResult(null);
    setRejected(false);
    setError(null);
    setFormError(null);
  }, [runId, jobId]);

  const examples = useMemo(() => {
    const weeks: number[] = [];
    const horizon = network.parameters?.horizon_weeks;
    if (typeof horizon === "number" && horizon >= 1) {
      weeks.push(1);
      if (horizon >= 2) weeks.push(2);
    } else {
      weeks.push(1);
    }
    return buildQueryExamples({
      activities: sortedUnique(
        network.activities.map((activity) => activity.activity_id),
      ),
      contracts: sortedUnique(
        network.contracts.map((contract) => contract.contract_number),
      ),
      locations: sortedUnique([
        ...network.locations.map((location) => location.location_id),
        ...Object.keys(network.location_capacities ?? {}),
      ]),
      weeks,
    });
  }, [network]);

  const submit = async () => {
    const parsed = parseLocalQuery(text);
    setFormError(null);
    setError(null);
    setRejected(false);
    if (!parsed.ok) {
      setFormError(parsed.error);
      setResult(null);
      return;
    }
    setSubmitting(true);
    try {
      const read = await querySchedule(runId, jobId, {
        query: parsed.normalized,
      });
      setResult(read);
    } catch (caught) {
      setResult(null);
      if (caught instanceof ApiError && caught.status === 422) {
        setRejected(true);
        setError(caught.message);
      } else {
        setRejected(false);
        setError(errorMessage(caught));
      }
    } finally {
      setSubmitting(false);
    }
  };

  const outcome = classifyQueryResponse(result, rejected, Boolean(error) && !rejected);
  const tone = queryOutcomeTone(outcome);

  return (
    <Panel
      title="Schedule query"
      eyebrow={`Bonus · F-BONUS-003 · scenario ${scenario}`}
      tone={tone === "ok" ? "ok" : tone === "warn" ? "warn" : tone === "danger" ? "danger" : "default"}
      actions={
        <span className="panel__meter">
          {queryOutcomeLabel(outcome)} · deterministic
        </span>
      }
    >
      <p className="replan__intro">
        Ask one question in the closed grammar. The server answers from persisted
        schedule evidence with citations, never from a language model and never
        from the network. An unsupported shape is rejected; a shape without
        evidence is reported unanswerable rather than guessed.
      </p>

      <ul className="query__examples" aria-label="Example queries">
        {examples.map((example) => (
          <li key={example.query}>
            <button
              type="button"
              className="btn btn--tiny btn--ghost"
              disabled={submitting}
              title={example.label}
              onClick={() => {
                setText(example.query);
                setFormError(null);
              }}
            >
              <code>{example.query}</code>
            </button>
          </li>
        ))}
      </ul>

      <form
        className="query__form"
        onSubmit={(event) => {
          event.preventDefault();
          void submit();
        }}
      >
        <label className="field query__field">
          <span className="field__label">Query</span>
          <input
            type="text"
            value={text}
            maxLength={MAX_QUERY_LENGTH}
            placeholder="capacity SEC:ALP:S01_S02:EB week 1"
            disabled={submitting}
            onChange={(event) => {
              setText(event.target.value);
              setFormError(null);
            }}
          />
        </label>
        <button type="submit" className="btn btn--primary" disabled={submitting}>
          {submitting ? "Answering…" : "Ask"}
        </button>
      </form>

      <p className="panel__hint query__help">{QUERY_GRAMMAR_HELP}</p>

      {formError ? (
        <div className="notice notice--danger" role="alert">
          <span className="notice__title">Query rejected</span>
          <p>{formError}</p>
        </div>
      ) : null}

      {rejected && error ? (
        <div className="notice notice--danger" role="alert">
          <span className="notice__title">Query rejected by the server</span>
          <p>{error}</p>
          <p className="query__caveat">
            Unsupported shapes return HTTP 422. The grammar is fixed, so rephrase
            within the supported forms above.
          </p>
        </div>
      ) : null}

      {error && !rejected ? (
        <div className="notice notice--danger" role="alert">
          <span className="notice__title">Query failed</span>
          <p>{error}</p>
        </div>
      ) : null}

      {submitting ? (
        <p className="empty" role="status" aria-live="polite">
          Reading persisted evidence…
        </p>
      ) : null}

      {!submitting && !result && !error && !formError ? (
        <p className="empty" role="status" aria-live="polite">
          Pick an example or type a query to see the grounded answer and its
          citations.
        </p>
      ) : null}

      {result ? <QueryAnswer result={result} scenario={scenario} /> : null}
    </Panel>
  );
}
