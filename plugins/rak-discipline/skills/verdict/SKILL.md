---
name: verdict
description: Write the verdict script of a pre-registered experiment before the data exists, and apply it unchanged afterwards - raw-value comparisons, PASS/FAIL/UNDETERMINED, strict input schemas, hashes in the output, write-once verdict files. Use when filling a prereg's criteria, when reading results of a frozen run, or when someone reports a number without saying which rule produced it.
license: Apache-2.0
compatibility: Template is plain Python 3.9+ with no dependencies; works in any agent. The read-blocking hook is Claude Code only.
metadata:
  plugin: rak-discipline
  version: "0.1.0"
---

# Verdict

The verdict script is the registered reading rule, executable. It is written with the prereg,
frozen with it, and is the only way results are turned into claims.

## Steps

1. Copy `templates/verdict.py` to `experiments/<id>/verdict.py`, set `PREREG_ID`.
2. Fill `GATES` (from prereg §3) and `CRITERIA` (from §4): metric key, comparison, threshold, min n.
3. Fill `EXPECTED_RESULT_KEYS` and `EXPECTED_EVIDENCE_KEYS` with every key the inputs may contain.
4. Test it on fabricated inputs **before freezing**: one input that must PASS, one that must FAIL,
   one with missing data that must be UNDETERMINED, one with an extra key that must raise.
   Delete the fabricated inputs afterwards; never commit them next to real results.
5. Commit and freeze together with the prereg.
6. After the run: `gate` (see `gate` skill), then

   ```bash
   RAK_PREREG=<id> python experiments/<id>/verdict.py judge --results results.json --out verdict.json
   ```

7. Copy the printed verdict lines into the results doc verbatim, with the `verdict.json` path.

## Rules the template enforces (do not remove them)

- **No rounding before comparing.** 0.0500001 is above 0.05 even though it prints as 0.05.
  Round only for display. A printed number that equals the threshold must say which side it is on.
- **Unknown flags and unknown keys raise.** A renamed metric or an ignored flag means you are
  judging something other than what was registered, and nothing else will tell you.
- **Three states.** Missing data, crashed runs and n below the minimum are UNDETERMINED, never
  folded into PASS or FAIL. Report how many runs were UNDETERMINED and why.
- **Hashes in the output.** `verdict.json` carries the prereg, verdict-script and results hashes.
  A verdict without them cannot be traced to what was registered.
- **Write once.** `--out` refuses to overwrite. A second judgement is a second file with a reason.
- **Refuses without a passing gate** (`GATE_FAIL`), and refuses if the prereg or the script changed
  after freezing.

## Reading a verdict honestly

- Report every registered criterion, including the ones that failed, in registration order.
- Descriptive quantities are labelled descriptive and carry no verdict.
- If a registered threshold turns out to be wrong, the verdict under the registered threshold is
  still reported, and the correction goes in an erratum with its own reasoning.
- "Partially passed" is not a verdict. Say which criteria passed, which failed, which were undetermined.
- An improvement that only shows up on the set used for selecting it is not evidence.
  Check that the reported split was not used to choose anything.

## Output

`verdict.json` (write-once, hashed) and the verdict lines pasted into the results doc.
