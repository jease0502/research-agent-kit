# The MCP server (L2): exec, read, edit, write through the policy engine

`python/rak/mcp_server.py` is layer 2 of `docs/harness-landscape.md` §4. The agent's own shell and file tools are
turned off, and these four tools take their place. Every call goes through the policy engine
(`python/rak/policy/`, `docs/policy-engine.md`) before anything runs.

- Standard library only.
- stdio transport: newline-delimited JSON-RPC 2.0. No network port.
- MCP methods: `initialize`, `ping`, `tools/list`, `tools/call`. The protocol version is the client's when we know
  it, else our newest.

```
python -m rak.mcp_server --root /abs/project --exec-allow git --exec-allow python --audit-log /abs/outside/audit.jsonl
```

## 1. What one call goes through

In this order. A "no" at any step means nothing runs, and the reply is `isError` with the reason.

1. **Arguments.** They are checked against the tool's schema: no unknown keys, the right types, no NUL bytes.
2. **Server confinement.** Fixed code; there is no flag to turn it off.
   - **The root.** `--root` is resolved once at start (realpath). If it is not given, does not exist, or is not a
     directory, the server does not start.
     - `CLAUDE_PROJECT_DIR` is never read.
     - The root is never widened to an enclosing repository. For the discipline rules, `project_root()` is the
       root itself, not a walk up from cwd.
   - **read, edit, write: the path.**
     - Any `..` component is refused.
     - The path is then resolved with `os.path.realpath`, which follows symlinks, Windows junctions and 8.3 short
       names. The *resolved* path must be inside the root. The string before resolving is never compared.
     - Refused as well:
       - anything under `.git`, at any depth, in any case, and with trailing dots or spaces (`.git.` is `.git` on
         Windows);
       - `:` in a component on Windows (alternate data streams);
       - a file with more than one hard link (it may be the same file as one outside the root).
   - **exec: the program.**
     - `argv[0]` must be a bare name on `--exec-allow`; a path is refused.
     - The name is looked up on the filtered `PATH`, by our own lookup:
       - The current directory is never searched. Before Python 3.12, `shutil.which` on Windows searched it
         first; the server's cwd may be the root, so a `git.exe` dropped there would hide the real one.
       - Relative `PATH` entries are skipped.
     - A program that resolves inside the root is refused, because the agent can write there.
     - **On Windows, only `.exe` and `.com` run.** A `.cmd` or `.bat` file runs through `cmd.exe`, and
       `list2cmdline` does not escape `& | > ^`. So one argument becomes a second command, and the shell rules
       never see it: the policy sees `shlex.join(argv)`, where the `&` is quoted.
       - A reviewer reproduced this with an allowlisted `tool.cmd`. `.vbs`, `.js` and `.ps1` would run through their
         hosts, so they are refused too, whatever `PATHEXT` says.
       - `npm`, `npx`, `mvn` and `gradle` are `.cmd` files on Windows. Allowlist the real program instead, for
         example `node.exe`.
       - This is the same family as `claude.cmd` dropping arguments after a newline (§4).
3. **The policy engine.**
   - It is called with every rule (`plugin=None`) and `unknown="deny"`, so the tool list is an allowlist. A tool
     the engine does not know is denied (rule `allowlist`). No argument or variable changes this.
   - An error in a check is a deny (`evaluate_closed`).
   - `ask` is a deny for now. The reason says that a person's approval is needed and that MCP has no approval path
     yet.
4. **The action.**
   - **exec:**
     - no shell; `shell=False`, with argv exactly as given;
     - the policy sees `shlex.join(argv)`, and the shell rules parse that string back into the same words;
     - cwd is the root;
     - the environment holds only `EXEC_ENV_ALLOW`;
     - stdin is closed;
     - a timeout (120 s by default, 600 s at most) kills the whole process tree (`taskkill /T` on Windows, a
       process group on POSIX);
     - output beyond 100,000 bytes is dropped while reading, so a huge output never sits in memory, and is
       reported as truncated.
   - **read:**
     - text, decoded as UTF-8 with replacement;
     - optional `offset` and `limit` in lines;
     - files over 20 MB are refused;
     - output is capped at 256,000 characters.
   - **write:** the whole file, with bytes exactly as given; parent folders are created inside the root.
   - **edit:**
     - `old_string` must occur exactly once, unless `replace_all` is set;
     - the file is edited as bytes, with no newline translation.

Every decision goes to stderr. With `--audit-log`, it also goes to a JSONL file:
- each row holds the time, tool, decision, rule and reason, and no file contents;
- for exec it also holds `argv`, at most 20 arguments of at most 200 characters each. A command line is not file
  contents, and it is what an investigation needs afterwards;
- the log must be outside the root, or the server does not start.

### The exec environment

`EXEC_ENV_ALLOW` is `run_digest.py`'s `ENV_ALLOW` minus `CREDENTIAL_ENV`:
- removed: `ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_BASE_URL`,
  `CLAUDE_CONFIG_DIR`, `CLAUDE_CODE_GIT_BASH_PATH`;
- why: that list is what the agent process needs to log in, and a command the agent runs needs none of it;
- `CLAUDE_PROJECT_DIR` and `RAK_*` are not in it either, so a child process cannot be pointed at another root;
- a test keeps the two lists in step.

### P1: the policy's own files

P1 is a new rule (plugin `rak-policy`). File tools may not write anything that enforces a rule, runs as a hook
or in CI, or configures an agent; reads are allowed.

`checks_policy.protected_name()` makes the match. The sandbox's `host.py` uses the same function, so L1 and L2 cannot
disagree about which names are protected. It compares path components, at any depth:
- case is ignored;
- trailing dots and spaces are dropped, since Windows drops them;
- a component that looks like an 8.3 short name (`GIT~1`) counts as protected.

It judges the name as the agent gave it and also the resolved path. Resolving folds `.claude ` back to `.claude`
only when that folder exists, so a check on the resolved path alone missed the spelling in a new folder (found
after the sandbox review of 2528365, maintainer 2026-11-01). Below, `*` is one path component.
- The engine:
  - `*/rak/policy/*`
  - `*/_vendor/rak_policy/*`
  - `*/rak/mcp_server.py`
- Project state: `*/.rak/*` (freeze records, gates, config).
- Claude Code and plugins:
  - `*/.claude/*`
  - `*/.mcp.json`
  - `*/.claude-plugin/*` (manifests declare hooks; the marketplace decides which plugins are installed)
- Hooks and their backends:
  - `*/plugins/*/hooks/*`
  - `*/hooks.json`
  - `*/plugins/*/scripts/*`: `rak_discipline.py` is reloaded on every hook call, `rak_cloud.py` holds the tree
    pin, and `gpulock.py` lives here too
  - `*/plugins/*/trees/*`
- Git hooks:
  - `*/scripts/hooks/*`
  - `*/.husky/*`
  - `*/.githooks/*`
  - `*/.pre-commit-config.yaml`
  - `*/lefthook.yml` and `*/.lefthook.yml`
- CI (L3):
  - `*/.github/*`
  - `*/.gitlab-ci.yml`
  - `*/.circleci/*`
  - `*/azure-pipelines.yml`
  - `*/jenkinsfile`
- Other agents and editors: `*/.gemini/*`, `*/.codex/*`, `*/.vscode/*`, `*/.idea/*`, `*/.devcontainer/*`.
- Git and the shell: `*/.git/*` (the server refuses it before the engine too), `*/.gitmodules`, `*/.gitattributes`,
  `*/.envrc`.
- The scanner and its allow file: `*/scan_private.py` and `*/.rak-scan-allow`.

The engine's own folder is protected wherever it is.

Considered and left writable:
- **Context files** (CLAUDE.md, AGENTS.md, GEMINI.md). Agents edit these as a normal part of the work. A rule that
  froze them is the owner's call.
- **Package scripts** (`package.json` `scripts`, `pyproject.toml` entry points). Through an allowlisted package
  manager they run code. Blocking every manifest would block normal work, so this is threat model item 1.

This is a second layer: an allowed command can still write these files. See §3.

## 2. Where the MCP server and the Claude Code hooks differ

| | Claude Code hooks (`plugins/*/hooks/`) | MCP server |
|---|---|---|
| Tools outside the engine's list | allowed (a hook sees only what its matcher names) | **denied** (`unknown="deny"`, fixed) |
| Rules evaluated | the plugin's own (`plugin="rak-team"`, ...) | all, including P1 |
| Project root | walk up from cwd; `CLAUDE_PROJECT_DIR` for the team rule | `--root`, nothing else |
| Engine error | exit 2 (block) with the plugin's message | deny (`evaluate_closed`) |
| `ask` | `permissionDecision: "ask"`, exit 0: Claude Code asks the person | deny, with the reason |
| Path confinement, `.git`, links | none (the agent's native tools apply Claude Code's own permissions) | §1 step 2 |

The hooks stay unchanged apart from `ask` (no rule uses `ask` yet). The differential tests of step 1 still hold.

## 3. Threat model

**What the server is for.** It is the one place where every shell and file action of an agent passes through our
rules, whatever the model and whatever the agent (Claude Code, Gemini CLI; Codex in part; see §5).

**What it holds**, when the agent's native tools are really off (§4):
- no file tool reads or writes outside the root, or under `.git`;
- no file tool writes the policy, the hooks or project state;
- no program runs unless it is allowlisted and lives outside the root;
- no shell parsing at all;
- no credential variables in commands;
- every call passes the discipline, team and tree rules, and is logged.

**What it does not hold.** Each is either for L1 or a known limit:
1. **An allowed program's own arguments are not confined.**
   - Examples: `git -C /elsewhere`, `git --git-dir`, `python -c "open('/etc/...')"`. An allowlisted interpreter
     (`python`, `node`, `bash`) can do anything the OS user can.
   - `git` is not safe either: aliases with `!`, `core.pager`, `core.hooksPath` and hooks all run arbitrary
     commands.
   - `--exec-allow` is a list of programs you trust with **any** arguments. Keeping a program inside the root is
     L1's job: a read-only mount outside the project, and network rules.
   - The exception that *was* a bug: on Windows, a `.cmd` or `.bat` on the list turned exec into an arbitrary
     shell (`&` started a second command), and the shell rules did not see it. Only `.exe` and `.com` run now
     (§1).
2. **The server's code and rules must be where the agent cannot write** (cross-review of fb10c8b).
   - `RULES_SHA256` and P1 are speed bumps. An allowed command (`python`, `git`) can still rewrite
     `python/rak/policy/` when it sits inside the root.
   - The real fix is an L1 matter: the server runs from a read-only location or as another OS user, outside the
     agent's sandbox. That step is not implemented yet.
3. **Races.**
   - The path is checked, then used. A process the agent started earlier with exec could swap a symlink in
     between.
   - Calls are handled one at a time, so only a background process can do this. L1 (no write outside, no
     long-lived processes) closes it.
   - Background processes include the grandchildren of an exec that ended normally. Only a timeout kills the
     process tree, so a process that a finished command left running lives on. L1 has to clean those up too.
4. **Context files** (CLAUDE.md, AGENTS.md, GEMINI.md) and @-mentions are read by the agent without a tool call.
   The server never sees them. A file the agent must not read has to be outside its sandbox.
5. **Other native tools of the agent.** Only what the adapter turns off is off (§4).
   - For Claude Code the adapter uses an allowlist (`--tools ""`), so a built-in tool added in a later version
     stays off.
   - A launch without that flag falls back to the deny list. A tool missing from that list is on, as PowerShell
     was in the first smoke run.
6. **Denial of service.**
   - Limits exist: the timeout, the output cap, the read size limit.
   - There is no limit on how many calls are made, or on disk use by writes.
7. **The audit log is not tamper-proof.** It is outside the root, but only L1 keeps the agent from reaching it.

**Fail closed, no bypass.**
- Any exception before the action is a deny.
- A malformed message gets a JSON-RPC error and no action.
- There is no debug mode and no flag that relaxes confinement or the allowlist. A test checks that `Server` and
  the argument parser have no such switch.

## 4. Claude Code adapter (`examples/claude-code-mcp/`)

- `mcp.json`: registers the server (`type: stdio`, `--root` as an absolute path, `PYTHONPATH` to `python/`).
- **The allowlist is `--tools ""`** on the launch line. It turns off every built-in tool, and the MCP tools
  remain:

  ```
  claude --tools "" --settings examples/claude-code-mcp/settings.json --mcp-config <your mcp.json> --strict-mcp-config
  ```

- **`settings.json` is the second layer.** It denies Bash, PowerShell, Monitor, Read, Edit, MultiEdit, Write,
  NotebookEdit, Glob, Grep, WebFetch and WebSearch, and allows the four `mcp__rak__*` tools. For a lock the user
  cannot undo, put the same keys in managed settings.
- Tests check three things: the deny list, that exactly the four MCP tools are allowed, and that every launch line
  in the example's README carries `--tools ""`.

**Real-CLI checks (2026-11-01, Claude Code 2.1.316, haiku; each approved by the maintainer).** Before any result was
read, each run checked the `init` event:
- the model was haiku;
- `rak` was `connected`;
- every tool other than `mcp__rak__*` was on an explicit allowlist.

A run that failed any of these was stopped there.

1. **Deny list only, 9 steps, US$0.0084** (`total_cost_usd`).
   - In order:
     - native Bash and Read: not available;
     - `read ../outside_canary.txt`: denied (`..`);
     - the same file by absolute path: denied (outside the root);
     - `read .git/config`: denied;
     - `exec curl`: denied (not allowlisted);
     - `read notes.md`, `write out.txt` and `exec git status`: done.
   - The canary token never appeared in the output, and the audit log matched step by step.
   - **It found a gap.** On Windows the tool list still had **PowerShell**, a built-in shell. That version of the
     example did not deny it, and the gate then checked only four names.
   - Agent, Workflow, Skill, the Cron tools, RemoteTrigger and SendMessage were there too.
2. **`--tools ""`, stopped at `init`: 0 model calls** (the transcript has no message with usage). The tool list
   was exactly `mcp__rak__edit`, `exec`, `read` and `write`.
3. **`--tools ""`, the same 9 steps, US$0.0023.**
   - The same denials and successes as run 1.
   - The tool list held only the four MCP tools, and the model reported no other tools.

Not checked: whether `--tools` can be set in a settings file. We treat it as a command-line flag.

**Windows notes.**
- `claude` on Windows is `claude.cmd`, which runs through `cmd.exe`. **An argument with a newline is cut at the
  newline, and every argument after it is dropped.**
  - Our first smoke run passed a multi-line prompt as an argument. `--model`, `--settings` and `--mcp-config`
    never arrived, and the default model answered "your message got cut off". It made no tool call, and its cost
    is in the transcript usage only.
  - Pass the prompt on stdin (`claude -p` reads it there), and check that no argument contains `\n` or `\r`.
  - Or call `node_modules/@anthropic-ai/claude-code/bin/claude.exe` directly. That is what `claude.cmd` runs.
    This also keeps an empty argument (`--tools ""`) intact.
  - Before reading any result, check the `init` event: the model, `mcp_servers` connected, and the tool list.
- PowerShell is a built-in tool on Windows. A deny list written with Bash in mind misses it.
- The same family on the server side: a `.cmd` or `.bat` runs through `cmd.exe`, so exec runs only `.exe` and
  `.com` (§1).
- The server kills a timed-out command's process tree with `taskkill /T /F`.

## 5. Other agents (documented, not tested)

These come from `docs/harness-landscape.md` §3 and its sources. **None of it has been run.**

- **Gemini CLI.**
  - Register the server under `mcpServers` in its settings (command, args, env), with the same arguments as
    above.
  - Deny `run_shell_command`, `read_file`, `read_many_files`, `write_file`, `replace`, `glob`, `grep_search`,
    `list_directory`, `web_fetch` and `google_web_search` through its policy engine.
  - System settings and admin policies override the user's. `@file` goes through `read_many_files`, so denying
    that tool covers it. GEMINI.md is read directly.
- **Codex CLI.**
  - Register the server under `[mcp_servers.rak]` in `config.toml`, and set `[features] shell_tool = false`.
  - **No documented switch turns off `apply_patch`**, so file writes have an unguarded path. Whether
    `exec_command` survives `shell_tool = false` is undocumented.
  - Until both are settled, Codex counts as "L1 + L3 only", not as enforced by this server.
- **OpenClaw.** The tools can be denied (`group:runtime`, `group:fs`), but nothing stops the operator from undoing
  that. It gets the same "L1 + L3 only" label.

## 6. Tests

- `python/tests/test_mcp_server.py`:
  - start-up refusals, and the root coming from the argument;
  - the four tools; unknown tools and bad arguments;
  - `..`, outside paths, `.git` (with case and trailing-dot forms on Windows);
  - symlinks (run in WSL; Windows without developer mode cannot create them), junctions and 8.3 names (Windows);
  - hard links;
  - write and edit; P1; D6 through the engine;
  - exec: argv only, the environment allowlist, the program allowlist, programs inside the root, T1–T3,
    engine errors, `ask`, the timeout and the output cap;
  - the audit log; the stdio protocol as a subprocess;
  - the example: the settings, and `--tools ""` on every launch line;
  - cross-review:
    - `.cmd`, `.bat`, `.vbs`, `.js` and `.ps1` refused on Windows, using the reviewer's reproduction;
    - lookup that ignores the current directory (red on Python 3.10, green on 3.14 even before the fix);
    - the discipline module instance carries the root, with `CLAUDE_PROJECT_DIR` pointed elsewhere;
    - exec `argv` in the audit log;
    - P1 over manifests, hook backends, git hooks, CI and other agents' config.
- `python/tests/test_policy_engine.py`: the allowlist mode, P1, and `ask` in the three hooks.
- Mutants, each caught by a failing test:
  - the `.git` check removed;
  - `unknown="allow"`;
  - `abspath` in place of `realpath`;
  - the full environment passed through;
  - the hard-link check removed;
  - `project_root` walking up;
  - programs inside the root allowed;
  - the program allowlist removed;
  - `ask` allowed;
  - `.rak/` dropped from P1;
  - the output cap removed.
