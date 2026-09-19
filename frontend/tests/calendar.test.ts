import assert from "node:assert/strict";
import test from "node:test";
import {
  calendarAuthorityBadge,
  calendarMatches,
  isOfficialAuthority,
  isProvisionalAuthority,
  locationLabel,
  compareCalendars,
} from "../src/lib/calendar.ts";
import type { PossessionCalendar } from "../src/api/types.ts";

test("calendar rejects old job responses and missing data", () => {
  const old = { job_id: "old" } as PossessionCalendar;
  assert.equal(calendarMatches("new", "new", old), false);
  assert.equal(calendarMatches("new", "old", old), false);
  assert.equal(calendarMatches("old", "old", old), true);
  assert.equal(calendarMatches("old", "old", null), false);
});

test("presentation mappings are opt-in and unknown locations retain raw IDs", () => {
  assert.equal(locationLabel("PLAT:ALP:H01:EB", false), "PLAT:ALP:H01:EB");
  assert.match(locationLabel("PLAT:ALP:H01:EB", true), /Promenade/);
  assert.equal(locationLabel("PLAT:HIDDEN:X99:EB", true), "PLAT:HIDDEN:X99:EB");
});

test("comparison keeps activity occurrence counts separate from possession counts", () => {
  const make = (week: number, activity_ids: string[]) => ({
    events: [{ week, physical_night: 2, activity_ids, eclo: false }], scores: {},
  }) as PossessionCalendar;
  const diff = compareCalendars(make(1, ["a","b"]), make(2, ["a","b","c"]));
  assert.equal(diff.moved, 2); assert.equal(diff.added, 1);
  assert.equal(diff.possessionDelta, 0);
});

test("only the official authority is not provisional", () => {
  assert.equal(isOfficialAuthority("official"), true);
  assert.equal(isOfficialAuthority("OFFICIAL "), true);
  assert.equal(isProvisionalAuthority("fallback"), true);
  assert.equal(isProvisionalAuthority("official"), false);
  assert.equal(isProvisionalAuthority(null), true);
  assert.equal(isProvisionalAuthority(""), true);
});

test("fallback authority carries a PROVISIONAL badge and warning", () => {
  const badge = calendarAuthorityBadge("fallback");
  assert.equal(badge.provisional, true);
  assert.equal(badge.label, "PROVISIONAL");
  assert.match(badge.warning, /fallback validation/i);
  assert.match(badge.warning, /not official acceptance/i);

  const official = calendarAuthorityBadge("official");
  assert.equal(official.provisional, false);
  assert.equal(official.label, "OFFICIAL");
  assert.equal(official.warning, "");
});

test("an unknown authority is treated as provisional", () => {
  const badge = calendarAuthorityBadge("mystery");
  assert.equal(badge.provisional, true);
  assert.match(badge.warning, /mystery/);
});
