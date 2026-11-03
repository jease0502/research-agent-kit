---
title: "<lesson title>"
track: "<track id>"
order: 0
level: "intro | intermediate | advanced"
prereqs: []
status: draft
summary: "<one sentence>"
---

<!--
Source file of a lesson. Every measured number is written as {{key}} and filled in by
build_logs.py from numbers.json, which build_logs.py extracts from the run's logs.
Do not type a measured number by hand: `build_logs.py --check` fails on unknown keys and
warns on bare numbers in the results sections. Numbers quoted from papers are written
literally with the paper cited, and the same number must appear in that paper's note.
-->

# <title>

## What this lesson solves

The question, in one paragraph a student can follow without the prereg.

## Prerequisites

Links to earlier lessons and concept cards. Do not re-explain them here.

## Intuition first

Analogy or picture before any formula. Then the formula, with each term explained.

## What we ran

Arms, seeds and budget in one table, linking the prereg (frozen at `{{prereg_commit}}`).

## What happened

| Arm | Success rate | n |
|---|---|---|
| control | {{control_success}} | {{control_n}} |
| treatment | {{treatment_success}} | {{treatment_n}} |

Verdict per criterion as registered: {{verdict_C1}}.

## What was wrong along the way

Hypotheses that were refuted and errata, with the original wording. Students learn more from the
wrong turn than from the final number.

## Self-check

Questions with a checkable answer (compute this, predict that, which of these logs shows X),
not "explain Y".

## Next

Link the next lesson in the track.
