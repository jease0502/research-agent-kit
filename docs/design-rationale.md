# Design rationale

Why the kit insists on a few habits that cost time. Each section names the failure modes it answers, from
`docs/failure-modes.md` (A1 = section A, entry 1). The catalogue describes what went wrong; this page explains the
choice of remedy.

## Pre-register before running

**Answers:** A2 (a green light that only covered a neighbouring property), C1 (conditions living outside the
artifact), C2 (one seed read as the answer), C3 (claims written from memory), C4 (the check relaxed instead of the
bug fixed), E3 (properties added after the first run).

An agent that reads results before deciding how to read them will find a reading that works. It does not need bad
intent for this: it needs a threshold that is still adjustable, a metric that can be renamed, and a seed count that
can grow until something passes. We saw each of these.

What the prereg fixes in advance:
- the question, the arms and the seeds;
- each criterion as PASS / FAIL / UNDETERMINED, with a raw-value comparison and a minimum n;
- predictions with confidence;
- the budget and the stop line;
- what the run will not be able to say.

The verdict script is written at the same time and frozen with it. Freezing records hashes, so a later edit is
visible and refused. When something was wrong, the correction is an erratum, and the verdict under the registered
rule is still reported.

Why not just "be careful"? Because the costly cases were the ones where the agent believed it was careful (C3).
A rule has to hold on the days when judgement fails.

## Show the criterion a known answer first (positive control)

**Answers:** A1 (the criterion measures something else), A3 (a stale value read as live), A4 (a continuous quantity
printed as a success rate), A5 (a threshold below the do-nothing baseline), A6 (evaluation contaminated by the
environment), A7 (validation at the wrong granularity), B2 (stale artifacts).

None of these failures raises an error. A criterion reading a cached value, the wrong coordinate frame, or a
command the environment silently overwrote produces plausible numbers. The only reliable detector is a case whose
answer is already known, run through the same code at the same moment the criterion reads it. Four checks make up the gate:
- **Positive control:** can it see an effect that is definitely there?
- **Negative control:** does it stay quiet when nothing is there?
- **Control reproduction:** is the baseline the same baseline as last time?
- **Do-nothing baseline:** is every threshold above what standing still earns?

Two design choices follow:
- **The gate is enforced by the verdict script, not by the hook.** The script is in the data path, so it refuses
  whoever runs it. The hook only catches the agent's attempt early.
- **A gate must be able to fail.** We check this by breaking the pipeline once on purpose. The kit's own test suites do
  the same: each guard was removed in turn, and the tests had to turn red. A check that passes for a broken pipeline is decoration.

## Keep the wrong sentence; append the correction

**Answers:** C3 (claims from memory), C4 (relaxing the check), C5 (novelty judged with your own vocabulary),
C6 (metadata and document disagree), D3 (results written before the coordinator saw them).

When a committed result turns out wrong, rewriting it in place destroys three things:
- when the wrong belief was held;
- which decisions rested on it;
- whether the "fix" is itself a quiet rewrite.

An erratum keeps the original sentence verbatim, says what is true instead, names the mechanism of the error, states the
effect on the verdict, and points at the evidence. This has two effects:
- **On readers:** they can calibrate how much to trust the rest of the record. A record without corrections is not a
  sign that nothing went wrong.
- **On the agent:** naming the mechanism ("rounded before comparing", "read the stale file") turns a one-off fix into
  a check that can be added. Several entries in the failure-mode catalogue started as errata.

It is enforced in two places:
- **Before commit:** an Edit/Write that drops a committed line of a results doc is refused, and a pre-commit check
  catches anything else that reached the index.
- **Drafts are free:** the rule starts at the first commit.

## Spending decisions live outside the agent

**Answers:** B1 (exit code 0 after failure), B3 ("could not ask" read as "gone"), B4 (a safety mechanism that
silently degrades), B5 (a dry run that checks only what it prints), B6 (headless environments), B8 (the remote ran
different code), B9 (line endings), B10 (idle compute nobody noticed).

An agent that can create a VM will sometimes forget it, mis-read its state, or delete it before its outputs are safe.
The kit therefore moves each decision into code that the model does not edit during a run:
- **Precheck** queries the provider for every constraint the real call depends on.
- **Create** refuses a command without max-run, termination DELETE and disk auto-delete.
- **The job** judges steps by fresh outputs, not exit codes. It checks at start that it can delete itself, and it writes its
  status last, after the manifest and a verified sync.
- **The waiter** treats only not-found as gone, deletes only after verifying every file against the manifest, and leaves an
  unverifiable VM running and reported instead of guessing. max-run deletes it in the end.

Why not let the idle guard on the VM handle cleanup? Because its failure is silent. A guard without delete
permission falls back to shutdown, and a stopped VM looks handled while its disk keeps billing (B4). The guard
stays as a backstop, and the external waiter is primary.

## Numbers come from files, by script

**Answers:** A2, C1, C3; and the general observation that the most trusted sentences in a report are the least checked.

Verdicts are produced by the frozen script from result files, and lessons render their measured numbers from logs
(`build_logs.py`). A number typed by hand is the easiest kind to get wrong and the hardest to notice: it looks the
same as a measured one. The lesson checker flags bare decimals in results sections for that reason.

## Coordination: one writer per fact

**Answers:** D1 (shared index, wrong commit), D2 (messages to the wrong peer, or taken as approval), D3 (results
written before the coordinator saw them).

When several sessions share a working tree, the failure is rarely a merge conflict. It is a commit that silently
includes someone else's staged files, or two sessions writing different conclusions about the same run.
The kit's answer:
- commits are scoped to paths;
- results go to one coordinator before they are written down;
- a peer's message is information, never approval.

Whole-tree staging and committing (`git add -A` / `.`, `git commit -a`) are blocked by the rak-team hook.
"Report before writing" and "a peer is not the user" are still conventions; the architecture page lists them as such.

## What we chose not to do

- **Fully automatic papers.** Choosing the question, approving budget and choosing direction stay with people.
  The kit prepares the evidence those decisions need.
- **Rules the model is merely asked to follow, where a script can hold them instead.** Where a rule is still a
  convention, we say so rather than imply otherwise.
- **Hiding uncertainty in defaults.** Configuration has no defaults for anything that differs between users, and unknown
  keys raise, because a default that works on one machine fails silently on the next (C1, B8).
