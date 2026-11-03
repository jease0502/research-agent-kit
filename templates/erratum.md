<!--
Erratum format. Append at the end of the results doc (or the prereg's results section), never
in place of the text it corrects. The text being corrected stays exactly as it was; the hook and
the pre-commit check refuse edits that remove or rewrite committed lines.
-->

## Erratum <N> (YYYY-MM-DD HH:MM, <when relative to the data: before any result / after gate / after verdict>)

**Corrects:** §<section> — quote the original sentence verbatim:
> <original sentence, unchanged>

**Correction:** <what is true instead, with numbers and the file they come from>

**Why it was wrong:** <the mechanism: wrong source, checked the wrong thing, rounded before comparing,
stale artifact, misread a log, ...>. If a check would have caught it, name the check.

**Effect on the verdict:** none / criterion C<k> changes from <X> to <Y> / undetermined until <...>.
A correction made after seeing results never changes a registered threshold; if a threshold was
wrong, say so here and report the verdict under the registered threshold as well.

**Evidence:** `<path/to/log or json>` (sha256 `<first 12>`)
