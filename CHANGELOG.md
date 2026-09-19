# Changelog

All notable changes to RAO are recorded here.

## [Unreleased]

- Add the physical possession calendar as a seventh workflow stage: a fail-closed projection of an assured job with versioned publication and date-only ICS export.
  - Ported from `RAO_Possession_Calendar_Project` (additive patch based on commit `46abcf8`), re-applied by hand onto this diverged branch.
- Add what-if sandbox and deterministic schedule query panels to the result view.
- Add an instance inspection CLI, Windows helpers and a repository hygiene audit.
- Add fragility and what-if sandboxing plus a deterministic schedule query backend.
- Add the disruption replanning panel to the validated result view.
- Add a Playwright browser and responsive acceptance suite covering AT-15.
- Add optional LTA DataMall advisory context, off by default with no egress without a key.
- Add disruption impact assessment and minimal-churn replanning backend.
- Build a witness-gated greedy incumbent so tight budgets still return a safe complete schedule.
- Add Tonight controller mode, scenario comparison, embedded why evidence and network name mapping.
- Harden hidden-instance parsing against malformed CSV, bad encoding and unsafe values.
- Enforce a single seven-night physical-slot universe across solver, fallback and witness.
- Reject provable same-class closure, mirror and interchange conflicts in fallback validation.
- Fail closed on malformed or contradictory official validator reports.
- Keep adaptive horizon from reporting congestion as proven infeasibility.
- Mark jobs failed on enqueue or persistence errors instead of stranding them.
- Ground explanation reasons in persisted displacement evidence and real co-sharing.
- Correct control-board buffer, selection, ECLO, assurance and stale-result behaviour.
- Make the additive schema upgrade concurrency safe and document it.
- Match mapped DTL/CCL topology to PS1 and broaden public-answer failure tests.
- Block submission export when the persisted physical witness fails.
- Upgrade existing `v0.3.0` database volumes with the physical-night column.
- Add frontend assurance tests and show soft capacity excess details.
- Document secure local publishing with Cloudflare Tunnel and alternatives.
- Exclude local backend environments and test artifacts from container builds.
- Organise the judge workflow into accessible staged tabs.

### Added

- Explicit physical possession slots and an independent persisted witness check.
- Adaptive congestion-safe horizon growth for Scenarios A and C.
- Reproducible public A/B/C answer generation and mandatory CI validation.
- Linked railway schematic, possession drawer, capacity overlays and deterministic explanations.
- Three-layer validation assurance for physical, fallback and official checks.
- Production nginx frontend image and hosted deployment runbook.
- Deterministic DTL/CCL mapped demonstration dataset generator.

### Changed

- `access_night` is derived as a contract-local export label rather than physical time.
- `co_share_group` is derived from the location-week physical possession slot.
- Public deployment ports bind to loopback by default for reverse-proxy hosting.
- Fallback-only validation is labelled provisional in the web interface.

### Fixed

- Capacity now counts distinct physical possessions rather than local night labels.
- Priority scoring follows the PS1 per-activity nudge inside the contract priority band.
- Process reloads retain schedule jobs, physical evidence and explanations.
