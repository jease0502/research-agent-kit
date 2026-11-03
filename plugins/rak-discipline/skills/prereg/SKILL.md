---
name: prereg
description: Write and freeze a pre-registration before running an experiment - question, arms, seeds, gate (positive/negative controls), criteria with PASS/FAIL/UNDETERMINED, predictions, budget, and what the run cannot claim. Use before launching any training run, evaluation sweep or cloud GPU job whose result will be reported, and whenever someone asks to "just try" a change whose outcome will be cited.
license: Apache-2.0
compatibility: Freezing needs git and Python 3.9+. The launch guard is a Claude Code hook (plugin rak-discipline); other agents get the CLI checks only.
metadata:
  plugin: rak-discipline
  version: "0.1.0"
---

# Pre-registration

A result is only as trustworthy as the moment its reading rules were written.
Write the rules, commit them, freeze them, then run. Everything learned afterwards is an erratum.

## When

- Before any run whose number will be written down anywhere (a doc, a lesson, a message, a paper).
- Before spending cloud money. The prereg holds the budget and the stop line.
- Not for throwaway debugging. If a debugging run turns into evidence, stop and write a prereg
  for the run that will actually be cited.

## Steps

1. **Collision check first.** Run the `collision-search` skill and link its record in §1.
   A prereg written before the collision check usually tests the wrong difference.
2. **Copy the template.** `templates/prereg.md` and `templates/verdict.py` into the project
   (e.g. `docs/prereg/<id>.md` and `experiments/<id>/verdict.py`).
   Set `id` (kebab-case) and `verdict_script` in the frontmatter.
3. **Fill the sections in order.** Each section has a reason:
   - §0 Question and out-of-scope list: makes scope creep visible later.
   - §2 Arms and explicit seeds: a seed range that no earlier run used.
     Say why n is enough. A single seed is one sample (see failure mode "single-seed bimodality").
   - §3 Gate: positive control, negative control, control reproduction, do-nothing baseline.
     Use the `gate` skill to design them.
   - §4 Criteria: each PASS / FAIL / UNDETERMINED with raw-value comparisons and a minimum n.
     State *when* the metric is read (which step, which state).
   - §5 Predictions with confidence: written so that surprise is visible.
   - §6 Budget and stop rules.
   - §7 What the run will not be able to say.
   - §8 Sim-to-real section when the result is meant to transfer to hardware.
4. **Write the verdict script now**, not after the data. Use the `verdict` skill.
   Thresholds live in `GATES` and `CRITERIA` and must match §3 and §4 word for word.
5. **Positive-control the criterion on paper.** For each criterion, write one known-answer case
   and check by hand that the criterion returns the known answer. If it cannot, rewrite it now.
6. **Commit both files**, then freeze:

   ```bash
   git add docs/prereg/<id>.md experiments/<id>/verdict.py
   git commit -m "prereg: <id>"
   python <plugin>/scripts/rak_discipline.py freeze docs/prereg/<id>.md
   git add .rak/frozen/<id>.json && git commit -m "prereg: freeze <id>"
   ```

   `freeze` refuses uncommitted or modified files and refuses to re-freeze an id.
   **List under `frozen_files:` every file the verdict depends on besides the verdict script**: the scorer,
   thresholds, chance tables, task definitions, aggregation. They are hashed with the prereg. The hook, the
   verdict script and job packaging then refuse if any of them changed. A scorer that can be loosened after
   freezing makes the gate meaningless: a 10× looser scorer can still pass a positive control.
   **List under `frozen_trees:` every folder that defines a condition**, for example the plugin or prompt set
   that an arm loads at run time. Every file in it is hashed (caches excluded), and adding, removing or editing
   any file afterwards is refused. Freezing refuses a folder with uncommitted or untracked files.
   Hashes are computed with CRLF normalised to LF, so a Windows checkout does not "unfreeze" a file.
7. **Launch with the id.** Experiment commands carry `RAK_PREREG=<id>`:

   ```bash
   RAK_PREREG=<id> python train.py --seed 101
   ```

   With the hook installed, a command matching `experiment_patterns` in `.rak/discipline.json`
   is blocked without a frozen id, or when the prereg or verdict script changed after freezing.

## Rules

- Never edit a frozen prereg. A wrong threshold, a missed condition or a bug found later goes into
  an erratum in the results doc (`erratum` skill). Report the verdict under the registered rule too.
- Never re-freeze to "fix" a prereg after seeing data. Make a new id for a new run instead,
  and say in its §1 why the old one was superseded.
- Every configuration value the run depends on must be written into the run's own output
  (config dump, hash). A file name or a memory of "which run was which" fails silently.
- No default values for experimental conditions in launch scripts. A missing condition raises.
- Unknown CLI flags raise. A silently ignored flag runs a different experiment from the registered one.
- Read the source of the installed version before registering a mechanism. A branch or newer
  release may have a function your installed commit does not.

## Writing good criteria

- **Above the do-nothing baseline.** Compute what doing nothing scores. A threshold below it rewards
  standing still.
- **Binary, decided at episode end, separate from the reward.** A continuous quantity printed as a
  percentage is not a success rate.
- **At the decision granularity.** If the decision is per case, measure separation within a case
  (correct vs incorrect options), not only an aggregate.
- **Signed and in the right frame.** Measure the real quantity the claim is about, not a proxy
  coordinate that happens to be convenient.
- **Strict inequalities near a bound** are fragile; say what happens exactly at the threshold.
- **Grid end points are not limits.** If the threshold comes from a lookup table, check the table
  range is the physical range.

## Output

- `docs/prereg/<id>.md` (frozen), `experiments/<id>/verdict.py` (frozen), `.rak/frozen/<id>.json`.
- A one-paragraph message to whoever approves budget: question, arms, n, budget, stop line.

## Limits

- The launch guard matches command text against regexes. A launch that does not match a pattern
  (renamed script, a wrapper, `python -c`) is not caught. Keep `experiment_patterns` broad and put a
  `verify_frozen` call at the top of training entry points as well.
- Freezing proves the files did not change after the freeze commit. It does not prove the freeze
  happened before the data existed; keep raw outputs timestamped and synced off the machine.
