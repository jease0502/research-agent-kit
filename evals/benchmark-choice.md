# Public benchmark: MLE-bench Lite or PaperBench Code-Dev?

Design note, 2026-10-31. **Nothing was run and nothing was spent.** Every requirement below was read from the official repositories and papers on 2026-10-31.

- The two papers' numbers were checked verbatim against the arXiv HTML: MLE-bench arXiv 2410.07095, PaperBench arXiv 2504.01848.
- The repository facts were checked against the raw READMEs, the split files and the GitHub license API.
- Cost lines marked *estimate* are our arithmetic on those numbers. They are not measurements.

## What each one is

| | MLE-bench, Lite (= the Low-complexity split) | PaperBench Code-Dev |
|---|---|---|
| Task | 22 Kaggle competitions; the agent submits a CSV, graded by the competition metric (medals) | replicate an ICML 2024 paper's code from scratch; an LLM judge grades only the Code Development rubric items |
| Size | 22 of 75 competitions. Low = "an experienced ML engineer can produce a sensible solution in under 2 hours excluding the time taken to train any models" (paper §2.1) | 20 papers. The repo also ships splits `debug` (1), `dev` (3), `lite` (5), `human` (5) |
| Official protocol | 24 h per competition, ≥ 3 seeds, report mean ± SEM of any-medal % (README) | the paper runs 3 per paper; full PaperBench uses 12 h rollouts; Code-Dev rollouts "can be made to run for half the duration" (paper §7) |
| Hardware | "36 vCPUs with 440GB RAM and one 24GB A10 GPU" (README); 4095 GiB SSD in the paper | **no GPU required**: "You don't need a GPU to run the reproduction step" (README). Agent GPU optional |
| Data | 158 GB for Lite, against 3.3 TB in full (README). Needs a Kaggle account and API token, and accepting each competition's rules | git-LFS checkout of `project/paperbench/data` |
| Grading cost | none (deterministic metric) | LLM judge, default o3-mini SimpleJudge: "around $10 USD per paper" for Code-Dev, against $66 for full PaperBench (paper §4.1). Needs an **OpenAI** key (`GRADER_OPENAI_API_KEY`). Judge F1 0.83 on JudgeEval for the full rubric (paper) |
| Infrastructure | Docker image `mlebench-env`; agents run in containers | Docker plus nanoeval/alcatraz; custom solvers subclass `PythonCodingSolver` (README) |
| License | repository LICENSE text is MIT. GitHub reports `NOASSERTION`, but the file starts "MIT License, Copyright (c) 2024 OpenAI". Competition data follows each Kaggle competition's rules | `openai/frontier-evals`: MIT (GitHub API). Paper texts are the authors'; we would not redistribute them |
| Claude agents already on it | yes: the README leaderboard lists Claude-based agents, so third-party agents are accepted | the paper evaluated Claude 3.5 Sonnet with its own BasicAgent. A Claude Code solver would be ours to write |

## Cost per arm (estimates)

We compare two arms, as in the fabrication audit: with and without `rak-discipline`. Every figure below is **per arm**; double it for the comparison.

**MLE-bench Lite, official protocol** (22 competitions × 3 seeds × 24 h):

- **Compute: 1,584 GPU-hours.**
  - At our own conservative planning figure of US$2.0 per VM-hour for a one-L4 machine, that is about US$3,200.
  - That machine has far less than the 440 GB of RAM the benchmark specifies. A machine that matches the spec costs more; we have not priced it.
  - GCP offers no A10; L4 is the nearest 24 GB card.
- **Tokens, scaled from the paper's o1-preview + AIDE figure** (127.5M input and 15.0M output tokens per seed of 75 competitions):
  - about 112M input and 13M output per arm;
  - on `claude-opus-5-5` at list price ($4 / $20 per million), between about US$270 (if most input is cached reads) and US$710 (if none is).
  - A Claude Code agent running 24 h may use a very different number of tokens than AIDE. Unknown until measured.
- **Total: roughly US$3,500–4,000 per arm, about US$7,500 for the comparison**, plus 158 GB of data and days of wall-clock time.

**PaperBench Code-Dev, 20 papers × 3 runs**:

- **Judging**: 60 × about US$10 = about US$600, on OpenAI's API.
- **Agent**:
  - the paper puts an o1 IterativeAgent 12 h rollout at $400 per paper;
  - Code-Dev at half duration gives "$4000 USD per eval run" of 20 papers;
  - so about US$12,000 per arm at o1 pricing for 3 runs.
  - With Claude Code, unknown until measured. At the fabrication audit's assumed US$1–3 per short run, a 6 h rollout could plausibly cost tens of dollars. That is an assumption, not a figure.
- **Compute**: CPU containers only.

**PaperBench Code-Dev, `lite` split (5 papers) × 3 runs**:

- Judging about US$150 per arm.
- Agent cost is a quarter of the 20-paper figure.
- The split exists in the repository, but the README does not describe how it was chosen. **Reporting on it is not comparable to the paper's numbers.**

## Recommendation

**PaperBench Code-Dev, starting with the `dev` split (3 papers) as a pilot, then the 20 papers if the pilot works.** Not MLE-bench Lite. The reasons:

1. **Cost and hardware.** Code-Dev needs no GPU, and its judge bill is about US$600 per arm for the full set. MLE-bench Lite's official protocol is about 1,600 GPU-hours per arm on a 440 GB-RAM machine. That is well past the "ask first" line in our own spending rules, and two orders of magnitude above the fabrication audit.
2. **Cross-family review comes for free.** The judge is an OpenAI model grading a Claude agent, which is the "different model family as reviewer" idea in plan §7. Its weakness is documented: it is non-deterministic, with F1 0.83 on the full rubric.
3. **It is closer to what the kit does.** Read a paper, implement it, record it, rather than tune a Kaggle submission.

What it does **not** give us, and why the fabrication audit stays the main evidence:

- **Code-Dev does not check results.** It grades whether the code implements the paper, not whether the reported numbers are true. Our core claim is about traceable numbers and honest reporting, and no public benchmark here measures that. A Code-Dev score tells readers the kit does not cost capability; the fabrication audit is what tests the claim.
- **The judge needs an OpenAI key** and grades with a model we do not control.
- **We must write a solver** that runs Claude Code inside their container runtime. Whether Claude Code and our plugins run cleanly inside alcatraz is **unverified**, and it is the first thing the pilot must establish.

MLE-bench Lite is worth revisiting only with a sponsor for the compute. A reduced protocol (1 seed, fewer hours) would be cheaper but **not comparable** to the leaderboard, and it would have to be labeled as such.

## Before spending anything

1. Freeze a prereg for the benchmark run, using `templates/prereg.md`. Include a positive control: the repository's dummy and direct-submission solvers run through the same pipeline and the same judge, and they must score where the README says they do.
2. Run the `debug` split (1 paper) with the dummy judge (`paperbench.judge.scaffold=dummy`). This costs no judge tokens and establishes that the Claude Code solver runs at all.
3. Re-check the API prices. The Claude prices above are from the claude-api reference cached on 2026-10-06; the o1 and o3-mini figures are the paper's, from 2025.
