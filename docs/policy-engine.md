# Policy engine: inventory and design

Status: step 1 done (2026-10-31): the engine exists (`python/rak/policy/`) and the three Claude Code hooks are
adapters over it, with behaviour unchanged (§5). The MCP server is the next step. Before that step the status was:
inventory and design, nothing implemented. The goal is to move the enforcement logic out
of the Claude Code hooks into one model-independent engine without changing behaviour. The input is a tool-call
event; the output is a decision with its reason.

**Where this sits.** [harness-landscape.md](harness-landscape.md) §4 recommends three layers that do not depend on
the agent loop:
- **L1**, an OS sandbox around the agent;
- **L2**, our MCP server for exec, read, edit and write, with every call going through one policy engine;
- **L3**, git and CI checks on the server side.

This package is the L2 engine. The same `evaluate(event)` is called by our MCP server (the guarantee, where an agent
can be limited to our tools) and by each agent's own pre-tool hook (defence in depth and better error messages,
never the guarantee). We do not write an agent loop of our own. The engine's interface is therefore the tool name,
the arguments, the cwd and the project root, and it assumes nothing about Claude Code's hook JSON.

## 1. Inventory: every rule enforced today

"Input" lists what each rule reads. "Output" is what it decides today. Every hook below **fails closed**: a crash
or a bad config blocks the call (exit 2).

### 1.1 rak-discipline `hooks/guard.py` (PreToolUse on `Bash|Edit|MultiEdit|Write`)

Active only when `<project>/.rak/discipline.json` exists. The project root comes from `cwd`, then
`CLAUDE_PROJECT_DIR`, then the working directory: the first ancestor with `.rak/` or `.git`.

| # | Rule | Input | Output |
|---|---|---|---|
| D1 | A Bash command matching `experiment_patterns` must carry `<prereg_token>=<id>` | command text, discipline.json | deny "looks like an experiment launch ... carries no RAK_PREREG" |
| D2 | ...and `<id>` must be frozen, with the prereg, verdict script, `frozen_files` and `frozen_trees` unchanged since freezing | command text; `.rak/frozen/<id>.json`; file hashes (CRLF-normalized); folder hashes | deny with `verify_frozen`'s message |
| D3 | A Bash command matching `verdict_patterns` (default `verdict\.py\s+judge`) needs `<token>=<id>` | command text | deny "reading results needs RAK_PREREG" |
| D4 | ...and the gate for `<id>` is PASS, recorded against the frozen prereg and verdict hashes | `.rak/gates/<id>.json`, the freeze record | deny "gate for `<id>` is FAIL/NONE/STALE" |
| D5 | A Bash command with an editing construct (`sed -i`, `perl -i`, `>`, `truncate`, `rm`, `git rm`, `mv`, `tee` without `-a`, `cp`, `dd`) that names a committed file matching `results_globs` | command text, discipline.json, `git show HEAD:<file>` | deny "append-only results doc; shell edits/deletes not allowed" |
| D6 | Edit / MultiEdit / Write on a committed file matching `results_globs` that would remove or rewrite a committed body line (frontmatter and blank lines exempt) | tool args (path, old/new strings, replace_all, edits, content), the current file, `git show HEAD:` | deny "append-only once committed; removes N line(s), first: ..." |

The frozen verdict script enforces D4 itself, and the pre-commit hook (`rak_discipline.py check-append-only
--staged`) enforces D5/D6 on the index. These are **not** tool-call rules; they stay where they are.

### 1.2 rak-team `hooks/git_guard.py` (PreToolUse on `Bash`)

Active in every git repo unless `.rak/team.json` says `{"shared_worktree": false}` (unknown keys raise).

| # | Rule | Input | Output |
|---|---|---|---|
| T1 | `git add -A / --all / -u / --update / --no-ignore-removal` (also in short-flag clusters) without a pathspec | command text: split on `;`, `&&`, `\|\|`, `\|`, `&`, newline; shlex; skips env assignments, `sudo/env/command/time/nohup`, and git's global options | deny "stages every change" |
| T2 | `git add` with a whole-tree pathspec (`.`, `./`, `:/`, `:(top)`, `*`, ...) | same | deny "stages the whole tree" |
| T3 | `git commit -a / --all`, or a short cluster containing `a` before a value-taking letter | same, with commit's options that take a value | deny "commits every tracked change" |

### 1.3 rak-cloud `hooks/tree_guard.py` (PreToolUse on `Edit|Write|MultiEdit|NotebookEdit|Bash`; 534dfdd)

| # | Rule | Input | Output |
|---|---|---|---|
| C1 | A file tool on a path under `<plugin>/trees/` (relative paths resolved against `cwd`, case-folded on Windows) | tool name, `file_path` / `notebook_path`, cwd, `CLAUDE_PLUGIN_ROOT` | deny |
| C2 | A Bash segment that names a tree file (`trees/*.json`, `lifecycle.json`), unless it starts with a read-only command (no `>`, no `-i`) | command text | deny |

### 1.4 Enforced inside code, not on tool calls

| # | Rule | Where | Input | Output |
|---|---|---|---|---|
| G1 | `gcloud compute instances create` must carry `--max-run-duration`, `--instance-termination-action=DELETE` and `--boot-disk-auto-delete` | `rak_cloud.guard_command` | the argv the kit builds | raise |
| G2 | The VM name starts with `name_prefix` | `rak_cloud.create_command` | name, config | raise |
| G3 | The lifecycle tree's hash matches its pin | `bt.load_tree` | the tree file | raise |
| F1–F3 | freeze: prereg id and verdict script required, no re-freeze, frozen files and trees committed and clean | `rak_discipline.freeze` | files, git | raise |

G1 checks only the commands the kit builds. **An agent that runs `gcloud compute instances create` itself is
unguarded today.** As a tool-call rule, G1 would cover that too. That is a behaviour change, so it is listed in §4
and not in the first step.

### 1.5 daily-digest `run_digest.py`: flags for Claude Code's own permission system

These rules are **enforced by Claude Code, not by our code**. The runner only builds the flags:

| # | Flag | Content |
|---|---|---|
| R1 | `--tools` | `Read,Glob,Grep,Write,Edit,Bash,WebFetch` (nothing else exists for the agent) |
| R2 | `--settings` | `blockReadsOutsideWorkingDirectories: true` |
| R3 | `--allowedTools` | WebFetch to arxiv.org and export.arxiv.org; `Bash(rak check)`, `Bash(rak build)`, `Bash(rak add-paper --batch <tmp>/ids_tmp.txt)`; `Edit(/papers/**)`, `Edit(/<digest_dir>/**)`, `Edit(/<tmp_dir>/**)` |
| R4 | `--disallowedTools` | Read of credential paths (`~/.ssh`, `~/.config`, `~/.aws`, `~/.claude`, gcloud, hf, docker, kube, `.env` files); Read and Edit of `/.git/**`; Read of `/digest.toml`; 28 read-only commands as `Bash(c)` and `Bash(c *)`; the home layer (every dot folder and AppData, decided two levels down, with the documented exceptions) |
| R5 | environment | allow-list `ENV_ALLOW`, plus `CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR=1` |

Their matching semantics (prefix rules, `**`, `~`, "deny beats allow") belong to Claude Code. Re-implementing
them in our engine would be a second, unverified copy of someone else's matcher.

### 1.6 How the hooks fail

Every command hook sets `"onFailure": "block"` since 11bb8f2. Before that, a hook that timed out, exited with a
code other than 0 or 2, or could not start let the call through, and "fails closed" was true only of errors inside
our Python (harness-landscape §0). Checked with the real CLI (2.1.316): with the setting, exit 1, a timeout and a
missing interpreter are all blocked. Any adapter the engine gets must keep this, and so must the MCP server: an
error is a deny.

## 2. Design

### 2.1 The event (agent-independent)

```json
{"tool": "shell" | "file.write" | "file.edit" | "file.read" | "web.fetch" | ...,
 "args": {"command": ...} | {"path": ..., "content": ...} | {"path": ..., "edits": [{"old": ..., "new": ..., "all": bool}]},
 "cwd": "...", "env": {"CLAUDE_PROJECT_DIR": ..., "PLUGIN_ROOT": ...},
 "agent": "claude-code" | "mcp" | "own-loop"}
```

The adapter maps native names onto this. For Claude Code: `Bash` → `shell`; `Write` → `file.write`;
`Edit` / `MultiEdit` → `file.edit` (MultiEdit's `edits` keep their order); `NotebookEdit` → `file.edit` with
`notebook_path` as `path`. The engine never sees "Bash" or "MultiEdit".

### 2.2 The decision

`{"decision": "allow" | "deny" | "ask", "rule": "D2", "reason": "..."}`. Every applicable rule is evaluated;
deny beats ask, and ask beats allow. With no applicable rule, the decision is allow: these rules sit on top of the
host's own permissions and do not replace them. An exception in a check, or a bad project config, is a deny with
the error as the reason (fail closed, as today). For Claude Code, deny is exit 2 with the reason on stderr; ask
would be the hook's JSON `permissionDecision: "ask"` (no rule uses ask today).

### 2.3 Rules as data, checks as code

Like the behaviour tree: the **policy file** (`policy/rules.json`) holds the rule ids, which event they apply to,
which registered check they call with which parameters, the decision, the message, and the activation condition.
The **checks** are named functions in the engine: `regex_any`, `token_value`, `frozen_ok`, `gate_pass`,
`edit_construct_names`, `append_only_lines`, `git_broad_add`, `git_commit_all`, `path_under`,
`segment_names_file`. Their parsing code is moved out of the hooks unchanged.

```json
{"id": "T3", "on": ["shell"], "active": {"not": {"project_json": [".rak/team.json", "shared_worktree", false]}},
 "check": "git_commit_all", "decision": "deny", "message": "`git commit -a` commits every tracked change, ..."}
```

The policy file is pinned like the tree (canonical hash in the engine). It is also listable in a prereg's
`frozen_files`, and the rak-cloud-style hook refuses edits to it. Project-specific values (`experiment_patterns`,
`results_globs`) stay in the project's `.rak/*.json`; rules read them as `"$discipline.experiment_patterns"`.

### 2.4 Adapters

1. **Claude Code hook** (first and only, in this step): one script that reads the hook JSON, builds the event, asks
   the engine, and exits 0 or 2. It keeps `"onFailure": "block"`. Each plugin's `hooks.json` keeps its own matcher
   and evaluates only its own rule ids, so each plugin still works alone.
2. **Native-permission compiler** (for R1–R5): the digest's rules become entries in the policy file with
   `"enforce": "native"`. A function compiles them to the exact `--tools` / `--allowedTools` / `--disallowedTools`
   / env values. The engine does not evaluate them at hook time (see §1.5). These belong with L1 (what the agent
   process may touch), not L2.
3. Next, and the actual L2: **our MCP server** with `exec`, `read`, `edit` and `write` tools. Each call becomes an
   event and goes through `evaluate()` before anything runs, and the agent's own shell and file tools are turned
   off (harness-landscape §3: possible and lockable in Claude Code and Gemini CLI; partly in Codex; OpenClaw has no
   admin lock). The server has real privileges, so it fails closed, has no debug bypass, and gets the same
   differential tests as the hooks.
4. Other agents' hooks (Gemini `BeforeTool`, Codex and OpenClaw pre-tool hooks): thin adapters to the same engine,
   with fail-closed set where the agent has it. These are best effort and are never described as the guarantee.

We do not write an agent loop of our own (harness-landscape §4).

### 2.5 Where the package lives (to decide)

`python/rak/policy/` is the source of truth (standard library only). But a plugin installed from the marketplace
cannot import `python/rak` unless the user `pip install`s it, and today each plugin works alone. Proposal: a sync
script vendors the engine into `plugins/<p>/_vendor/rak_policy/`, and a test fails if any vendored copy differs
from the source byte for byte. The alternative is to require `pip install research-agent-kit` for the hooks, which
changes what users must install.

## 3. Equivalence plan

- The existing guard tests pass unedited: rak-discipline `test_guard.py` (47), rak-team `test_git_guard.py` and
  `test_team.py` (23), and the rak-cloud hook test.
- The hooks as of today are kept as frozen reference copies (`tests/legacy_*.py`), as with the lifecycle.
- **Differential test**: the old hook and the new adapter on the same inputs; the decision (exit code) and the
  reason (stderr) must match for every sample:
  - generated git commands (random flag clusters, option values, pathspecs, `--`, separators, env prefixes,
    quoting, `sudo`/`env`, global options);
  - generated discipline cases (experiment and verdict patterns with and without tokens, frozen / modified /
    missing records, gate states, every edit construct against results files and non-results files, Edit,
    MultiEdit and Write that keep, reflow or rewrite committed lines);
  - tree-guard paths and commands;
  - **real commands**: the Bash commands in this machine's Claude Code transcripts, run through both. This is
    local-only: the corpus contains private paths and names, so it is read at test time from
    `~/.claude/projects` and never written into the repo. The committed test uses only the generated corpus.
- Mutants: a few deliberate changes to the engine must each turn the differential test red.
- The native compiler: its output must equal today's `agent_cmd` / `agent_env` strings for a set of configs and
  home layouts (dot folder, AppData/Local, AppData/Roaming, outside home).

## 4. Not in this step (behaviour changes, each for a decision)

- G1 as a tool-call rule: block an agent's own `gcloud compute instances create` that lacks the three flags.
- `ask` decisions, for example for `git push`.
- Evaluating R3/R4 in our engine for non-Claude agents. This needs our own path-glob semantics, documented as ours
  and not Claude Code's.
- The MCP server itself (§2.4 item 3), and turning off the agents' native tools: the next step after the hooks
  are moved onto the engine with equivalence shown.
- Rules about reads. Context files (CLAUDE.md, AGENTS.md, GEMINI.md) and @-mentions are read without a tool call
  in every agent, so no L2 rule sees them. Only L1 can keep a file unread.

## 5. Step 1: the Claude Code adapters (done)

What exists:
- `python/rak/policy/`: `engine.py` (Event, Decision, `evaluate`, `evaluate_closed`, pinned `rules.json`),
  `adapters.py` (Claude Code hook JSON → Event), and the checks `checks_discipline.py`, `checks_git.py`,
  `checks_trees.py`. The checks are the hooks' code moved over. `checks_git.py` was generated from `git_guard.py`
  line for line, and the only change is that the environment comes from the event.
- The rules: `D1-D2`, `D3-D4`, `D5`, `D6`, `T1-T3`, `C1`, `C2`, in the order the hooks used to check them.
  The first deny wins.
- Freeze, gate and append-only semantics stay in `plugins/rak-discipline/scripts/rak_discipline.py`. The adapter
  passes that module in as the event's `discipline` backend, so they keep a single home.
- Each plugin with hooks carries a byte-identical copy in `_vendor/rak_policy/`, written by
  `scripts/vendor_policy.py`. A test fails if a copy differs or is missing. No plugin needs `pip install`.
- `guard.py`, `git_guard.py` and `tree_guard.py` are now adapters: hook JSON in, `evaluate()`, the same block
  messages and exit codes as before.

How equivalence was checked:
- **The existing hook tests pass unchanged**: rak-discipline, rak-team, the tree-guard test and the fail-closed
  test, 125 cases, with no test file edited.
- **Differential, generated** (`python/tests/test_policy_differential.py`): the old hook, kept as a frozen copy in
  `plugins/*/tests/legacy_*.py`, and the new one get the same hook JSON. Exit code and stderr must be equal for
  every sample:
  - rak-team: 3,000 git commands. They mix env prefixes, `sudo`/`env`/`nohup`, global options, flag clusters,
    option values, pathspecs, `--`, quoting, unbalanced quotes, separators and wrappers. Working folders: a plain
    repo, an opted-out repo, an opted-in repo, a repo with a bad `team.json`, no git, and no cwd.
  - rak-cloud: 1,500 file-tool and shell calls on paths inside and outside `trees/`, with and without
    `CLAUDE_PLUGIN_ROOT`.
  - rak-discipline: 1,200 calls over eight project states: no config, bad config, unfrozen, frozen, frozen then
    changed, and gate PASS / FAIL / STALE. The calls are launches with and without ids, verdict reads, every
    editing construct, and Edit, MultiEdit and Write that keep, reflow or rewrite committed lines.
  - Each set must contain both blocks and passes (and errors, where that is possible).
  - A loosened rule (one whole-tree pathspec removed) turns the test red.
- **Differential, real commands** (`python/tests/test_policy_differential_local.py`, local only, run with
  `RAK_LOCAL_TRANSCRIPTS=1`):
  - Source: the Bash commands in this machine's transcripts. Each is screened with `scan_private` and skipped on
    any hit. Nothing from them is written to the repository; only these counts are.
  - 2026-10-31 run: 132,227 distinct commands; 66,928 skipped by the scan; 20,000 sampled.
  - Each sample went through all three hooks, old and new: 0 differences.
  - rak-team blocked 106, rak-discipline blocked 1, the tree guard blocked 0, and none of the three errored.

Limits of step 1:
- `rak_discipline.project_root()` still reads `CLAUDE_PROJECT_DIR` from the process, not from the event. That is
  fine for a hook and has to change for the MCP server.
- `ask` exists in the engine and no rule uses it. The adapters treat any non-allow decision as a block.

For step 2, the MCP server (cross-review of fb10c8b):
- **Where the policy lives.** `RULES_SHA256` pins `rules.json`. But no rule protects `python/rak/policy/`,
  `_vendor/rak_policy/` or the pin itself, so, as with the lifecycle trees, the pin is a speed bump. Once the MCP
  server is the one process with real privileges, its code and rules must sit where the agent cannot write: a
  read-only mount in the L1 sandbox, or a different OS user. A rule in the C1 style over the policy folders can
  be added as one more speed bump.
- **Unknown tools.** `evaluate()` allows any tool outside `TOOLS` (`other:*`). That is right for a hook, which
  only sees the tools its matcher names. The MCP server names its own tools, so there it should be an allowlist:
  a tool not in `TOOLS` is denied, as in `evaluate_closed`. Otherwise a new tool added without a rule would run
  unchecked.
- **ask.** A Claude Code adapter that meets an `ask` decision must answer with `permissionDecision: "ask"`, not
  exit 2 (noted in `adapters.py`).


## 6. Step 2: the MCP server (done; details in `docs/mcp-server.md`)

How the step-2 notes above were settled:
- **Unknown tools.**
  - `evaluate()` and `evaluate_closed()` take `unknown=`. Hooks keep `"allow"`.
  - The MCP server passes `"deny"`. This is fixed in code, with no flag or variable to change it.
  - `file.read` joined `TOOLS`.
- **ask.**
  - The three hooks answer `permissionDecision: "ask"` and exit 0, through `adapters.claude_code_ask()`.
  - The MCP server denies `ask`, with the reason, until there is an approval path.
- **Where the policy lives.**
  - A new rule, P1 (plugin `rak-policy`), denies file-tool writes to the engine, its rules, the hooks, `.rak/`,
    `.claude/` and `.mcp.json`.
  - The MCP server evaluates P1. The hooks evaluate only their own plugin's rules, so for them nothing changed.
  - P1 is a speed bump. The real place for the server's code and rules is outside the agent's reach (L1), and
    that is not implemented yet.
- **project_root.** The server loads its own private instance of `rak_discipline.py` and sets that instance's
  `project_root` to return `--root`. Calls made from inside the module get the same root (cross-review of
  94356a4). The file itself is unchanged, and so is the hooks' behaviour.

`rules.json` gained P1. sha256 of the LF blob: old `1d38716c...afd32c`, new `b23725cc...0de86`. `RULES_SHA256`, the
canonical hash, is now `77fe52d5...`.
