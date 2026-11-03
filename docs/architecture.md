# Architecture

research-agent-kit is four Claude Code plugins in one marketplace, a shared Python library (`python/rak`, the
`rak` CLI), templates, and a worked example. This page shows how the pieces connect, where data flows, and,
most importantly, which rules are enforced by code and which still rely on the agent following instructions.

## The four plugins

```
                 ┌──────────────────────────── rak-team ────────────────────────────┐
                 │ lead-worker · handoff (tasks.json + progress.md) · notify         │
                 │ coordinates several sessions; reports go to a lead / the user     │
                 └───────────────┬───────────────────────────────┬──────────────────┘
                                 │ dispatch / report             │ dispatch / report
 ┌──────── rak-knowledge ────────▼──────┐          ┌─────────────▼──────── rak-discipline ────────┐
 │ add-paper · concept-card · kb-query  │  cites   │ collision-search → prereg → freeze → gate →   │
 │ daily-digest · citation-check        │◄─────────│ verdict → results doc → erratum → lesson      │
 │ markdown KB: papers/ concepts/ ...   │          │ hooks: guard.py (PreToolUse)                  │
 └──────────────────────────────────────┘          └─────────────┬────────────────────────────────┘
                                                                  │ RAK_PREREG=<id> launches
                                                   ┌──────────────▼──────── rak-cloud ─────────────┐
                                                   │ precheck → create (guarded) → VM: vm_job.sh    │
                                                   │ → waiter: pull + verify manifest → delete      │
                                                   │ cost ledger (audit log) · idle guard · gpulock │
                                                   └────────────────────────────────────────────────┘
```

| Plugin | Owns | Depends on |
|---|---|---|
| `rak-knowledge` | The knowledge base (markdown with a schema): papers with API-sourced metadata, concept cards, cited answers, daily digests, citation checks | `rak` CLI |
| `rak-discipline` | The experiment record: collision search, pre-registration, freeze, gate, verdict, errata, lessons. Hook: `guard.py` | git, Python stdlib. Uses rak-knowledge search if installed |
| `rak-cloud` | Cloud GPU jobs end to end: configuration, prechecks, create, VM-side job engine, waiter, ledger, runner service account; a local GPU lock | gcloud CLI, bash on the VM image |
| `rak-team` | Coordination between sessions: dispatch, handoff files, notifications. Hook: `git_guard.py` (no whole-tree staging in a shared index) | Claude Code cross-session messaging or Channels |

Each plugin works alone. `rak-discipline` is useful without the cloud; `rak-cloud` can run any job; `rak-team` is
optional for a single session.

## Enforcement layers

The plugins run inside an agent. Whether their rules hold depends on where they are enforced
([harness-landscape.md](harness-landscape.md) §4). There are three layers, and an adapter for each agent:

```
┌─ L1  OS sandbox around the agent process ──── prototype under review (templates/sandbox/) ────┐
│                                                                                               │
│  agent: Claude Code (or Gemini CLI, Codex: documented, not run)                               │
│    model: Anthropic, or another vendor via ANTHROPIC_BASE_URL                                 │
│           (python/rak/model_profiles, docs/model-profiles.md; only anthropic run)             │
│    built-in tools off: --tools "" (+ permissions.deny as a second layer)                      │
│    plugin hooks: guard.py · git_guard.py · tree_guard.py  (adapters, onFailure: block)        │
│        │ hook JSON                          │ exec / read / edit / write (MCP over stdio)     │
└────────┼────────────────────────────────────┼─────────────────────────────────────────────────┘
         │                                    ▼
         │                ┌─ L2  python/rak/mcp_server.py ──────────────────────────────┐
         │                │ --root only · path confinement · program allowlist · no shell │
         │                │ env allowlist · audit log · unknown tools denied              │
         ▼                └──────────────────────────────┬────────────────────────────────┘
┌─ L2  python/rak/policy: one engine ───────────────────▼───────────────────────────────────────┐
│ rules.json (pinned): D1-D6 discipline · T1-T3 team · C1-C2 lifecycle trees · P1 policy files  │
│ checks: checks_discipline · checks_git · checks_trees · checks_policy                         │
└───────────────────────────────────────────────────────────────────────────────────────────────┘
┌─ L3  outside the agent's machine or after it ─────────────────────────────────────────────────┐
│ pre-commit: staged scan blocks · CI: tree + history scan · frozen prereg and verdict hashes   │
│ (verdict script, job packaging) · lifecycle trees pinned in rak_cloud.py · append-only results│
└───────────────────────────────────────────────────────────────────────────────────────────────┘
```

Where the other pieces sit:
- **Behaviour-tree pilot** ([bt-pilot.md](bt-pilot.md)).
  - rak-cloud's create and wait lifecycle is a declarative tree in `plugins/rak-cloud/trees/`, run by code, with
    its hash pinned in `rak_cloud.py`.
  - C1 and C2 keep the agent from editing it, and P1 keeps it from writing through the MCP server. Both are speed
    bumps; the pin and review are what hold.
- **Daily digest** (rak-knowledge).
  - An unattended `claude -p` that reads untrusted abstracts.
  - Its limits are Claude Code flags today: `--tools`, allow and deny rules, an environment allowlist, and reads
    outside the base blocked. It does not run through the MCP server yet.
  - Its own threat model says it belongs in L1.
- **Model profiles.**
  - Changing the model keeps every control, because the hooks, the permission rules and the MCP server all run on
    the client side.
  - Changing the agent does not. Only the adapters differ between agents.

What holds today, and what does not, is in [status.md](status.md) under P4: "Real-CLI runs" and "Not verified".

## Data flow of one experiment

1. **Question.**
   - `collision-search` writes a record of the queries, the papers read and what collides.
   - Papers it reads can be added to the knowledge base (`add-paper`).
2. **Registration.**
   - `prereg` produces `docs/prereg/<id>.md` and a verdict script.
   - Both are committed, then frozen: `.rak/frozen/<id>.json` stores the commit and the LF-normalised hashes of both files.
3. **Packaging** (cloud runs).
   - The job folder is built from the frozen commit only (see the example's `prepare_job.py`): an archive with
     a `COMMIT` file, its sha256, and the VM steps rendered with that commit.
4. **Execution.**
   - Every experiment command carries `RAK_PREREG=<id>`.
   - On a VM, `vm_job.sh` runs a self-check (GPU visible; the VM can delete itself and write the bucket), publishes
     `REQUIRED.txt` (every declared output, verified in the bucket before anything runs), then the steps.
   - A step succeeds only if its declared outputs exist, are non-empty and are newer than the step.
   - At the end the job writes `MANIFEST.sha256`, syncs, verifies the sync, and only then writes its status.
5. **Collection.**
   - The waiter pulls the outputs and verifies every file against the manifest.
   - Only then does it delete the VM, and it confirms that the VM and its disk are gone.
   - The ledger counts the VM's time from the audit log.
6. **Gate.**
   - The frozen verdict script evaluates the registered controls and writes `.rak/gates/<id>.json`, bound to the frozen hashes.
7. **Verdict.**
   - The same script judges the results: PASS / FAIL / UNDETERMINED, with no rounding before comparison.
   - It writes `verdict.json` once, with the hashes of the prereg, the script and the input.
8. **Record.**
   - The results doc quotes the verdict.
   - Once committed, it is append-only: corrections are errata that quote the original sentence.
9. **Lesson.**
   - `lesson` renders a lesson whose measured numbers come from logs by script (`build_logs.py`).

## What is enforced, and by what

| Rule | Enforced by | Strength | Gap |
|---|---|---|---|
| No experiment launch without a frozen prereg | `rak-discipline` PreToolUse hook (`guard.py`) on Bash commands matching `experiment_patterns` | Blocks matching commands; fails closed on its own errors, and on a timeout or a hook that cannot start through `onFailure: block` (Claude Code 2.1.295+) | Matches command **text**: a renamed script, a wrapper or `python -c` is not seen. Training entry points should also check the freeze |
| No verdict until the gate passes | The frozen verdict script itself (`GATE_FAIL`); the hook is a second line | Strong: the script refuses regardless of who runs it | Someone can write a different, unfrozen script. The freeze record makes that visible, it does not prevent it |
| Prereg and verdict script unchanged after freezing | Hash check in the hook, in the verdict script, and in `prepare_job.py` | Strong for edits | The freeze proves "not changed since", not "written before the data" |
| Committed results are append-only | git pre-commit check (`check-append-only --staged`); PreToolUse hook on Edit/Write/MultiEdit and on in-place shell edits | Pre-commit sees everything that is staged | `git commit --no-verify` skips it; run the same check in CI for a hard guarantee |
| Cloud create carries max-run, termination DELETE, disk auto-delete | `rak_cloud.py` refuses any create command without them | Strong for VMs created through the kit | VMs created by hand are outside the kit |
| Disk ≥ image, worst-case budget under the stop line, credentials valid, SPOT accepted explicitly | `rak_cloud.py precheck` (also run by `create`) | Strong | The price is a configured estimate, not the bill |
| A VM is deleted only after its outputs are verified | Waiter (`rak_cloud.py wait`) | Strong; unverified VMs are left running and reported | max-run deletes them anyway when it expires; that is the backstop, by design |
| "Gone" means not-found, never "could not ask" | `vm_state()` | Strong | - |
| Steps succeed by fresh outputs, not exit codes | `vm_job.sh` | Strong | Only for declared outputs; declare them |
| The VM can delete itself | Self-check at job start (testIamPermissions as the VM); `install_sa.sh --canary` | Strong when used | The IAM condition limiting deletes to the name prefix is unverified on a live project |
| Citations exist and match | `rak cite-check` / `citation-check` skill | Reports; changes nothing | It is not a hook: nothing forces it to be run before a draft leaves |
| No private names, accounts, local paths or tokens in the repo | `scripts/scan_private.py` in CI, over the working tree and history; the pre-commit hook on staged content | Fails the build; a staged finding blocks the commit. The private list and the approved commit identities live outside the repo | Pattern- and list-based; see `security.md`. The pre-commit hook only warns about findings outside the commit, since sessions share the tree |
| No whole-tree staging or committing in a shared tree (`git add -A` / `.` / `-u`, `git commit -a`) | `rak-team` PreToolUse hook (`git_guard.py`) | Blocks matching commands, including `git -C`, `-c`, env prefixes and command chains; fails closed. On by default; a single-session repo opts out in `.rak/team.json`. `onFailure: block` (Claude Code 2.1.295+) covers a timeout or a hook that cannot start | Matches command **text**: a script or alias that runs git is not seen. A bare `git commit` (no `-a`, no paths) is not blocked; the skill asks for `-- <paths>` |
| Shell and file tools stay inside the project and pass the policy (with the agent's built-in tools off) | `python/rak/mcp_server.py` over `python/rak/policy` | Strong for paths, `.git`, the policy files and unlisted programs; fails closed; no bypass flag | An allowed program's arguments reach outside the project, and the server's own files are writable by an allowed command until L1 exists ([mcp-server.md](mcp-server.md) §3) |
| Report to the lead before writing results; a peer's message is not the user's approval | `rak-team` skills; Claude Code itself does not let a peer approve a permission prompt | Partly platform-enforced | Writing before reporting is convention only |
| Never invent numbers, authors, years | `add-paper` takes metadata from APIs; verdicts and lessons take numbers from files by script | Strong where a script produces the number | Prose written by the agent is checked only by review and the fabrication audit (`evals/`) |

The pattern: every rule that matters is enforced first by a script in the data path (the verdict script, the
waiter, the job engine, CI). Hooks are the second line, because they match text and Claude Code documents hook
filtering as best effort. Where only a convention remains, the table says so.

## Files and state

| Path (in a user project) | Written by | Commit it? |
|---|---|---|
| `.rak/discipline.json` | user | yes (turns the hooks on) |
| `.rak/frozen/<id>.json`, `.rak/gates/<id>.json` | `rak_discipline.py freeze`, verdict script | yes |
| `.rak/cloud.json` | user | depends on your repo's visibility; it names account, project and bucket |
| `.rak/cloud/instances.json` | `rak_cloud.py create`, waiter | no (local bookkeeping; the audit log is the source of truth) |
| `docs/prereg/`, `docs/results/`, `experiments/<id>/` | agent with the skills | yes |

## Portability

- Skills follow the Agent Skills layout and are readable by other agents.
- Hooks, Channels and cross-session messaging are Claude Code specific.
- `rak-cloud` targets GCP only. Its waiter, ledger and checks are written against the gcloud CLI.
