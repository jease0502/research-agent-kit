---
name: erratum
description: Correct a committed result, claim or judgement by appending a numbered erratum that quotes the original sentence verbatim, instead of editing or deleting it. Use whenever a committed results doc, prereg outcome, report or lesson turns out to be wrong, incomplete or misleading - including your own message that said something was done when it was not.
license: Apache-2.0
compatibility: Format works anywhere. Enforcement (append-only results docs) is a Claude Code hook plus a git pre-commit check.
metadata:
  plugin: rak-discipline
  version: "0.1.0"
---

# Erratum

Wrong judgements stay in the record, marked wrong. A reader who sees only the final text cannot tell
what was believed when, which decisions rested on the wrong version, or whether the fix is itself a
quiet rewrite. Keeping the original sentence makes all three visible.

## When

- A committed number was wrong (wrong file, wrong rule, rounded before comparing, stale artifact).
- A claim was stronger than the evidence (n too small, single seed, proxy metric).
- A collision or prior work found later changes what is new.
- A status message ("done", "verified", "committed") turns out to be false. Correct it in the place
  it was made, and in the results doc if it reached one.

## Steps

1. Do not touch the original text. With the hook installed, Edit/Write/MultiEdit that removes or
   rewrites a committed line of a file matching `results_globs` is blocked; shell edits, `rm` and `mv`
   naming such a file are blocked; and the git pre-commit check rejects anything else that reached the index.
2. Append a section from `templates/erratum.md` at the end of the doc:
   number, timestamp, **when relative to the data** (before any result / after gate / after verdict),
   the original sentence quoted verbatim, the correction, why it was wrong, effect on the verdict, evidence path.
3. Inline marker (optional, allowed because it only adds text): put `(see Erratum N)` on a new line
   right after the corrected paragraph. Do not change the paragraph itself.
4. If the correction changes a verdict, report both: the verdict under the registered rule and the
   corrected reading, and say which one downstream decisions should use.
5. Find every place that cited the wrong value (`grep` the number and the claim) and add a pointer there.
6. Commit with a message that says what was corrected: `results: <id> erratum 2 - control n was 4 not 5`.

## What counts as "why it was wrong"

Name the mechanism, not the mood. Good: "read the first 1,200 characters of the abstract; the numbers
were in the last third". "Compared the rounded value". "Checked that the file exists, not that it is
the new one". Bad: "mistake", "oversight". If a check would have caught it, name the check and add it
(see `docs/failure-modes.md`).

## Frontmatter and drafts

- Frontmatter (`updated:` and similar) may change; only the body is append-only.
- A results doc that has never been committed is a draft and can be edited freely. The rule starts at
  the first commit, so commit results docs early.

## Limits

- The hook sees tool calls, not intentions. A Python one-liner that rewrites the file passes the hook;
  the pre-commit check catches it when it is staged. Someone can still bypass git hooks with
  `--no-verify`; CI should run `rak_discipline.py check-append-only --staged` equivalents on pushes.
- Moving a paragraph counts as removing it (order matters). Add a pointer instead of moving.
