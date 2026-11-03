# Example: the full discipline chain on a public Isaac Lab task

**Status: design draft. Nothing has been run and no machine has been created.**

A cheap, reproducible walk through every rak-discipline step, on a question whose answer is expected in
advance: *does randomizing robot-body friction during training keep a flat-ground quadruped
(`Isaac-Velocity-Flat-Anymal-C-v0`) walking at low friction, without costing nominal performance?*
Because the expected answer is known, a surprise points at the pipeline first - which is exactly what
the gate is for.

## The chain, and what each step leaves behind

| Step | Skill | Artifact in this folder |
|---|---|---|
| 1. Collision search | `collision-search` | `docs/collision/friction-dr-legged-2026-10-31.md` (done: collides with 3 of 5 papers read) |
| 2. Pre-registration | `prereg` | `docs/prereg/friction-dr-anymal.md` (draft) |
| 3. Verdict script, written before data | `verdict` | `experiments/friction-dr-anymal/verdict.py` (gates and criteria filled) |
| 4. Re-read defaults on the run machine, timing smoke | `prereg` §9 steps 0–1 | erratum to prereg §6 if the budget changes |
| 5. Freeze | `prereg` | `.rak/frozen/friction-dr-anymal.json` |
| 6. Train 2 arms × 5 seeds | - | launched as `RAK_PREREG=friction-dr-anymal ...` (blocked by the hook otherwise) |
| 7. Gate: friction really applied, metric sees ice, override neutral, training worked, do-nothing fails | `gate` | `gate_evidence.json`, `.rak/gates/friction-dr-anymal.json` |
| 8. Judge | `verdict` | `verdict.json` (write-once, hashed) |
| 9. Results doc + errata | `erratum` | `docs/results/friction-dr-anymal.md` (append-only once committed) |
| 10. Lesson | `lesson` | `lessons/friction-dr-anymal.md`, numbers from `handson/.../logs` |

`.rak/discipline.json` turns the hooks on for this folder.

The verdict script has been exercised once on fabricated inputs, in a temporary copy that was deleted. That
run produced PASS, FAIL and UNDETERMINED for the three criteria, and refused to judge without a gate. No real
evidence exists yet.

## Scripts (written, not yet run in Isaac)

| File | Role | Tested on CPU |
|---|---|---|
| `experiments/friction-dr-anymal/protocol.py` | Every registered number in one place. Its sha256 goes into every output | - |
| `.../core.py` | The decisions: friction per arm (refuses if the installed task default differs), command lock, episode tracker, material read-back check, write-once outputs | yes |
| `.../train.py` | Isaac adapter. `--arm` and `--seed` have no default; refuses without `RAK_PREREG`; success = final checkpoint exists, not exit code | launch checks yes; Isaac part no |
| `.../evaluate.py` | Isaac adapter. One policy × one friction per process; material read-back from the engine; command lock checked every step | settings yes; Isaac part no |
| `.../aggregate.py` | Summaries → `gate_evidence.json`, `results.json` with exactly the verdict's keys. Missing evaluations leave keys out (→ UNDETERMINED); summaries from another protocol, wrong episode counts or unregistered seeds raise | yes |

`python -m pytest -q tests` runs 34 CPU tests, including an end-to-end chain on fake summaries
(aggregate → `verdict.py gate` → `verdict.py judge`).
They were checked against four deliberate breaks, and each break turned tests red:
- command check disabled;
- material check always reporting "applied";
- success ignoring falls;
- heading control left on.

The Isaac-side calls (`root_physx_view.get_material_properties`, the ground material lookup, rsl_rl
runner loading) follow the installed Isaac Lab source but have never been executed. The timing smoke
(prereg §9 step 1) is their first test.

## Running it on a cloud VM (rak-cloud)

| File | Role |
|---|---|
| `cloud/cloud.json` | rak-cloud configuration for this example (placeholders; copy to `.rak/cloud.json` and fill) |
| `cloud/prepare_job.py` | Builds the job folder. It refuses a dirty tree, an unfrozen prereg, or frozen hashes that differ from HEAD. It archives HEAD with a COMMIT file, writes the sha256, renders `steps.sh` with that commit, and prints (does not run) the upload and create commands |
| `cloud/steps.sh.tmpl` | The VM steps, in prereg §9 order (see below) |

The steps, in order:
1. Fetch the code, checking the sha256 and COMMIT.
2. Install.
3. **G1 material preflight before any training.**
4. Timing smoke.
5. **Budget rule:** if the projection crosses 8 L4-hours, the job stops before any main training.
6. Train × 10.
7. Evaluate × 31.
8. Aggregate.
9. Gate.
10. Judge, only if the gate passed. A failed gate ends the job with no verdict.

`tests/test_cloud_flow.py` runs this whole chain on a laptop. Everything is real code except gcloud and the
physics: the rak-discipline freeze, `prepare_job`, rak-cloud's `vm_job.sh` with all 49 steps, the example's argument
handling, aggregate, verdict, and finally rak-cloud's waiter pulling, verifying against the manifest and deleting.
It also covers the early stops:
- G1 preflight failing;
- the budget projection crossing the line;
- tampered code;
- a failed gate producing no verdict.

Three of these guards were removed on purpose once, and each removal was caught.

## Budget (estimate, not measured)

The training length is the task default: 300 iterations × 24 steps × 4096 envs ≈ 29.5 M env-steps per run *(verify at the pinned tag)*.

| Item | Count | Per item | Total (L4-hours) | Basis |
|---|---|---|---|---|
| Setup: Isaac Sim pip + Isaac Lab install + shader warm-up | 1 | 20–30 min | 0.3–0.5 | Isaac Sim pip install took 85–93 s on an L4 VM in our earlier trial; the rest is an assumption |
| Timing smoke (50 iterations) | 1 | ~10 min | 0.2 | assumption |
| Training | 10 | 12–18 min (start-up 2–3 + 10–15 training) | 2.0–3.0 | **weak anchor**: our notes record ~5 min for ~30 M PPO env-steps on a similar flat quadruped task on unrecorded hardware; assumed an L4 is 2–3× slower |
| Evaluation processes (one friction condition per process) | 31 (20 main + 5 ice + 5 no-override + 1 zero-action) | 3–4 min | 1.6–2.1 | ~1 M env-steps each + start-up |
| Sync, checks, slack | - | - | 0.3 | - |
| **Total** | | | **≈ 4.4–6.1** | |

- **Money:** at an assumed US$0.85 per L4-hour on demand *(price not checked)*: **≈ US$3.7–5.2**.
  Spot is cheaper, but a Spot VM in this kit's own trials was preempted 6 minutes after boot, and every
  preemption restarts the 0.3–0.5 h setup.
- **Cheaper variant** (≈ 3.5–4.6 h): evaluate several friction values in one process by assigning
  friction per environment group. This cuts evaluation from 31 processes to 11, but G1 must then check
  the read-back friction per group.
- The plan's earlier figure of 2–3 VM-hours did not count the 31 separate evaluation processes or the
  setup. This table replaces it.
- Stop rules (prereg §6): reporting line US$8, hard stop US$12. If the timing smoke implies more than
  8 L4-hours, stop and re-plan.
