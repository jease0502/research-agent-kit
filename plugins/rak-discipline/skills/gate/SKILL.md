---
name: gate
description: Design and run the gate of a pre-registered experiment - a positive control with a known answer, a negative control that must show nothing, reproduction of the previous control arm, and a do-nothing baseline - before any result is read. Use when writing a prereg's gate section, when a metric or judge is new, or when a result looks too good or too bad.
license: Apache-2.0
compatibility: Gate status is written by the frozen verdict script (Python 3.9+). The read-blocking hook is Claude Code only.
metadata:
  plugin: rak-discipline
  version: "0.1.0"
---

# Gate

A criterion that has never been shown a known answer is measuring something unknown.
The gate shows it one, through the same pipeline, before the real data is read.

## Why this exists

Three common ways a correct-looking pipeline measures the wrong thing:

- The criterion reads a stale or cached value (a pose that is never updated, a buffer filled once).
- The criterion reads a different object than intended (the wrong frame, the wrong joint order,
  a coordinate box offset from the real contact geometry).
- The evaluation itself changes what is evaluated (a command resampled mid-episode overwrites the
  one you set; a reset not wrapped in the same inference mode).

None of these produce an error. All of them are caught by running a case whose answer you already know.

## The four checks

| Check | Question it answers | Example |
|---|---|---|
| **Positive control** | Can the criterion see an effect that is definitely there? | A synthetic system with known parameters is recovered within 5%; a scripted policy known to succeed scores success |
| **Negative control** | Does it stay quiet when there is nothing? | Shuffled labels, an identical copy as "treatment", a no-op change: effect within ±tolerance |
| **Control reproduction** | Is the baseline the same baseline as last round? | Control arm with the previous round's seeds lands within tolerance of its recorded value |
| **Do-nothing baseline** | Is the threshold above what doing nothing earns? | A zero-action policy's score is computed and every threshold is above it |

Pick the positive control at the level of the claim. If the claim is "the controller tracks the
command", the positive control is a case where tracking is known to be correct, run through the
same evaluation code, with the same checks at the same time step.

## Steps

1. Write the four checks in prereg §3 with **numeric tolerances**, and the same numbers in
   `GATES` of the verdict script. Freeze (see `prereg`).
2. Produce the evidence json with the real pipeline (same code path, same flags, same machine type).
   Do not hand-compute gate values.
3. Run the gate:

   ```bash
   RAK_PREREG=<id> python experiments/<id>/verdict.py gate --evidence gate_evidence.json
   ```

   This writes `.rak/gates/<id>.json` with `PASS` or `FAIL`, bound to the frozen hashes.
4. **FAIL means stop.** Do not read results. Report the failing check, find the mechanism,
   and decide with whoever owns the question whether to fix the pipeline and re-register under a new id.
   Never widen a gate tolerance to make it pass (see failure mode "guard loosened instead of fixed").
5. **PASS** lets `verdict.py judge` run. The hook also blocks `verdict.py judge` commands while the
   gate is not PASS, or when the gate was recorded against other prereg / verdict hashes (`STALE`).

## Designing a positive control that can fail

- It must exercise the exact quantity the criterion reads, at the exact time it reads it.
- It must be able to fail. A positive control that passes for every pipeline (including a broken one)
  is decoration. Check by breaking the pipeline on purpose once and confirming the gate fails.
- When the criterion is an automated judge (a model grading outputs), the positive control includes
  known-good and known-bad items, and the gate checks separation between them within the same case,
  not only overall accuracy.

## When the gate is expensive

Run it on the smallest configuration that still uses the same code path (one environment, one seed,
a short horizon) and say so in the prereg. Do not skip it. A skipped gate makes every downstream
number unreadable, and the expensive part of the run is wasted with it.

## Output

`.rak/gates/<id>.json` (commit it) and one line in the results doc:
`Gate: PASS (pos 0.012 ≤ 0.05; neg 0.004 within ±0.02; ctrl Δ 0.008 within ±0.03; do-nothing 0.11 < threshold 0.30)`.
