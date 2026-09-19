import assert from "node:assert/strict";
import { describe, it } from "node:test";

import {
  buildQueryExamples,
  classifyQueryResponse,
  formatEvidenceValue,
  normalizeQuery,
  parseLocalQuery,
  projectCitations,
  projectEvidence,
  queryOutcomeLabel,
  queryOutcomeTone,
  QUERY_GRAMMAR_HELP,
  MAX_QUERY_LENGTH,
} from "../src/lib/scheduleQuery.ts";

describe("normalizeQuery", () => {
  it("collapses whitespace", () => {
    assert.equal(normalizeQuery("  why \t A1  "), "why A1");
    assert.equal(normalizeQuery(""), "");
  });
});

describe("parseLocalQuery", () => {
  it("parses every supported form and alias", () => {
    const why = parseLocalQuery("why A1");
    assert.equal(why.ok, true);
    assert.equal(why.kind, "why_moved");
    assert.equal(why.id, "A1");

    assert.equal(parseLocalQuery("WHY A1").kind, "why_moved");
    assert.equal(parseLocalQuery("downstream A1").kind, "downstream_risk");

    const capacity = parseLocalQuery("capacity SEC:ALP:S01_S02:EB week 3");
    assert.equal(capacity.kind, "capacity_check");
    assert.equal(capacity.id, "SEC:ALP:S01_S02:EB");
    assert.equal(capacity.week, 3);

    assert.equal(
      parseLocalQuery("co-share SEC:ALP:S01_S02:EB week 1").kind,
      "capacity_check",
    );
    assert.equal(parseLocalQuery("milestone C1").kind, "milestone_brief");
    assert.equal(parseLocalQuery("handover C1").kind, "milestone_brief");
  });

  it("normalizes before matching", () => {
    const parsed = parseLocalQuery("  why    A1  ");
    assert.equal(parsed.ok, true);
    assert.equal(parsed.normalized, "why A1");
  });

  it("rejects an empty query with the grammar help", () => {
    const parsed = parseLocalQuery("   ");
    assert.equal(parsed.ok, false);
    assert.match(parsed.error ?? "", /Empty query/);
    assert.match(parsed.error ?? "", /why/);
  });

  it("rejects an over-long query", () => {
    const parsed = parseLocalQuery(`why ${"A".repeat(MAX_QUERY_LENGTH)}`);
    assert.equal(parsed.ok, false);
    assert.match(parsed.error ?? "", /exceeds/);
  });

  it("rejects malformed and unsupported shapes", () => {
    for (const text of [
      "why",
      "why A1 A2",
      "capacity SEC:A",
      "milestone",
      "drop table schedule",
      "explain why A1 moved",
    ]) {
      const parsed = parseLocalQuery(text);
      assert.equal(parsed.ok, false, `expected ${text} to be rejected`);
      assert.ok(parsed.error);
    }
  });

  it("rejects a zero week with a specific message", () => {
    const parsed = parseLocalQuery("capacity SEC:A week 0");
    assert.equal(parsed.ok, false);
    assert.equal(parsed.kind, "capacity_check");
    assert.match(parsed.error ?? "", /positive integer/);
  });

  it("keeps the grammar help text stable", () => {
    assert.match(QUERY_GRAMMAR_HELP, /why <activity_id>/);
    assert.match(QUERY_GRAMMAR_HELP, /capacity <location_id> week <n>/);
  });
});

describe("query outcome tone", () => {
  it("maps each outcome to a tone and label", () => {
    assert.equal(queryOutcomeTone("answerable"), "ok");
    assert.equal(queryOutcomeTone("unanswerable"), "warn");
    assert.equal(queryOutcomeTone("rejected"), "danger");
    assert.equal(queryOutcomeTone("error"), "danger");
    assert.equal(queryOutcomeTone("idle"), "idle");
    assert.equal(queryOutcomeLabel("unanswerable"), "Unanswerable");
  });

  it("classifies the response, rejected and failed states", () => {
    assert.equal(classifyQueryResponse(null, false, false), "idle");
    assert.equal(
      classifyQueryResponse({ answerable: true }, false, false),
      "answerable",
    );
    assert.equal(
      classifyQueryResponse({ answerable: false }, false, false),
      "unanswerable",
    );
    assert.equal(classifyQueryResponse(null, true, false), "rejected");
    assert.equal(classifyQueryResponse(null, false, true), "error");
  });
});

describe("formatEvidenceValue", () => {
  it("renders missing and empty values as a dash", () => {
    assert.equal(formatEvidenceValue(null), "—");
    assert.equal(formatEvidenceValue(undefined), "—");
    assert.equal(formatEvidenceValue([]), "—");
    assert.equal(formatEvidenceValue({}), "—");
  });

  it("joins arrays and stringifies objects", () => {
    assert.equal(formatEvidenceValue([1, 2, 3]), "1, 2, 3");
    assert.equal(formatEvidenceValue(["A1", "A2"]), "A1, A2");
    assert.equal(formatEvidenceValue({ week: 2 }), JSON.stringify({ week: 2 }));
    assert.equal(formatEvidenceValue("b1"), "b1");
    assert.equal(formatEvidenceValue(0), "0");
  });
});

describe("projectEvidence", () => {
  it("sorts fields alphabetically for a stable panel", () => {
    const fields = projectEvidence({ week: 2, activity_id: "A1", excess: 0 });
    assert.deepEqual(
      fields.map((field) => field.key),
      ["activity_id", "excess", "week"],
    );
    assert.equal(fields[1].value, "0");
  });
});

describe("projectCitations", () => {
  it("keeps the citation order and sorts each field map", () => {
    const rows = projectCitations([
      {
        source: "schedule_access",
        fields: { week: 1, activity_id: "A1" },
      },
      { source: "contract_result", fields: { overrun_days: 0 } },
    ]);
    assert.deepEqual(
      rows.map((row) => row.source),
      ["schedule_access", "contract_result"],
    );
    assert.deepEqual(
      rows[0].fields.map((field) => field.key),
      ["activity_id", "week"],
    );
  });

  it("handles a missing citation list", () => {
    assert.deepEqual(projectCitations(undefined as never), []);
  });
});

describe("buildQueryExamples", () => {
  it("uses the first vocabulary entry for each form", () => {
    const examples = buildQueryExamples({
      activities: ["A2"],
      contracts: ["C9"],
      locations: ["SEC:X"],
      weeks: [4],
    });
    assert.deepEqual(
      examples.map((example) => example.query),
      ["why A2", "downstream A2", "capacity SEC:X week 4", "milestone C9"],
    );
  });

  it("falls back to placeholders on an empty vocabulary", () => {
    const examples = buildQueryExamples({
      activities: [],
      contracts: [],
      locations: [],
      weeks: [],
    });
    assert.equal(examples[0].query, "why A1");
    assert.equal(examples[2].query, "capacity LOC1 week 1");
  });
});
