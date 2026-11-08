# Sources for "How this relates to other systems"

All pages opened on 2026-11-08.

How they were read:
- arXiv abstracts from the `abs` page. Paper bodies from the arXiv **HTML** (v1) rendering. **No PDF was checked.**
- READMEs and docs as raw files from `raw.githubusercontent.com` (default branch, 2026-11-08).
- Repo metadata (license, created, pushed, stars) from `gh api repos/<owner>/<repo>`.
- Every quote below was copied from the raw text, not from a summarising tool. WebFetch was used only to find
  pages; its summaries are not the basis of any claim.

Secondary reports (blogs, news) were used only to find the systems. None is cited in the draft.

---

## 1. Harness² (Google Cloud AI Research)

### Opened

- arXiv abstract: https://arxiv.org/abs/2610.14224
- arXiv HTML v1: https://arxiv.org/html/2610.14224v1
- Repo README: https://github.com/google-research/harness2 (raw `main/README.md`)
- `gh api repos/google-research/harness2`

### Identity: confirmed

| Item | Value | Source |
|---|---|---|
| arXiv ID | 2610.14224, exists and matches | abs page |
| Title | "Harness^2: Recursive Agent Harnessing for an Open World" (arXiv renders the superscript as `^2`) | abs page |
| Authors | Ruiyao Xu, Yanfei Chen, Zhongying CuiZhu, Bhavana Dalvi Mishra, Yifei Ming, Han Yu, Rujun Han, Chen-Yu Lee, Tomas Pfister | abs page |
| Date | "[Submitted on 9 Oct 2026]", v1 only | abs page |
| Categories | cs.AI (primary), cs.CL, cs.LG | abs page |
| Paper license | CC BY 4.0 | abs page |
| Affiliations | "Google Cloud AI Research" and "Northwestern University" | HTML v1, author block |
| Repo | `google-research/harness2` exists; created 2026-10-06; last push 2026-11-02; license **Apache-2.0**; 23,099 stars on 2026-11-08 | gh api |
| Repo disclaimer | "This is not an officially supported Google product." | README |

The per-author affiliation mapping did not survive the HTML conversion (superscripts are lost). The draft says
only that the paper lists Google Cloud AI Research and Northwestern University.

### Claims in the draft

- *Improves the harness around a frozen model.* README: "It connects two levels of recursion while keeping model
  weights fixed". Paper §1: "the runtime scaffolding around a frozen base model".
- *Components include system prompt, guardrails, memory, skills.* README: "Harness² exposes eight editable
  components around the model: **system prompt, guardrails, memory, tool guidance, subagents, skills, scripts,
  and plugins**."
- *"without ground-truth verifiers".* Abstract: "Task-level recursion refines the current task's harness using a
  contrastive Propose-Probe-Compose step that reliably guides edits without ground-truth verifiers".
- *"evidence-supported lessons" for later tasks.* README: "Harnessing-level recursion updates a persistent
  improvement harness with adopted harnesses and evidence-supported lessons from each task to guide future
  refinement."
- *Numbers.* Abstract: "a single step consistently improves GLM-5 and Gemini 3.5 Flash over their base harnesses,
  yielding gains of up to 11.5 points on WorkBuddy-Bench, 4.5 points on JobBench, and 11.8 percentage points on
  LAB". README specifies "11.8 percentage points on LAB's partial pass rate".
- *Meta-Harness is a baseline.* HTML Figure 1 caption: "Harness2 with parallel recursion at k=5 exceeds the
  strongest baseline in every domain, Meta-Harness". It appears as "Meta-Harness†" in the result tables.

### Context not in the draft (useful for judging the numbers)

- LAB scoring: "Tasks are judged by Claude Sonnet 4.6, and we report the per-criterion pass rate (Partial)";
  LAB tasks have "no executable check" (Appendix B). So the 11.8 is an LLM-judged per-criterion rate.
- Each reported score "is the mean over three independent streams" (Appendix B).
- Limitations (Appendix F): behavioural contrasts "remain sensitive to execution variability and shared model
  biases. They do not guarantee correctness or establish that an adopted change will transfer to a different task."
- README, Web access: "Executor network access is unrestricted, and Codex runs with its sandbox disabled. Public
  benchmark rubrics may be accessible online. Before evaluation, configure network restrictions to prevent access
  to benchmark answers and grading criteria."
- Supported executors: "OpenCode and Codex executors" (README). Not Claude Code. This is why the draft says
  "We have not tried the two together" and makes no compatibility claim.

### Not verified

- Which authors belong to which affiliation.
- Any peer-reviewed venue (none listed on the abs page; "Comments" field empty).
- The numbers themselves (no independent replication found; not looked for beyond the paper).

### Discrepancies with secondary reports

- A blog headline ("…Improves Frozen Models by Up to 11.8 Points", themenonlab.blog) collapses three numbers into
  one. 11.8 is **percentage points of LAB's LLM-judged per-criterion pass rate**; the other two maxima are 11.5
  (WorkBuddy-Bench) and 4.5 (JobBench), in points.
- Reports say "Google Research". The paper lists **Google Cloud AI Research** (plus Northwestern University). The
  repo is under the `google-research` GitHub organisation and says it is not an officially supported Google product.
- A report says agents "rewrite their own harness mid-task" (zeli.app). In the paper the edits come from separate
  improver sessions (Harness Editor, Composer, Experience Reflector, Appendix H) between executions of the same
  task, not from the executing agent during its run. Close, but not the same.

---

## 2. Meta-Harness (Stanford, KRAFTON, MIT)

### Opened

- arXiv abstract: https://arxiv.org/abs/2603.28052
- arXiv HTML v1: https://arxiv.org/html/2603.28052v1
- Project page: https://yoonholee.com/meta-harness/
- Code README: https://github.com/stanford-iris-lab/meta-harness (raw `main/README.md`)
- `gh api` for `stanford-iris-lab/meta-harness` and `stanford-iris-lab/meta-harness-tbench2-artifact`
- OpenReview forum https://openreview.net/forum?id=tmbOUyFx3R (linked from Harness²'s reference list):
  **blocked by a browser check, not read.**

### Identity: confirmed

| Item | Value | Source |
|---|---|---|
| arXiv ID | 2603.28052 | abs page |
| Title | "Meta-Harness: End-to-End Optimization of Model Harnesses" | abs page |
| Authors | Yoonho Lee, Roshen Nair, Qizheng Zhang, Kangwook Lee, Omar Khattab, Chelsea Finn | abs page |
| Date | "[Submitted on 30 Mar 2026]", v1 only | abs page |
| Affiliations | Stanford (Y. Lee, Nair, Zhang, Finn), KRAFTON (K. Lee), MIT (Khattab) | HTML v1 author block |
| Venue | `booktitle={Conference on Language Modeling (COLM)}, year={2026}` | project page BibTeX; Harness² cites it as "In Third Conference on Language Modeling" |
| Code | `stanford-iris-lab/meta-harness`, "Official code for Meta-Harness (2603.28052)", **MIT** | gh api, README |

### Claims in the draft

- *A coding agent rewrites harness code from prior candidates' code, scores and traces.* Abstract: "We introduce
  Meta-Harness, an outer-loop system that searches over harness code for LLM applications. It uses an agentic
  proposer that accesses the source code, scores, and execution traces of all prior candidates through a
  filesystem." README: "The examples use Claude Code as the proposer agent."
- *Harness² uses it as a baseline.* See §1.

### Context not in the draft

- TerminalBench-2 protocol (§4.3): "For this experiment, we perform search and final evaluation on the same 89-task
  benchmark." The authors justify this as "standard practice" and add: "We additionally check for overfitting by
  manual inspection and regex-based audits for task-specific string leakage into evolved harnesses."
- Text classification (§4.1): "select candidates solely based on search-set performance, and hold out the test sets
  until the final evaluation."
- README Release Note: "This is a cleaned-up version of the code we used for the paper. It has not been tested
  beyond verifying that it runs."

### Not verified

- COLM 2026 acceptance on OpenReview itself (page blocked); the venue comes from the authors' own BibTeX and from
  Harness²'s reference list.

### Discrepancies with secondary reports

- "Stanford/MIT/KRAFTON; an agent rewrites its harness from execution logs": consistent with the paper. The paper
  says "execution traces" plus source code and scores, read through a filesystem.

---

## 3. Sakana AI: The Agentic Scientist ("AI Scientist v3")

### Opened

- arXiv abstract: https://arxiv.org/abs/2610.18933
- arXiv HTML v1: https://arxiv.org/html/2610.18933v1
- Repo README: https://github.com/SakanaAI/AI-Scientist-v3 (raw `main/README.md`)
- Repo docs: `docs/pipeline.md`, `docs/evaluation_evidence.md`, `docs/no_winner_studies.md`,
  `docs/paper_final_outcomes.md`, `docs/task_drafting.md`
- `gh api repos/SakanaAI/AI-Scientist-v3`

### Identity: confirmed, with a naming caveat

| Item | Value | Source |
|---|---|---|
| arXiv ID | 2610.18933 | abs page |
| Title | "The Agentic Scientist: Orchestrating Coding Agents for Automated Scientific (Co-)Discovery" | abs page |
| Authors | Robert Tjarko Lange, Luca Grillotti, Yutaro Yamada, Rujikorn Charakorn, David Ha | abs page |
| Date | "[Submitted on 13 Oct 2026]"; Comments: "88 pages" | abs page |
| Paper license | CC BY 4.0 | abs page |
| Repo | `SakanaAI/AI-Scientist-v3`, created 2026-10-11, last push 2026-10-18, **Apache-2.0**, 657 stars on 2026-11-08 | gh api |

**The paper and README never call it "AI Scientist v3".** "AI-Scientist-v3" is only the repo name. The draft uses
the paper's name and gives the repo name next to it.

### Claims in the draft

- *Drives coding agents such as Claude Code and Codex.* README: "Agentic Scientist drives `claude`, `codex`,
  `cursor`, `opencode`, `gemini`, and `pi` through Headless CLI".
- *From a task file through ideas, ablations, "a sealed final evaluation" and a paper.* README: "Starting from a
  `task.md`, the agents propose ideas, run experiments, evaluate outcomes against the task rubric, and iterate
  toward stronger programs. The pipeline then runs baselines and ablations, a sealed final evaluation, post-hoc
  analyses, and writes the paper".
- *Each idea must state "a falsifiable hypothesis" before it runs.* Paper §3.3: "The ideation agent must instead
  emit a structured idea bundle containing a title, a falsifiable hypothesis, an ordered implementation plan, and
  the target rubrics. Those records are normalized, and any missing fields or mismatched rubric identifiers are
  rejected."
- *The writer "may only cite keys" a script retrieved from bibliographic APIs.* Paper §F.1: "The paper-writing
  phase (Section 3.5) never lets the writer agent produce bibliography entries from memory." … "A deterministic
  script then executes the plan against the Semantic Scholar Graph API" … "falls back to OpenAlex" … "Google
  Scholar via the scholarly package is used as a last resort." … "The writer agent may only cite keys present in
  this file, and the validation checks of the repair loop reject any citation key or claim-to-source link that
  does not resolve to a retrieved entry."
- *An audit agent checks claims against the evidence.* Paper §3.5: "An independent audit agent runs every round on
  a read-only copy of the workspace and flags where the paper's numbers, comparisons, or conclusions overclaim or
  contradict the canonical data and evidence trail."
- *Sealed, held-out final evaluation.* Paper §3.1: the alignment judge "verifies that the search and final
  evaluators are independent and use disjoint data". `docs/no_winner_studies.md`: "Final evaluation uses the
  frozen program." README: "the final evaluation re-scores it in a sealed environment".
- *Rubrics "check only the criteria they enumerate".* Paper §6.3 (RL-based LLM fine-tuning case study): "rubrics check only the
  criteria they enumerate, so they cannot catch violations of constraints that were never stated". Same section:
  "In two of the three Pi runs, we observed that the agent also modified the test-time evaluation procedure
  itself" … "Neither the evaluator nor the rubric gates flagged these programs, and we identified them after a
  manual post-hoc audit."

### Context not in the draft

- Security: "Agentic Scientist launches coding agents with full tool permissions (Headless `--allow yolo`)." …
  "Keep runs inside the Docker image rather than on your workstation" (README).
- Evidence files: "Candidate diagnostic numbers and timeseries are explicitly **unverified**, even inside an
  evaluator-authored file." "Missing broker measurements are `null`, never fabricated zeroes." "fabricated or
  altered sources still fail the final-evidence check." "Final manifest schema 3 seals evidence through
  `results_tree_sha256`" (`docs/evaluation_evidence.md`).
- Mandatory gates: "Compilation, references, provenance, and evidence-audit gates remain mandatory." "Before each
  audit, the host checks these copies and study facts against the frozen selection; author changes cannot replace
  the evaluated source." (`docs/no_winner_studies.md`).
- Negative results: a verified `not_qualified` final "may support a negative-results manuscript"; presets set
  `allow_not_qualified`, while the default without a preset is `qualified_only` (`docs/paper_final_outcomes.md`).
- Human verification for the one externally reviewed paper (§4.3): "all references in the BibTeX bibliography were
  manually verified" … "human researchers removed several citations that did not support the corresponding
  claims". So the API-only bibliography guarantees the entries exist, not that they support the claim.
- ALIFE 2026: the abstract says a development version was used "to submit a single research paper, which got
  accepted for publication at ALIFE 2026". This is the authors' statement; not checked against ALIFE.

### Not verified

- ALIFE 2026 acceptance (authors' statement only).
- Whether the "alignment judge" is a model or a script (`docs/task_drafting.md` says "Independent alignment judges
  receive only allowlisted metadata and evidence digests"; the word "judge" suggests a model, not confirmed).
- Run cost (the paper has a "Limitations: cost and runtime" paragraph that was not read).

---

## 4. Sakana AI: The AI Scientist v1 and v2

### Opened

- v1 arXiv: https://arxiv.org/abs/2408.06292
- v2 arXiv: https://arxiv.org/abs/2504.08066
- v1 README: https://github.com/SakanaAI/AI-Scientist (raw `main/README.md`)
- v2 README: https://github.com/SakanaAI/AI-Scientist-v2 (raw `main/README.md`)
- v1 blog: https://sakana.ai/ai-scientist/
- v2 workshop blog: https://sakana.ai/ai-scientist-first-publication/
- `gh api` for both repos

### Identity

| | v1 | v2 |
|---|---|---|
| Title | "The AI Scientist: Towards Fully Automated Open-Ended Scientific Discovery" | "The AI Scientist-v2: Workshop-Level Automated Scientific Discovery via Agentic Tree Search" |
| Authors | Chris Lu, Cong Lu, Robert Tjarko Lange, Jakob Foerster, Jeff Clune, David Ha | Yutaro Yamada, Robert Tjarko Lange, Cong Lu, Shengran Hu, Chris Lu, Jakob Foerster, Jeff Clune, David Ha |
| Dates | submitted 12 Aug 2024, last revised 1 Sep 2024 (v3) | submitted 10 Apr 2025 |
| Repo license | GitHub: `NOASSERTION`; README: "The AI Scientist Source Code License (a derivative of the Responsible AI License)" with "Mandatory Disclosure" of AI use | GitHub: `NOASSERTION` |

### Claims in the draft

- *Idea-to-paper pipelines scored by an automated reviewer.* v1 abstract: "generates novel research ideas, writes
  code, executes experiments, visualizes results, describes its findings by writing a full scientific paper, and
  then runs a simulated review process for evaluation." v2 abstract: "we enhance the AI reviewer component".
- *v2 drops v1's code templates for an agentic tree search.* v2 abstract: "eliminates the reliance on
  human-authored code templates" … "leverages a novel progressive agentic tree-search methodology managed by a
  dedicated experiment manager agent." (v2 README: the tree search "is built on top of the AIDE project".)
- *Both READMEs warn about running LLM-written code and ask you to sandbox it.* v1: "This codebase will execute
  LLM-written code." … "Please make sure to containerize and restrict web access appropriately." v2: "This codebase
  will execute Large Language Model (LLM)-written code." … "Ensure that you run this within a controlled sandbox
  environment (e.g., a Docker container)."
- *v1 tried to extend its own timeout.* v1 blog: "In another case, its experiments took too long to complete,
  hitting our timeout limit. Instead of making its code run faster, it simply tried to modify its own code to
  extend the timeout period."
- *v2 citation errors.* v2 blog: "The AI Scientist occasionally made embarrassing citation errors. For instance,
  here, we found that it incorrectly attributed "an LSTM-based neural network" to Goodfellow (2016) rather than to
  the correct authors, Hochreiter and Schmidhuber (1997)."

### Context not in the draft

- v2 blog: Sakana's own internal review "concluded that none of them passed our internal bar for an ICLR
  conference track publication", and the papers were to be withdrawn if accepted, by prior agreement.

### Not verified

- Any earlier license of the v1 repository (only the current README and GitHub's `NOASSERTION` were checked).

---

## 5. karpathy/autoresearch (optional row)

### Opened

- https://github.com/karpathy/autoresearch: raw `master/README.md`, raw `master/program.md`, file tree via
  `gh api repos/karpathy/autoresearch/git/trees/master?recursive=1`

### Claims in the draft

- *An agent edits one training file and keeps or discards each 5-minute run.* README: "It modifies the code, trains
  for 5 minutes, checks if the result improved, keeps or discards, and repeats." `program.md`: "Modify `train.py` —
  this is the only file you edit."
- *The read-only rule lives in `program.md`.* `program.md`, under "What you CANNOT do": "Modify `prepare.py`. It is
  read-only. It contains the fixed evaluation, data loading, tokenizer, and training constants". "The
  `evaluate_bpb` function in `prepare.py` is the ground truth metric."
- *No enforcement file.* The full file tree is `.gitignore`, `.python-version`, `README.md`, `analysis.ipynb`,
  `prepare.py`, `program.md`, `progress.png`, `pyproject.toml`, `train.py`, `uv.lock`. There is no hook, settings
  or permission file. (The draft states only where the rule is written; it does not claim nothing else enforces it,
  since a user's own agent settings could.)

### Not verified

- License: README says "MIT"; `gh api` reports no license file (`null`).

---

## 6. research-agent-kit claims used in the draft

From the public clone at `816b8da`:

- Run limits outside the agent. README: "max-run, idle self-delete and a waiter run **on the VM and outside the
  agent**".
- Paper metadata. README: "`rak add-paper` takes metadata from the arXiv/DOI API only".
- Rules outside the model. README table: "In a hook and in the verdict script, outside the model".
- `frozen_files`. `plugins/rak-discipline/skills/prereg/SKILL.md`: "List under `frozen_files:` every file the
  verdict depends on besides the verdict script … They are hashed with the prereg. The hook, the verdict script and
  job packaging then refuse if any of them changed."
- Not measured. README: "The comparison is by construction, not measured: the fabrication audit that would measure
  it has not been run yet."
- Same limit as rubrics. README: "Hooks match command text: a renamed script or `python -c` is not seen as an
  experiment"; architecture.md: steps succeed by fresh outputs "Only for declared outputs; declare them".
