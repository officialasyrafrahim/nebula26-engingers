# PS1 Compliance

This document compares the implemented RAO workflow with the authoritative
`PS1_README.md` requirements.

## Core Requirements

| PS1 requirement | Status | Implementation |
| --- | --- | --- |
| Complete every activity workload | Met | CP-SAT half-unit workload constraints and submission gate |
| Planned start and predecessor FS+0 | Met | Physical-slot solver and fallback checks |
| Buffers, Live mirroring and interchange | Met internally | Compiled closure graph, physical-slot constraints and independent witness check |
| PM/PC/C mixes and co-sharing | Met | Legal slot mix and deterministic location-week groups |
| Weekly allocation and workfront limits | Met | Contract slot caps and per-slot workfront constraints |
| Congestion-safe completion | Met | Adaptive horizon growth; time exhaustion returns `UNKNOWN`, not false infeasibility |
| Scenario A | Met | Strict supply, no ECLO, weighted overrun objective |
| Scenario B | Met | Hard planned dates, excess and ECLO objective |
| Scenario C | Met | Combined objective, +1 soft capacity, two-week ECLO window |
| Exact three-file output | Met | Separate scenario zip with exact published headers |
| Hidden-instance web workflow | Implemented | Eight-file browser upload, queued solve, visualisation, assurance and download |

## Assurance

RAO reports three different assurance layers.

1. The physical witness check verifies the generated internal physical slots.
2. The fallback validator checks the exported CSVs under the published,
   sample-calibrated interpretation.
3. The official validator adapter runs the judge command when it is supplied.

The output schema does not uniquely identify every cross-contract physical
night. Therefore a fallback-only pass is labelled `PROVISIONAL`. The solver is
stricter than the fallback for buffer-only conflicts, but official calibration
remains required before claiming authoritative parity.

## Deliverables

| Deliverable | Repository status | External action |
| --- | --- | --- |
| Public A/B/C results | Generator and validation commands implemented | Generate and commit final answer keys |
| Hosted live web app | Production Compose stack and runbook implemented | Provision host, DNS, HTTPS and judge access |
| Three-minute video | Not a repository artifact | Record after public deployment |
| GitLab repository URL | Source is currently on GitHub | Mirror or publish to the required GitLab project |

## Verification Commands

```bash
make test
make lint
make sample-validate
make public-answers-smoke
make web-build
make features-validate
```

The official validator is not included in the problem pack. Run
`make validator-calibrate` after its command becomes available.
