---
id: "friction-dr-anymal"
title: "Does training with randomized friction keep a flat-ground quadruped walking on low friction, without losing nominal performance?"
status: draft
verdict_script: "experiments/friction-dr-anymal/verdict.py"
frozen_files:
  - "experiments/friction-dr-anymal/protocol.py"
  - "experiments/friction-dr-anymal/core.py"
  - "experiments/friction-dr-anymal/aggregate.py"
  - "experiments/friction-dr-anymal/smoke_budget.py"
created: "2026-10-31"
---

# Friction randomization on a flat-ground quadruped (demo prereg)

> **DRAFT - not frozen, nothing has been run.** This is the worked example of the rak-discipline chain.
> The question is deliberately not new (see §1); the point is to show every step on a cheap public task.
> Values marked *(verify at the pinned tag)* were read from a local Isaac Lab checkout, not from the tag
> this demo pins; step 0 of §9 re-reads them on the machine that runs the job.

## 0. Question

- **Q1.** Trained with robot-body friction sampled from a range, does the policy succeed more often at
  low friction (μ = 0.3) than the same policy trained at the fixed default friction?
- **Q2.** Does it do so without losing more than 5 points of success at the nominal friction (μ = 0.8)?

**Out of scope:** rough terrain; real hardware; other randomizations (mass, pushes) beyond the task defaults;
tuning PPO; any claim about which friction range is best.

## 1. Prior work and collision check

Record: `docs/collision/friction-dr-legged-2026-10-31.md` (searched and read 2026-10-31; verdict: collides).
Colliding work: Peng et al. 2017 (arXiv 1710.06537), the same "fixed vs randomized friction" ablation on a
manipulation task; Lee et al. 2020 (arXiv 2010.11251) and Rudin et al. 2021 (arXiv 2109.11978), friction
randomization in legged locomotion. Rudin et al. is the lineage of the Isaac Lab task used here.

**What is not new:** randomizing physical parameters during training to get robustness to their
variation is the standard domain-randomization recipe, and friction randomization is common in
legged-locomotion training pipelines. This run tests nothing beyond "the recipe works on this task with
this evaluation", which is why it is a good demo: the expected answer is known in advance, so a
surprising result points at the pipeline before it points at the world.

## 2. Arms

| Arm | Robot-body friction during training | Everything else |
|---|---|---|
| control | static 0.8, dynamic 0.6 (task default *(verify at the pinned tag)*) | `Isaac-Velocity-Flat-Anymal-C-v0` defaults, rsl_rl PPO defaults, 300 iterations, 4096 envs |
| treatment | static U(0.25, 1.2), dynamic U(0.2, 1.0) with `make_consistent=True` (dynamic ≤ static per material) | identical |

- Ground material: static = dynamic = 1.0 with `friction_combine_mode="multiply"` *(verify at the pinned tag)*,
  so the effective contact friction equals the robot-body value. The gate checks this by reading it back.
- **Training seeds:** 9101 9102 9103 9104 9105 for each arm (10 runs). n = 5 per arm, enough to see
  a 15-point mean difference and to report how many seeds agree; not enough to separate a bimodal seed
  distribution, so C1b also counts seeds.
- **Evaluation seed:** 7 for every evaluation, so every policy sees the same commands and initial states.

## 3. Gate (must pass before any result is read)

All gate thresholds are also in `GATES` of the verdict script.

| Check | Procedure | Pass if |
|---|---|---|
| **G1 friction really applied** (positive control, mechanism) | In every override evaluation, read the material back from the physics engine for every robot collision shape (static and dynamic) and the ground plane (friction and combine mode) | max abs deviation of robot static friction from μ ≤ 1e-6, of dynamic friction from 0.75 μ ≤ 1e-6, ground = 1.0 with combine mode "multiply" |
| **G2 evaluation sees a known effect** (positive control, metric) | Control policies (5 seeds) evaluated at μ = 0.05 vs μ = 0.8 | mean success drop ≥ 0.50 |
| **G3 override path is neutral** (negative control) | Control policies evaluated at μ = 0.8 through our override code vs the task default path (both end at static 0.8 / dynamic 0.6, so this also measures evaluation repeatability) | mean abs success difference ≤ 0.05 |
| **G4 training worked** (sanity, replaces "control reproduction": there is no previous round) | Control policies at μ = 0.8 (no override) | mean success ≥ 0.80 |
| **G5 do-nothing baseline** | Zero-action policy at μ = 0.8 | success ≤ 0.05 |

G1 exists because a material override can silently not apply (for example to instanced prims), and
every number downstream would then compare two identical conditions. G2 shows the success criterion can
see friction at all. A gate failure stops the line; thresholds are not relaxed.

## 4. Criteria

Episode success (binary, decided at episode end, separate from the training reward):
the episode reaches its 20 s limit **without** the base-contact termination **and** the episode-mean
planar velocity tracking error ‖v_xy − c_xy‖ is ≤ 0.25 m/s.
Commands: one command per episode drawn with the evaluation seed from the task's ranges
(lin_vel_x, lin_vel_y, ang_vel_z in [-1, 1] *(verify at the pinned tag)*); **command resampling is disabled
during evaluation and the command is asserted unchanged every step.**
Per policy and condition: 512 envs × 2 episodes = 1,024 episodes.

Evaluation settings (all set in `evaluate.py`, all tested on CPU):
- Friction override: static = μ, dynamic = 0.75 μ (the task default ratio 0.6 / 0.8), through the task's own material event.
- Command lock: resampling timer off, **heading control off and standing envs off**. Both rewrite the command
  every step in the installed command term. The command term's resample is replaced so that episode k of
  env i always gets the same command for every policy. The command is checked every step, and the lock's
  episode count must match the episode tracker's.
- As in the task's PLAY configuration: no pushes, no external force events, no observation corruption.
  Other start-up randomization (base mass) stays, seeded by the evaluation seed.
- The step on which an env is reset is excluded from both episodes, because the state read after an automatic reset belongs to the new episode.

| Criterion | Metric | Rule (raw values) | Min n | Missing data |
|---|---|---|---|---|
| C1 | mean over seeds of success(treatment, μ=0.3) − success(control, μ=0.3) | ≥ 0.15 | 5 seeds per arm | UNDETERMINED |
| C1b | number of seed pairs (same seed index) where treatment > control at μ=0.3 | ≥ 4 of 5 | 5 | UNDETERMINED |
| C2 | mean success(treatment, μ=0.8) − mean success(control, μ=0.8) | ≥ −0.05 | 5 | UNDETERMINED |

**Descriptive only:** success at μ = 0.5 and 1.0; fall rate and tracking error separately; per-seed tables.

## 5. Predictions

- C1 PASS, confidence 75%. C1b PASS, 65%. C2 PASS, 70% (randomization usually costs little at nominal on flat ground).
- G2 is the gate most likely to surprise: if the default policy already handles μ = 0.05, the
  success criterion is too loose and the line stops for redesign.

## 6. Budget and stop rules

Estimate in `README.md` §Budget (≈ 4–6 L4-hours, ≈ US$4–6 on-demand at an assumed US$0.85/h; *unverified price*).
- Step 1 of §9 is a timing smoke (one control run, 50 iterations). If the measured time per run implies
  a total above 8 L4-hours, stop and re-plan before the main runs; record the measurement as an erratum to this section.
- Reporting line US$8, hard stop US$12 (machine deleted, partial results reported as stopped).
- Per job wall-clock limit: training 40 min, evaluation 15 min; cloud max-run 8 h.

## 7. What we will not be able to say

- Anything about real hardware: simulated friction is a single Coulomb coefficient per shape pair.
- Anything about rough terrain, or about friction combined with other shifts.
- Which range is best: one treatment range only.
- With n = 5, a bimodal seed distribution would show up only as C1b disagreeing with C1.

## 8. Sim-to-real section

Not applicable to the claim (simulation only), listed so a reader does not over-read it:
- Real friction varies per foot, over time and with load; here it is constant per episode and per shape.
- The success threshold uses the true base velocity, which a real robot estimates.
- A second-simulator check is not part of this demo.

## 9. Execution

0. On the run machine: re-read the defaults marked *(verify at the pinned tag)* from the installed source
   (grep, not memory); if any differs, stop and file an erratum before freezing.
1. Timing smoke (not evidence): one control run, seed 9100, 50 iterations; record s/iteration and process start-up time.
2. Freeze this prereg and the verdict script (`rak_discipline.py freeze`).
3. Train 10 runs: `RAK_PREREG=friction-dr-anymal python train.py --task Isaac-Velocity-Flat-Anymal-C-v0 --headless --seed <s> --arm <control|treatment>`
   (one process per run; the arm sets the friction event; every run dumps its resolved config).
4. Gate evaluations (G1–G5) → `gate_evidence.json` → `verdict.py gate`.
5. Main evaluations (10 policies × μ ∈ {0.3, 0.8}) → `results.json` → `verdict.py judge`.
6. Results doc, then a lesson (`lesson` skill) whose numbers come from the logs.

Files that must exist before the machine is deleted: 10 final checkpoints (not committed; kept in the
bucket), every `params/*.yaml` config dump, `gate_evidence.json`, `results.json`, per-episode CSVs,
training logs (tfevents), `verdict.json`. Each is checked by name and size after download.
