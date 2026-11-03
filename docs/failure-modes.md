# Failure modes of agent-run experiments

Recurring ways our agent-run research went wrong, rewritten without project names. Each entry
happened at least once in real use; several happened many times before a guard was added.
Format: **Symptom** (what you see) / **Cause** (what was actually going on) / **Guard** (what stops it now).
Entries marked ⚙ are enforced by code in this kit; the rest are checklists in the skills.

## A. Measuring the wrong thing

**A1. The criterion measures something else.** ⚙
- Symptom: a reasonable-looking criterion gives plausible numbers, and the conclusion is wrong.
  In one case three new criteria were each found to measure something else, including a joint-order
  check that failed even a policy known to work.
- Cause: the criterion was never shown a case with a known answer.
- Guard: a positive control through the same pipeline before any result is read (`gate`; `verdict judge` refuses without it).

**A2. A green light only means the thing you checked passed.**
- Symptom: "verified" followed by a wrong claim. For example, "the API truncates abstracts" was reported when
  the agent had printed only the first 1,200 characters itself, and the numbers were in the last third.
- Cause: the check tested a neighbouring property (file exists, not that it is new; first part read, not all of it).
- Guard: write down what the check actually tested next to the claim. Read whole inputs before concluding absence.

**A3. A stale value read as a live one.**
- Symptom: a pose, buffer or cached field is constant across steps, and every criterion built on it looks stable.
- Cause: a value is only refreshed on some code path (for example a camera pose that is not updated when
  the simulator is stepped manually).
- Guard: cross-check the quantity against an independent source (forward kinematics, the rendered image) once per pipeline.

**A4. Continuous metric printed as a success rate.**
- Symptom: "~56% success" for a behaviour that never actually completes the task (the agent holds the object forever).
- Cause: a continuous shaping quantity formatted as a percentage.
- Guard: success is binary, decided at episode end, computed separately from the reward (`prereg` §4).

**A5. Threshold below the do-nothing baseline.**
- Symptom: training converges to standing still, or "passes" with near-zero commands.
- Cause: the reward or threshold pays more for not moving than for trying under small commands.
- Guard: compute the do-nothing score first; every threshold must be above it (`gate`).

**A6. Evaluation contaminated by the environment.**
- Symptom: after changing a command distribution, every arm gets "worse" at once.
- Cause: the environment resampled the command mid-episode, overwriting the one the evaluation set.
- Guard: disable resampling during evaluation and assert the command every step.

**A7. Validation at the wrong granularity.**
- Symptom: an automatic judge agrees with labels case by case, yet cannot rank alternatives within a case.
- Cause: aggregate agreement hides that scores do not separate correct from incorrect options for the same input.
- Guard: measure within-case separation (correct vs incorrect), split by source type, before using a judge as a criterion.

**A8. A table edge read as a physical limit.**
- Symptom: a "maximum reach" of a mechanism that is simply the last entry of a lookup grid.
- Cause: the grid range was never compared to the model's real range.
- Guard: check that grids and sweeps cover the physical range; label grid-bounded results as such.

## B. Silent infrastructure failures

**B1. The process exits 0 after failing.**
- Symptom: a job "succeeded" and produced nothing, or produced a previous run's files.
- Cause: the simulator or app framework swallows exceptions and exits 0; child process exit codes are not reliable.
- Guard: success is defined by expected artifacts with fresh timestamps and expected content, never by exit code.

**B2. A stale artifact is more dangerous than a missing one.**
- Symptom: a sweep reports results for configurations that never ran.
- Cause: output paths reused across runs; the old file was read as the new one.
- Guard: one process per configuration, unique output paths, and a run id written inside every artifact.

**B3. "Not found" confused with "query failed".** (planned: rak-cloud waiter)
- Symptom: a watcher declared a cloud machine gone; the guard then deleted it together with the only copy of its log.
- Cause: credentials had expired; every query failed, and failure was treated as absence.
- Guard: only an explicit not-found counts as gone; logs are synced off the machine by the machine itself.

**B4. A safety mechanism that silently degrades.**
- Symptom: idle machines "self-deleted" but kept billing for disks.
- Cause: the machine's service account lacked delete permission; the guard fell back to shutdown, which looked similar.
- Guard: verify the permission at install time by testing it; the external waiter, not self-deletion, is the primary cleanup.

**B5. A dry run that checks only what it prints.**
- Symptom: dry run passed; the real create failed in every zone ("disk smaller than image").
- Cause: the dry run echoed parameters and never queried provider constraints.
- Guard: dry runs query the provider for every constraint the real call depends on (image size, quotas, credentials).

**B6. Headless or clean environments differ from the interactive one.**
- Symptom: a setup script fails in zero seconds on the remote machine with an obscure message; or the GPU is
  "not found" when the real problem is a missing graphics library.
- Cause: no terminal (`TERM` unset makes a `tabs` call fail under `set -e`), missing system libraries,
  local caches that hid downloads, compilers and resolver state.
- Guard: rehearse in a fresh container with an empty home and cache; set `TERM` explicitly in job scripts;
  read the last failing system call (strace) instead of the first error message.

**B7. Test fixtures that do not look like the real data.**
- Symptom: every unit test passes and the first real episode crashes; a benchmark on synthetic data overestimates speed 2×.
- Cause: synthetic fixtures with different field names or sizes; limits (file descriptors, memory) never reached.
- Guard: before launching anything paid, run the loader and one step on a real artifact.

**B8. The remote ran different code.**
- Symptom: a "new" experiment reproduces the old one exactly.
- Cause: a silently failing fetch on the remote plus an unknown flag that was ignored.
- Guard: compare the remote HEAD to the expected commit before running; unknown flags raise; bit-identical results to a previous run are a red flag.

**B9. Line endings change hashes.**
- Symptom: reported sha256 does not match the repository; a job script fails on the remote with `\r` errors.
- Cause: automatic CRLF conversion on one side.
- Guard: hash LF-normalised content (⚙ freeze does this); force LF for files sent to remote machines.

**B10. Idle compute nobody noticed.**
- Symptom: a GPU sat idle for hours after a crash; someone else noticed first.
- Cause: no watcher, or a watcher that only checked the process was alive.
- Guard: every GPU job gets a watcher that checks artifacts, process liveness and log progress, and notifies.

## C. Bookkeeping and claims

**C1. Experiment conditions living outside the artifact.**
- Symptom: two logs with identical hashes labelled as different conditions.
- Cause: the condition was encoded in a file name or remembered, not written into the output.
- Guard: every run dumps its full config and hash into its own output; no default values for conditions; missing ones raise.

**C2. One seed treated as the answer.**
- Symptom: "fixed" — then the same configuration and seed collapse on rerun.
- Cause: bimodal outcomes; a single run is one sample.
- Guard: register n and the claim's form ("k of n succeed"); claim a fix only after n consecutive successes.

**C3. Claims written from memory instead of the source.**
- Symptom: a draft says something the data in hand contradicts; a status message says "committed" for a commit that failed.
- Cause: writing from recollection; the stronger the reader's trust in a sentence, the less it was checked.
- Guard: before "done", re-read the artifact (`git log -1`, the file, the json); scale checking to how much the reader will rely on it.

**C4. The guard was loosened instead of the bug being fixed.**
- Symptom: a failing assertion turned green by changing the expected value.
- Cause: the cheapest edit that makes a check pass is to relax the check.
- Guard: write the repair order into the guard's message ("fix X; do not change the expected value"); when unsure, fail towards safe. ⚙ the hook fails closed on its own errors.

**C5. Novelty judged with your own vocabulary.**
- Symptom: a "novel" idea turns out to exist under another field's name; found two rounds late.
- Cause: searching your own terms only finds people using your terms.
- Guard: `collision-search` step 6 (renamed fields) and searching by mechanism, not application.

**C6. Metadata and the document disagree.**
- Symptom: a quoted paper does not contain the quoted claim.
- Cause: an identifier resolved to metadata of one paper and a PDF of another, or the source was read through a paraphrasing tool.
- Guard: compare the PDF title with the metadata first; quote verbatim; mark "not checked against PDF" otherwise.

**C7. Reading the source of the wrong version.**
- Symptom: a registered mechanism relies on a function the installed version does not have.
- Cause: reading the upstream main branch instead of the installed commit.
- Guard: grep the installed package on the machine that will run the job before registering.

## D. Multi-agent coordination

**D1. Shared index, wrong commit.**
- Symptom: a commit contains another session's half-finished files.
- Cause: several sessions share one working tree and git index; a bare `git commit` takes everything staged.
- Guard: path-scoped commits (`git commit -- <paths>`); check `git diff --cached --stat` before committing.

**D2. Messages to the wrong peer, or treated as approval.**
- Symptom: instructions reach a session with the same display name; a peer's "go ahead" is taken as the user's consent.
- Cause: names are not unique addresses; peers cannot grant permissions.
- Guard: address peers by unique reference; only the user approves actions that need approval.

**D3. Results written before the coordinator saw them.**
- Symptom: a registry or doc says "reported to lead" when it was not; two sessions write conflicting conclusions.
- Cause: writing the result is faster than reporting it.
- Guard: report to the coordinator first, write after the reply.

## E. Reinforcement-learning specific

**E1. Dense shaping that rewards hovering.**
- Symptom: the policy approaches the target and stays near it forever.
- Cause: a per-step "closer is better" bonus makes staying close more valuable than finishing.
- Guard: potential-based shaping (difference of potentials), which leaves the optimal policy unchanged.

**E2. Clipping and entropy bonus drive exploration noise up.**
- Symptom: action noise grows during training until behaviour collapses.
- Cause: actions clipped at the limits plus a Gaussian policy plus an entropy bonus: wider noise costs nothing at the bound.
- Guard: lower the entropy coefficient or bound the standard deviation; measure limit violations before the clamp.

**E3. Motion quality added after the fact.**
- Symptom: high success in simulation, joints chattering at full speed; adding rate limits later cannot recover it.
- Cause: smoothness and rate limits were not present in the first training run.
- Guard: rate limits and smoothness terms present from the first run; included in prereg §8 (sim-to-real).
