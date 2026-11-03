---
id: "<kebab-case-id>"
title: "<one line: what this run answers>"
status: draft            # draft -> frozen (by rak_discipline.py freeze; never by hand)
verdict_script: "<path/to/verdict.py>"   # committed together with this file, frozen with it
frozen_files:                            # everything else the verdict depends on: scorer, thresholds, tables, task defs
  - "<path/to/score.py>"
frozen_trees:                            # whole folders, file by file: e.g. the plugin or prompt set that is the treatment
  - "<path/to/folder>"
created: "YYYY-MM-DD"
---

# <title>

> Written before any result of this run exists. After `freeze`, this file does not change.
> Anything learned later goes into the results doc as a numbered erratum.

## 0. Question

One or two questions, each answerable with PASS / FAIL / UNDETERMINED.

**Out of scope** (write what you will not do or claim, so scope creep is visible):

## 1. Prior work and collision check

Link the collision-search record. State what is not new, at the level of the method
(components and how they connect), and which difference this run tests.

## 2. Arms

| Arm | What changes | Everything else |
|---|---|---|
| control | | identical to the last round's control (reproduced in the gate) |
| treatment | | |

Seeds: list them explicitly (e.g. `101 102 103 104 105`). Use a seed range no earlier run used.
n per arm and why that n.

## 3. Gate (must pass before any result is read)

Thresholds are fixed here and in `GATES` of the verdict script.

- **Positive control**: a case with a known answer, run through the same pipeline and the same
  criterion. Example: a synthetic system with known parameters must be recovered within X%.
  If the criterion cannot see a known effect, it is measuring something else.
- **Negative control**: a case where the effect must be absent (shuffled labels, a no-op change,
  a do-nothing baseline). The criterion must report no effect.
- **Control reproduction**: the control arm reproduces the previous round within a stated tolerance.
  If it does not, the comparison is against a moving target.
- **Do-nothing baseline**: what score does doing nothing get? Every threshold must be above it.

## 4. Criteria (written now, applied unchanged)

| Criterion | Metric (key in results json) | Rule | Min n | Verdict if data missing |
|---|---|---|---|---|
| C1 | | `>= 0.05`, raw value, no rounding | 5 | UNDETERMINED |

- Binary success is decided at episode end, separately from the training reward.
- When the metric is evaluated (which step, which state) is part of the criterion; write it.
- Descriptive-only quantities are listed separately and never get a verdict.

## 5. Predictions (with confidence)

For each criterion: expected outcome and a confidence (e.g. 60%). Written so that a surprise is visible.

## 6. Budget and stop rules

- Compute: max GPU-hours / max money for this run; reporting line and hard stop line.
- Time: wall-clock limit per job (and the cloud `max-run` if any).
- A run that hits a stop rule is reported as stopped, not as a result.

## 7. What we will not be able to say

Examples: one environment only; single morphology; simulation only; n too small to separate
two seeds' bimodal outcomes; a metric that is a proxy for the real goal.

## 8. Sim-to-real section (fill when the result is meant to transfer to hardware)

- Observations the real system cannot measure (or measures with different noise / latency).
- Actuator limits, rate limits and smoothness: present from the first training run, not added later.
- Randomisation ranges and the real values they are supposed to cover.
- The deployment frame of reference vs the training one (e.g. command frame, contact geometry).
- What is checked in a second simulator before hardware.

## 9. Execution notes

Where it runs, how the job is launched (`RAK_PREREG=<id> ...`), what is synced where,
and the list of files that must exist before the machine is deleted.
