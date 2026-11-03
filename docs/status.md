# Status (2026-11-04)

Where the kit stands against the plan in [ROADMAP.md](ROADMAP.md), what the cross-review changed, what is known not
to work, and what only the owner can decide. Published 2026-11-04 at https://github.com/jease0502/research-agent-kit with a
fresh, single-commit history; the development history stays in a local archive and is not published, so the
commit hashes in this file cannot be looked up in the public repository.

## Done, by phase

### P0: skeleton

| Item | Commits |
|---|---|
| Marketplace, plugin shells, `python/rak`, licenses | `0ac276d` |
| Deny-list scan: private names from a list outside the repo, CI fails without the list; approved commit identities (exact name and e-mail) exempt in history; e-mails fully redacted | `63ca161`, `348aa33`, `00a917b`, `5b6a2a5`, `ec6f722`, `296fdc9` |
| Pre-commit hook (`git config core.hooksPath scripts/hooks`): a staged finding blocks; the rest of the working tree only warns, since sessions share it | `c55fe5b`, `367e047`, `3a8bb32`, `3fa885e` |
| `rak` in English by default, zh-TW optional, configurable section headings; web UI follows the locale | `964f0ef`, `336bf5b` |
| Comments and docstrings of `python/rak` in English (behaviour unchanged: AST without docstrings identical) | `d42f8c0`, `fa95f86`, `4691842`, `3cccff9` |

### P1: first usable version

| Item | Commits |
|---|---|
| `rak-discipline`: collision search, prereg, freeze, gate, verdict, erratum, lesson skills; `guard.py` hook; templates; failure-mode catalogue | `ba7460a`, `a46eaf7`, `ca197ca` |
| Freeze extended to the scorer, tables and whole folders (`frozen_files`, `frozen_trees`) | `843d68c`, `62c4ee7` |
| `rak-knowledge` and `rak-team` skills; `rak-team` `git_guard.py` hook | `8d30d38`, `78d855c` |
| Hooks 1–4 of the plan: no job without a frozen prereg, no verdict without a passing gate, results append-only, no whole-tree staging | see [architecture.md](architecture.md) for what each one enforces and how |
| Demo project `examples/friction-dr-anymal`: design draft, collision search, CPU pipeline and tests, cloud job preparation. **Not run** | `a6c8e09`, `b9a813f`, `4b38fda`, `ece1af2` |

### P2: cloud execution and anti-fabrication checks

| Item | Commits |
|---|---|
| `rak-cloud`: pre-create checks, guarded create with max-run, waiter that only treats "not found" as gone, VM job engine, idle self-delete, cost ledger, runner service-account installer | `d995a23` |
| Local GPU lock (atomic stale takeover; the takeover race fixed) | `31a2a98`, `01fbeb2`, `dff0bd1` |
| `rak cite-check` and the `citation-check` skill | `8d30d38`, then review fixes below |
| Daily paper digest runner (unattended `claude -p`) | `8d30d38`, then review fixes below |
| Plan hook 5 (no VM without budget and stop line): done in `rak-cloud`'s guarded create, as code rather than a hook. Hook 6 (citation check before a draft leaves): a skill, **not enforced**. Hook 7 (deny-list scan in CI): done, plus the pre-commit hook | |

### P3 (started): evaluation

| Item | Commits |
|---|---|
| Fabrication-audit eval: tasks, scorer, controls, aggregation, verdict, prereg (draft, **not frozen, not run**) | `4884277`, then review fixes below |
| Public benchmark choice: PaperBench Code-Dev recommended over MLE-bench Lite ([benchmark-choice.md](../evals/benchmark-choice.md)) | `4884277` |

### P4 (started): enforcement that holds whatever the model or agent

The plan is [harness-landscape.md](harness-landscape.md) §4: no agent loop of our own, and enforcement in three
layers. [architecture.md](architecture.md) shows where each piece sits.

| Layer | State | What exists | Commits |
|---|---|---|---|
| **L1** OS sandbox around the agent process | **prototype, under review** | `templates/sandbox/`: the whole agent in one container. The kit is mounted read-only, the home folder is empty, the rootfs is read-only, there are no capabilities, and egress goes only through an allowlisting CONNECT proxy. A probe ran without a model (23 of 23). The canary run with a model waits for the owner's choice of authentication | `6555c3c`, `3e1a518` |
| **L2** policy engine | **done** | `python/rak/policy`: rules as data (pinned `rules.json`), checks as code. The three Claude Code hooks are adapters over it, shown equivalent by differential tests (generated, plus 20,000 real commands locally, 0 differences) | `f889085`, `fb10c8b`, `f3d48ee` |
| **L2** MCP server | **done** | `python/rak/mcp_server.py`, with exec, read, edit and write: path confinement, a program allowlist (only `.exe`/`.com` on Windows), argv without a shell, an environment allowlist, every call through the engine with unknown tools denied, P1 (policy, hook and CI files are not writable), an audit log. The Claude Code example uses `--tools ""` | `94356a4`, `53f7221`, `baca45b` |
| **L2** hook hardening | **done** | `onFailure: "block"` on every PreToolUse hook; a SessionStart warning below Claude Code 2.1.295 | `11bb8f2`, `96ef615` |
| **L3** git and CI | **done** for the scan; the freeze checks were there before | CI scans the tree and the history; the pre-commit hook scans what is staged; frozen hashes are checked by the verdict script and the job packaging; `rules.json` and the lifecycle trees are pinned by hash | `ec6f722`, `296fdc9`, `3fa885e`, and P1 above |

Beside the layers:

| Item | State | Commits |
|---|---|---|
| Model profiles: another vendor's model behind Claude Code through `ANTHROPIC_BASE_URL` ([model-profiles.md](model-profiles.md)) | Profiles for seven vendors and a positive control. Only `anthropic` has been run | `8b47fda` through `c28d7ce` |
| Behaviour-tree pilot: rak-cloud's job lifecycle as a pinned, declarative tree ([bt-pilot.md](bt-pilot.md)) | Done for rak-cloud. Rolling it out to other layers is on hold | `534dfdd`, `3c02fd0`, `8e0c5ee`, `1cc6d7e` |
| Daily digest runner (unattended `claude -p`) | Done. Its permissions are Claude Code flags (`--tools`, allow and deny rules, an environment allowlist), not yet the MCP server | `8769c58` through `283f005` |

#### Real-CLI runs (each approved by the maintainer)

| What | Model | Cost | Commit |
|---|---|---|---|
| Daily digest canaries, runs 1 to 4 | haiku | US$0.004, US$0.0037, US$0.002, US$0.002 | `8769c58`, `4775a42`, `35839af`, `283f005` |
| `onFailure: "block"`, 5 runs with throwaway plugins | see commit | about US$0.018 | `11bb8f2` |
| SessionStart version check, 2 runs | see commit | US$0.0058 | `96ef615` |
| Model-profile positive control, runs 1 to 5 (`anthropic`) | haiku | US$0.0078 (runs 1 and 2), US$0.0029, US$0.0030, US$0.0028 | `0841ec2`, `729a816`, `087e055`, `c28d7ce` |
| MCP smoke, first attempt: `claude.cmd` cut the prompt argument at a newline and dropped `--model` and the rest; no tool call | the default (Opus), by accident | no `total_cost_usd`; transcript usage only | `53f7221` |
| MCP smoke, deny list only, 9 steps (found PowerShell still available) | haiku | US$0.0084 | `53f7221` |
| MCP smoke, `--tools ""`, stopped at `init` | none (no model call) | 0 | `53f7221` |
| MCP smoke, `--tools ""`, 9 steps | haiku | US$0.0023 | `53f7221` |

#### Not verified

- **L1** is a prototype under review, and no model has run inside it. Until it is accepted, these are only speed
  bumps: the MCP server's code and rules, the pins, and P1. A command the agent is allowed to run can rewrite them,
  and an allowed program's own arguments reach outside the project ([mcp-server.md](mcp-server.md) §3).
- Whether subagents started by Claude Code's Agent or Workflow tools keep the session's tool restrictions. With
  `--tools ""` both tools are absent, so this matters only for a launch without the flag.
- Whether `--tools` can be set in a settings file. We treat it as a command-line flag.
- The Gemini CLI and Codex adapters for the MCP server are documented, not run. Codex has no documented switch for
  `apply_patch`.
- Every model profile except `anthropic`.
- The SessionStart warning: the hook was shown to emit it. We did not watch the interactive UI display it.
- The IAM condition that limits VM deletion to the runner's VMs, on a live project (also under Known limits).

## What the cross-review changed

A full review of `python/rak`, the rak-knowledge skills, the scanner and the fabrication audit
([review-2026-10-31.md](review-2026-10-31.md)) found 13 high and 20 medium findings, and later reverse reviews
of the fixes found more. Every fix came with a test that failed before it.

- **Security** (`348aa33`, `5b6a2a5`): the local Q&A bridge checks Host, Origin and Content-Type, takes the question
  on stdin and runs read-only; raw HTML, event attributes and non-http(s) links (also entity- or tab-obfuscated) are
  dropped from rendered notes; the build refuses to delete a folder it did not create.
- **Citation check** (`aee1a16`, `58dbf9f`, `9e1f399`, `0b04f62`): titles must match word for word (one-word
  fabrications such as "Playing Go with Deep RL" on a real id are mismatches); surname-only author match; more
  reference formats; unparsable references are reported; no citation found is exit 1.
- **Scanner** (`00a917b`, `5b6a2a5`, `c55fe5b`): private names glued to other words, percent-encoded, full-width
  or split across lines and folders; whole-domain e-mail allow-list; history scan of authors, tags and all paths.
- **Fabrication audit** (`04ed71a` through `0e06280`): the reference values come from a hash-checked re-run, never
  from the agent's own logs; the gates were rebuilt so that a scorer loosened 10x in any single number format fails
  (thresholds checked on seeds not used to set them); a "not scorable" class for precision the scorer cannot
  resolve; C1 reads only the tasks whose key numbers are resolvable; unparsable references count as bad citations;
  small integers have their own fixed controls (0 of 21 honest sentences flagged, 1 of 21 fabrications missed).
  Many of these are maintainer decisions waiting for the owner (below).
- **Daily digest runner** (`3172481` through `283f005`): the agent reads untrusted abstracts, so it has no git, no
  code execution, no free network access, an allow-listed environment, reads blocked outside the knowledge base,
  and writes only under the content folders; the runner fetches the papers and commits a fixed set of paths. Tested
  four times against the real CLI with canary files (about US$0.01 in total): every read outside the base was refused.
- **Documentation honesty** (`0b04f62`, `ce14435`): stale claims were corrected in place, with the original sentence
  kept. The zh-TW output of `rak build` differs from the tooling it was extracted from on 6 of 1,993 pages, each for
  a listed reason; `rak check` output is identical.

## Known limits

- **Hooks match command text.** A renamed script, a wrapper or `python -c` is not seen; the frozen scripts' own
  checks are the first line. Claude Code's permission rules are not a sandbox either: the daily digest should run
  in a container or VM ([daily-digest SKILL, "Threat model"](../plugins/rak-knowledge/skills/daily-digest/SKILL.md)).
- **Citation check** compares only the first author's surname (two people with one surname match), does not check
  co-authors, and does not check that a source supports the sentence citing it.
- **Fabrication audit**: the gates do not detect a scorer that is only 3x too loose, and no gate can verify a
  fabrication off by one in the last printed digit. The small-integer rule misses some phrasings and is frozen;
  further findings become known limits. Adding small integers to the unscorable share may push the more descriptive
  arm towards UNDETERMINED. Details in the prereg's revision record.
- **Small-integer rule (frozen):** besides the misses in the prereg, `The mean of 5 seeds is 2.48.` flags the 5 (a
  result name, "of", a count), which works against the more descriptive arm, so the pilot reports coarse small
  integers per arm; a point in time (`after 10 epochs`) is read as a result; the argv-setting rule has never fired
  on the real logs; the controls' plants are scored without result names (same result today, noted in the code).
- **rak-cloud** is GCP only; the IAM condition that limits deletion to the runner's VMs has not been verified on a
  live project (the `cloud-setup` canary is the test); the GPU lock has a documented race window on very long holds.
- **Not done yet**: the demo project has not run; the fabrication audit has not run; no benchmark has run; an
  install into a clean environment is still to do; the package is not on PyPI.
- **`claude plugin validate`** (Claude Code 2.1.314, 2026-10-31): the marketplace and all four plugins pass (exit 0).
  Each plugin has one directory-catalog warning, no icon (`ICON_MISSING`), and one piece of advice: its README
  has no `/plugin install <name> --marketplace <owner>/<repo>` line. That line needs the published repository's
  name, so it waits for publishing; the icons are a design choice left to the owner.
  *Update (2026-11-04): the root README now has that line, with the published name; the plugin READMEs do not yet.*

## Waiting for the owner

1. **Commit author identity — decided (2026-11-01).** The owner keeps the existing commit identity: no author
   rewrite, no change to the e-mail. `scan_private.py --history` now skips an author or committer field only when
   its name and e-mail exactly match an approved identity. The list stays out of the repository
   (`~/.config/research-agent-kit/allow_identities.txt` or `RAK_ALLOW_IDENTITIES`; in CI, the secret
   `RAK_ALLOW_IDENTITIES`). Messages, files and paths are scanned as before. Local run with the list: 77 commits,
   154 fields exempted, 1 hit left. The hit is the fake user path in an old blob of
   `test_run_digest_review.py`, added in 3172481 and removed in 5b6a2a5. It is still in history and is reported
   as it is.
2. **Fabrication-audit decisions made by the maintainer**, each marked "pending the owner's confirmation" in
   `evals/fabrication-audit/prereg.md`, among them:
   - the "not scorable" class and its 0.05 threshold;
   - min-n counted in scored numbers (100 per arm, at least 10 runs with scored numbers);
   - C1 read on t1–t3 only; C1 not comparable when arm B's unscorable share exceeds arm A's by more than 0.10;
   - unparsable references counted as bad citations; t5 requiring an id on every reference;
   - coarse decimals untraced; the small-integer rule and its freeze.
3. **When to run the fabrication audit, and the API key.** The runs use an isolated config directory and need
   `ANTHROPIC_API_KEY`; the prereg's budget is about US$120 planned, US$150 hard stop, pilot first. The plugins it
   freezes (`plugins/rak-discipline`, `plugins/rak-knowledge`, `templates`) cannot change after the freeze without a
   new registration, so the freeze should wait until plugin work for this round is done.
4. **PaperBench.** Whether to pursue PaperBench Code-Dev at all: it needs an OpenAI key for the judge, a Claude Code
   solver inside its container runtime (unverified), and about US$600 of judge cost per arm for the full set.
   A dummy-judge debug run costs no judge tokens and comes first.
5. **Demo project on a VM.** Creating the runner service account (`install_sa.sh`, dry run by default) and running
   its live permission canary need a GCP project and the owner's go-ahead; then the demo's budget rule applies
   (stop if the projection crosses 8 L4-hours).
6. **Publishing.** No remote exists and nothing has been pushed; publishing waits for items 1 and 2 at least.
7. **Freeze the context files?** CLAUDE.md, AGENTS.md and GEMINI.md steer every session, and an agent can edit
   them. Through the MCP server they are writable on purpose, since agents edit them as normal work
   ([mcp-server.md](mcp-server.md), P1). The question is whether to add them to P1, or to freeze them in a prereg's
   `frozen_files`, so that a change needs a person.

## Must be done before publishing

1. **The fake user path in history.** An old blob of `plugins/rak-knowledge/tests/test_run_digest_review.py`,
   added in 3172481 and removed in 5b6a2a5, has a Windows user path that `scan_private.py --history` flags
   (`user-path`). The rule stays as it is, and history is not rewritten now. Before publishing, that blob has to be
   dealt with; the owner picks how at that time.
   *Done (2026-11-04): the owner chose to publish a fresh history. The public repository starts from one commit
   of this tree, so the blob is not in it; the full history stays local only.*
2. **CI secrets.** *Open (2026-11-04):* CI is red until the owner sets `RAK_DENY_TERMS` and
   `RAK_ALLOW_IDENTITIES` (format in README and CONTRIBUTING). We do not set them.
