# Mapped DTL and CCL demonstration instances

This directory documents the mapped demonstration dataset generator for
`F-DATA-001`. The generator writes exactly the eight PS1 instance CSVs. The
solver keeps using its own identifiers (`ALP`, `BET`, `S01`..`S18`, `H01`,
`H02`). The real station names are a presentation layer only and never reach the
canonical model.

## Provenance and honesty note

The station names and their order below are an unverified presentation mapping
of the public LTA Downtown Line and Circle Line. They have not been checked
against a retrieved authoritative LTA dataset, so the topology is a presentation
label and not an operational reference. The generator keeps its own canonical
identifiers and the real names never reach the solver. Every capacity, contract,
programme, workfront, planned date and access allocation in the generated files
is synthetic. The synthetic layer follows PS1 rules only and does not claim to
reproduce LTA operational data.

## Real versus synthetic layers

| Layer | Source | Notes |
| --- | --- | --- |
| Line topology | Unverified presentation mapping | `ALP` is the DTL city segment, `BET` is the CCL segment |
| Station order | Unverified presentation mapping | 10 stations per line; Promenade and Bayfront are interchange hubs present on both lines |
| Sector chain | Unverified presentation mapping | Adjacent stations; H01_H02 is a separate tunnel per line with independent capacity, so both mapped sectors carry `is_shared=0` to match the public instance |
| Supply capacities | Synthetic | Ladder described below, follows PS1 shape only |
| Buffer policy | PS1 rules | Live 2 sectors and opposite bound, Consist 1, Others 0 |
| Contracts and workfronts | Synthetic | 14 contracts, 41 activities, priorities 1 to 3 |
| Access allocations | Synthetic | Deterministic per profile and seed |
| Horizon | Synthetic | 30 weeks from Monday 2027-01-04 |

The `contract_description` column carries real DTL and CCL place names because
that column is free text. The eight-file schema has no `display_name` column for
activities, and the parser rejects extra columns, so the activity mapping is
documented here instead of in the CSV.

## ALP and BET to DTL and CCL mapping

| Station id | ALP name | BET name |
| --- | --- | --- |
| S01 / S11 | Newton | Dakota |
| S02 / S12 | Little India | Mountbatten |
| S03 / S13 | Rochor | Stadium |
| S04 / S14 | Bugis | Nicoll Highway |
| H01 | Promenade | Promenade |
| H02 | Bayfront | Bayfront |
| S05 / S15 | Downtown | Marina Bay |
| S06 / S16 | Telok Ayer | Prince Edward Road |
| S07 / S17 | Chinatown | Cantonment |
| S08 / S18 | Fort Canning | Keppel |

`ALP` maps to `DTL` in station order. `BET` maps to `CCL` in station order.
Promenade is `H01` on both lines. Bayfront is `H02` on both lines. The H01_H02
interchange is two physically separate tunnels with independent line capacity,
so both mapped H01_H02 sectors carry `is_shared=0` to match the published public
instance. Only a `Live` activity closes the other line's H01_H02 tunnel.

## Profiles

| Profile | Demand | Supply | Expected solving |
| --- | --- | --- | --- |
| `baseline` | Spread across both lines and bounds | Outer 4, approach 3, H01_H02 tunnel 2, interchange platform 2 | A and B solve inside the bounded test budget. C is a stress case and may return `UNKNOWN` in a short budget |
| `congestion` | Higher synthetic `total_accesses` across Bugis to Marina Bay | Outer 4, approach 2, H01_H02 tunnel 1, interchange platform 1 | Deliberate stress. A, B and C may return `UNKNOWN` inside a short budget, which is not proven infeasibility |
| `disruption` | Byte-identical to `baseline` | Outer 4, approach 3, H01_H02 tunnel 1, interchange platform 1 | A and B solve. C may need a longer budget |

The supply ladder is applied to tunnel sectors and platforms as follows.

| Location class | baseline | congestion | disruption |
| --- | ---: | ---: | ---: |
| Outer tunnel sectors | 4 | 4 | 4 |
| Approach tunnel sectors | 3 | 2 | 3 |
| H01_H02 tunnel sectors | 2 | 1 | 1 |
| Normal platforms | 3 | 3 | 3 |
| Interchange platforms | 2 | 1 | 1 |

Approach sectors are S04_H01 and H02_S05 on ALP, and S14_H01 and H02_S15 on BET.
The congestion profile also adds three synthetic access nights to every activity
whose span touches the Bugis to Marina Bay CBD, capped at 7.

## Fixed policy encoded in every profile

| Policy | Value |
| --- | --- |
| Horizon start | 2027-01-04 |
| Horizon weeks | 30 |
| Live buffer | 2 sectors, opposite bound required |
| Non-live (Consist) buffer | 1 sector, no mirror |
| Non-live (Others) buffer | 0 sectors, no mirror |
| Live weekly access cap | 2 |
| Other weekly access cap | 3 |
| Workfronts | 1 or 2 per contract |
| Predecessors | Backward links inside a contract, so the graph is acyclic |

## Activity mapping

Every activity span is fixed. The seed only varies `total_accesses`,
`planned_start_date` and the derived contract dates. The table lists the base
workload before the small deterministic seed jitter.

| Activity | Contract | Line | Bound | Real span | Base accesses |
| --- | --- | --- | --- | --- | ---: |
| A001 | C001 | DTL | WB | Newton to Bugis | 3 |
| A002 | C001 | CCL | EB | Bayfront to Keppel | 3 |
| A003 | C001 | DTL | EB | Telok Ayer to Fort Canning | 2 |
| A004 | C001 | CCL | WB | Dakota to Stadium | 2 |
| A005 | C002 | DTL | WB | Little India to Bayfront | 4 |
| A006 | C002 | CCL | EB | Mountbatten to Bayfront | 4 |
| A007 | C002 | CCL | WB | Promenade to Prince Edward Road | 3 |
| A008 | C003 | CCL | EB | Dakota to Stadium | 3 |
| A009 | C003 | DTL | EB | Newton to Rochor | 2 |
| A010 | C003 | DTL | WB | Chinatown to Fort Canning | 2 |
| A011 | C004 | DTL | WB | Rochor to Bayfront | 4 |
| A012 | C004 | CCL | EB | Stadium to Bayfront | 4 |
| A013 | C004 | DTL | EB | Little India to Bugis | 3 |
| A014 | C005 | DTL | EB | Newton to Rochor | 3 |
| A015 | C005 | CCL | WB | Marina Bay to Keppel | 3 |
| A016 | C005 | CCL | EB | Mountbatten to Nicoll Highway | 4 |
| A017 | C006 | DTL | WB | Newton to Little India | 2 |
| A018 | C006 | CCL | EB | Prince Edward Road to Keppel | 2 |
| A019 | C006 | DTL | EB | Downtown to Chinatown | 3 |
| A020 | C007 | CCL | EB | Mountbatten to Bayfront | 5 |
| A021 | C007 | DTL | WB | Bugis to Downtown | 4 |
| A022 | C007 | CCL | WB | Promenade to Marina Bay | 3 |
| A023 | C008 | DTL | EB | Newton to Bugis | 3 |
| A024 | C008 | CCL | WB | Dakota to Stadium | 2 |
| A025 | C008 | DTL | WB | Telok Ayer to Fort Canning | 2 |
| A026 | C009 | CCL | EB | Stadium to Promenade | 4 |
| A027 | C009 | DTL | EB | Promenade to Downtown | 3 |
| A028 | C009 | CCL | WB | Bayfront to Prince Edward Road | 2 |
| A029 | C010 | DTL | EB | Chinatown to Fort Canning | 3 |
| A030 | C010 | CCL | WB | Mountbatten to Nicoll Highway | 4 |
| A031 | C010 | DTL | WB | Little India to Bugis | 3 |
| A032 | C011 | CCL | EB | Promenade to Cantonment | 3 |
| A033 | C011 | DTL | WB | Promenade to Downtown | 3 |
| A034 | C011 | CCL | WB | Mountbatten to Nicoll Highway | 2 |
| A035 | C012 | DTL | EB | Rochor to Bugis | 2 |
| A036 | C012 | CCL | EB | Dakota to Mountbatten | 2 |
| A037 | C012 | DTL | WB | Bayfront to Downtown | 1 |
| A038 | C013 | DTL | EB | Promenade to Bayfront | 3 |
| A039 | C013 | DTL | WB | Promenade to Bayfront | 2 |
| A040 | C014 | CCL | EB | Promenade to Bayfront | 2 |
| A041 | C014 | CCL | WB | Promenade to Bayfront | 2 |

C013 and C014 are the Live contracts. A038 to A041 sit on the H01_H02 tunnel
sector and exercise the cross-line Live interchange closure.

## Reproducibility

The generator is deterministic. The same `profile` and `seed` always produce
identical bytes for all eight files. Generate one profile with:

```
python3 scripts/generate_mapped_instance.py --profile baseline --outdir data/mapped/baseline --seed 42
```

Replace `--profile` with `congestion` or `disruption` for the other datasets.
The generated CSV directories are not committed yet. Run the command above, or
the tests, to produce them locally. `backend/tests/test_mapped_instance.py`
generates every profile, loads it with the real parser and compiler, and checks
determinism, buffer policy, the per-line interchange sectors (`is_shared=0`), the
interchange Live work and bounded A/B solves for the profiles documented as
solvable. Stress combinations that do not converge inside the bounded budget are
reported, not asserted.
