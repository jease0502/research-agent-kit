# Design takeaways for research-agent-kit

**Proposals, not implemented.**

These are proposals, not commitments. Each one names the source mechanism (quotes in [related-work-sources.md](related-work-sources.md)), how it could
map onto rak, and what could go wrong. None has been prototyped.

## 1. A sealed final evaluation, bound to a frozen candidate

**Source.** The Agentic Scientist separates a search evaluator from a final evaluator. Before a run starts, a judge
"verifies that the search and final evaluators are independent and use disjoint data" (paper §3.1). Final
evaluation "uses the frozen program", and the run cannot "choose another program after final evaluation"
(`docs/no_winner_studies.md`).

**Mapping.** rak has no held-out stage today; the verdict is read from whatever results the run produced.
- The prereg gains a `final_eval:` block: the final evaluator and a manifest of the final data go under
  `frozen_files`.
- `verdict.py` gets a `final` step. It needs a gate PASS, records the candidate commit once in a write-once
  `.rak/final/<id>.json`, and refuses a second final run for the same prereg id.
- A cheap deterministic check for disjointness: hash every file or row in the search and final manifests and
  refuse on any overlap.

**Risk.**
- The freeze proves "not changed since", not "never looked at". An agent that can read the final data can still
  tune on it. Only the L1 sandbox (final data not mounted during search) closes that.
- "One final run per id" invites opening a new prereg id for each retry. A per-question ledger that lists every id
  would need to come with it.
- Hash overlap only catches exact duplicates, not near-duplicates or leaked labels.

## 2. Numbers and citations in prose must resolve to a source before a draft leaves

**Source.** The Agentic Scientist's writer produces "a claim-to-source map". Its validation checks "reject any
citation key or claim-to-source link that does not resolve to a retrieved entry" (§3.5, §F.1). Its docs say
"fabricated or altered sources still fail the final-evidence check" (`docs/evaluation_evidence.md`).

**Mapping.**
- rak's lesson checker already flags bare decimals in results sections. Extend it to results docs and drafts.
  Every number must carry a pointer, such as `verdict.json#/criteria/0/value` or `logs/x.txt:L42`, that resolves
  and matches the number.
- Make `rak cite-check` a pre-commit or hook gate on a `drafts/` path. `architecture.md` currently says of it:
  "It is not a hook: nothing forces it to be run before a draft leaves".

**Risk.**
- Resolution proves a number was copied from somewhere, not that it was read correctly. Even with an API-only
  bibliography, Sakana's authors still had to remove "several citations that did not support the corresponding
  claims" by hand (§4.3).
- v3 catches overclaiming with an LLM audit agent. By rak's own rule that is a classifier, not enforcement, so it
  could only be advisory.
- False positives: years, hyperparameters and section numbers look like results.

## 3. Mark which numbers the evaluator computed and which the agent reported

**Source.** In The Agentic Scientist, the evaluator owns `evaluation_evidence.json`. "Candidate diagnostic numbers
and timeseries are explicitly **unverified**, even inside an evaluator-authored file." "Missing broker measurements
are `null`, never fabricated zeroes." The final manifest "seals evidence through `results_tree_sha256`"
(`docs/evaluation_evidence.md`).

**Mapping.**
- `verdict.json` records a provenance for each value: `evaluator` if the frozen verdict script or scorer computed it
  from raw files, `reported` if it was copied from an agent-written log.
- The gate and verdict accept only `evaluator` values for criteria.
- `verdict.json` already stores the input hash. Making that a hash of the whole results tree is a small change.

**Risk.**
- This is a schema change: the template, the checker, the docs and existing examples have to change together.
- More friction for small projects where the scorer and the training script are the same file.

## 4. Controls for protocol tampering and leakage, not only for the metric

**Source.**
- The Agentic Scientist: in two of three runs with one agent, "the agent also modified the test-time evaluation
  procedure itself", and "Neither the evaluator nor the rubric gates flagged these programs" (§6.3).
- Meta-Harness, which searched and evaluated on the same TerminalBench-2 tasks, ran "regex-based audits for
  task-specific string leakage into evolved harnesses" (§4.3).
- The Harness² README warns that executors can reach "benchmark answers and grading criteria" unless network access
  is restricted.

**Mapping.**
- rak's gate has positive and negative controls for the metric. Add an optional **tamper control**: a candidate
  that deliberately changes the evaluation protocol (majority voting, more samples, a swapped eval set) must make
  the pipeline report FAIL or refuse.
- An optional leakage scan: grep agent-written code for strings from the held-out set before the verdict is read.
- A prereg field for hosts the run must not reach, enforced by the L1 egress allowlist.

**Risk.**
- A tamper control catches only the tampering someone thought of. That is the limit v3's authors state:
  rubrics "check only the criteria they enumerate".
- A regex scan catches verbatim strings only.
- A domain allowlist is not "no exfiltration" (rak's own `harness-landscape.md` §2).
- Each control is more work per prereg.

## 5. Keep lessons only with evidence; if rak ever tunes its own prompts, keep the rules outside the tuned surface

**Source.**
- Harness²'s harnessing-level recursion: "Lessons are retained only when supported by execution contrasts;
  selecting an output alone does not establish transferability", and "When evidence is insufficient, reflection
  adds no new experience entry" (§2.3). Each library entry has an `EXPERIENCE.md` with "the applicable situation,
  lessons, and supporting evidence".
- Both Harness² and Meta-Harness optimize the harness automatically. In Harness², "guardrails" is one of the
  editable components.

**Mapping.**
- (a) rak's erratum → lesson → failure-mode catalogue could adopt Harness²'s rule. An entry must cite a contrast
  (a before/after run, or the erratum's evidence) or it is not added. This fits `design-rationale.md`
  ("Several entries in the failure-mode catalogue started as errata").
- (b) If rak's skill texts are ever tuned automatically, Harness²- or Meta-Harness-style, the editable surface must
  exclude the hooks, `rules.json`, verdict scripts and frozen files. P1 already denies MCP file-tool writes there.
  The tuning run is itself a preregistered experiment with a held-out split.

**Risk.**
- Tuning skills against the fabrication-audit score is Goodhart-prone, which is why (b) requires a held-out split.
  Meta-Harness's TerminalBench-2 result shows how easy it is to skip one: "we perform search and final evaluation
  on the same 89-task benchmark".
- Harness²'s own evidence is "sensitive to execution variability and shared model biases" (Appendix F).
- Harness² supports OpenCode and Codex executors, not Claude Code, so (b) would need porting or a different tool.
- P1 is "a speed bump" (`policy-engine.md`) until L1 exists. An optimizer with shell access could still reach the
  rules.
