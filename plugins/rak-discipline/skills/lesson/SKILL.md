---
name: lesson
description: Turn a finished experiment line (including failed and refuted ones) into a lesson a student can follow, where every measured number is extracted from the run's logs by script rather than typed by hand. Use after a verdict, when an experiment line is closed or abandoned, or when asked to document what was learned.
license: Apache-2.0
compatibility: Template plus a stdlib Python extractor; works in any agent.
metadata:
  plugin: rak-discipline
  version: "0.1.0"
---

# Lesson

An experiment line is not finished when the verdict is written. It is finished when someone who was
not there can learn from it, including from the hypotheses that were wrong.

## Inputs

- The frozen prereg, `verdict.json`, the results doc with its errata.
- The run logs (small: summaries, json, csv; not checkpoints or videos).

## Steps

1. Create `lessons/<slug>.src.md` from `templates/lesson.md`, and `handson/<slug>/logs/` with the
   logs the lesson cites. Keep each log file small (well under a megabyte); large artifacts stay out of git.
2. Copy `templates/build_logs.py` to `handson/<slug>/build_logs.py` and add one `EXTRACTORS` entry per
   number: which log file, how to read it (json path or regex), how to format it.
3. Extract and render:

   ```bash
   python handson/<slug>/build_logs.py extract --logs handson/<slug>/logs --out handson/<slug>/numbers.json
   python handson/<slug>/build_logs.py check   --src lessons/<slug>.src.md --numbers handson/<slug>/numbers.json
   python handson/<slug>/build_logs.py render  --src lessons/<slug>.src.md --numbers handson/<slug>/numbers.json --out lessons/<slug>.md
   ```

   `extract` raises if a log is missing or a rule matches nothing. `check` fails on unknown keys and on
   bare decimals in the results section.
4. Write for a student: the question first, intuition before formulas, every formula term explained.
   Link concept notes instead of copying them.
5. Include **what was wrong along the way**: refuted hypotheses and errata, quoting the original wording.
6. Write self-check questions with checkable answers (compute, predict, find in a log), not "explain X".
7. Numbers quoted from papers are written literally with the paper cited; the same number must be in
   that paper's note.

## Rules

- No number in the results section is typed by hand. If a number is not in a log, it is not a result.
- "Measured" means it ran here. Numbers from a paper or a vendor are labelled as such.
- A lesson about a failed line is as valuable as one about a success; do not wait for a success to write it.
- Do not reorder or renumber an existing track on your own; insert with the next free `order` and
  let the track owner decide renumbering.

## Output

`lessons/<slug>.md` (rendered), its `.src.md`, `handson/<slug>/{build_logs.py,numbers.json,logs/}`.
