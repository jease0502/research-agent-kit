# L1 sandbox: the whole agent in a container

L1 of the three layers in [docs/harness-landscape.md](../../docs/harness-landscape.md) §4. Claude Code and our MCP
server ([docs/mcp-server.md](../../docs/mcp-server.md)) run in one container. The operating system, not our code,
holds the lines the MCP server cannot hold: an allowed `python3 -c` can do anything the user can, so the user must
not be able to do much.

## Two modes

**copy (the default).** The project folder never reaches the container.
1. `run.sh` copies the tracked and untracked-but-not-ignored files into a tar. It leaves out `.git` and every
   protected path (below), and any file whose real path is not where it is listed: nothing is copied through a
   symlink or a Windows junction, at any level (Git for Windows lists files inside junctions).
2. It loads the tar into a fresh Docker volume, which the agent sees as `/work`.
3. After the run it exports the volume. `host.py inspect` judges the change from the tar entries alone, without
   extracting anything on the host.
4. If the change is clean, git writes the patch inside a container: `$RAK_AUDIT/runs/<time>/changes.patch`, with
   `summary.json` beside it.
5. You review the patch and apply it with `git apply -p1 <patch>`.
- The whole run is refused (exit 3, no patch) when a changed path:
  - is protected, at any depth and in any spelling (other case, trailing dots or spaces, an 8.3 short name such as
    `GIT~1`, another Unicode form, invisible characters such as U+200C);
  - creates something that looks like a git repository under another name (`HEAD` with `objects/` and `refs/`,
    or a `config` with a `[core]` section);
  - is a symlink or special file;
  - differs from another only by case or Unicode form;
  - ends in a dot or space, or contains an invisible character;
  - is a Windows reserved name, or has a character Windows does not allow.
- The agent cannot commit, because there is no `.git` in the copy.

**mount (advanced).** The project folder itself is mounted read-write, with the protected folders and files mounted
read-only over it.
- Only on a case-sensitive filesystem without 8.3 names: Linux, a case-sensitive macOS volume, or WSL2's ext4.
- On a Windows path it is refused, and it is refused whenever `host.py` cannot tell.
- Why: on NTFS, `/work/.GIT/hooks`, `/work/GIT~1/hooks` and `/work/.git./…` reached the host's `.git` around an
  overlay mounted at `/work/.git` (review of 1a90306, reproduced here before the fix).
- After the run, any change to a protected path, at any depth, is moved to `$RAK_AUDIT/quarantine/<time>/`, the
  original (file or symlink) is put back, and the run exits 3. Only paths that exist at the top level can be
  mounted read-only during the run; nested ones are caught afterwards. A Linux folder with per-directory casefold
  (`chattr +F`) is not detected by the check, which tests the project's root only.

Protected paths (`host.py`, kept in step with the policy engine's P1 list by a test):
- folders: `.git`, `.claude`, `.claude-plugin`, `.github`, `.husky`, `.githooks`, `.circleci`, `.gemini`, `.codex`,
  `.rak`, `.vscode`, `.idea`, `.devcontainer`, `scripts/hooks`;
- files: `.mcp.json`, the pre-commit, lefthook, GitLab, Azure and Jenkins configs, `.rak-scan-allow`, `.envrc`,
  `.gitmodules`, `.gitattributes`.

These are the paths that git, an editor, CI or another agent runs on the host later. They count at any depth:
`sub/.claude/settings.json` is read by an agent started in `sub/`, and `sub/.vscode/tasks.json` by an editor opened
there.

On the host, set `git config --global safe.bareRepository explicit`: git then ignores a bare repository it finds in
a working tree unless you name it, which is the host-side defence against a planted one.

## What it holds

| What | How | Checked by |
|---|---|---|
| The host's project does not change during a run (copy mode) | the agent works on a copy; changes come back only as a patch you apply | `verify.py probe` (the host tree, `.git` included, is compared byte for byte) |
| The policy engine, plugins, MCP server and settings cannot be changed | the kit is mounted **read-only** at `/opt/rak`, the settings at `/opt/rak-config`; the image's own filesystem is read-only | `probe_l1.py`, canary step 9 |
| Nothing survives from one run to the next | the home folder is a fresh tmpfs on every run, and Claude Code starts with `--restricted --setting-sources=`, so no user, project or local settings file is read (no planted hooks) | `probe_l1.py` |
| The host's files are not there | only the project (copy or folder), the kit, the config and the audit FIFO folder are mounted. No Docker socket | `probe_l1.py`, canary step 8 |
| The network is the allowlist | the agent sits on an `internal` Docker network with no route out. Its only exit is `egress_proxy.py`. The proxy: opens HTTPS tunnels (CONNECT to port 443) to listed hosts only; resolves them itself and refuses non-public addresses; requires the TLS ClientHello's SNI to be the tunnel's host. No SNI, a repeated extension, or Encrypted Client Hello: cut. No plain HTTP and no outside DNS | `probe_l1.py`, `test_sandbox_proxy.py`, canary step 10 |
| The MCP audit log cannot be erased by the agent | the MCP server writes to a FIFO the agent's group may only write; a separate container (uid 10002) appends each line to `RAK_AUDIT` on the host, which the agent does not mount | `probe_l1.py` |
| No privileges | user 10001, every Linux capability dropped, `no-new-privileges`, process and memory limits | `probe_l1.py` |
| No host credentials | the host's `~/.claude` is not mounted. The run gets `CLAUDE_CODE_OAUTH_TOKEN` (from `claude setup-token`) or `ANTHROPIC_API_KEY` from your environment | `run.sh` refuses without one |

Inside the container, Claude Code starts with `--tools ""`, so its only tools are the four `mcp__rak__*` tools. The
MCP server then applies the policy engine. L1 does not replace that layer; it covers what that layer cannot.

## Use

```
cd <this kit>
templates/sandbox/run.sh build                                  # once per Claude Code version (~1 GB image)

export RAK_PROJECT=/abs/path/project
export RAK_KIT=/abs/path/research-agent-kit                     # read-only; must not contain the project
export RAK_AUDIT=/abs/path/outside/the/project/audit            # patches, audit log, quarantine
export CLAUDE_CODE_OAUTH_TOKEN="$(cat ~/.config/rak-sandbox/oauth_token)"   # or ANTHROPIC_API_KEY
templates/sandbox/run.sh claude --model claude-haiku-5-5 < prompt.txt
# review $RAK_AUDIT/runs/<time>/summary.json and changes.patch, then in the project:
git apply -p1 "$RAK_AUDIT/runs/<time>/changes.patch"
templates/sandbox/run.sh down                                   # stop the proxy and the audit collector
```

- `run.sh` refuses:
  - a project that is a drive root, your home folder, or contains it;
  - a kit inside the project, or a project inside the kit;
  - an audit folder inside the project.
  It compares real paths, ignoring case where the filesystem does.
- `RAK_MODE=mount` selects mount mode.
- `RAK_EGRESS_ALLOW` sets the allowlist. The default is `api.anthropic.com arxiv.org export.arxiv.org`. For another
  vendor's model ([docs/model-profiles.md](../../docs/model-profiles.md)), add its endpoint host and set
  `ANTHROPIC_BASE_URL`.
- Edit `config/mcp.json` for the programs `exec` may run. Every program listed there can run with any arguments
  (docs/mcp-server.md §3). In copy mode `git` has no repository to work on.
- Each audit line is wrapped as `{"received": ..., "line": <the MCP server's JSON>}`.

## Verify on your machine

```
python templates/sandbox/verify.py probe  --project <dir> --audit <dir>     # no model, no cost
python templates/sandbox/verify.py canary --project <empty dir> --audit <dir> --model claude-haiku-5-5
```

- `probe` runs `probe_l1.py` in the agent container in copy mode. It checks mounts, read-only paths, the home
  tmpfs, the audit FIFO's permissions, capabilities, egress allowed and blocked, direct connections and DNS.
- It also plants git hooks and agent config in every spelling from the review. Then it checks three things: the run
  is refused (exit 3), the refusal names each planted path, and the host project is byte for byte what it was,
  `.git` included.
- It sends four calls through the MCP server that the server allows. A refusal by the policy engine does not count
  as an L1 refusal.
- Mount mode must be refused on a Windows path.
- `canary` asks the model to run ten steps through the MCP tools:
  - the MCP smoke steps of docs/mcp-server.md §4;
  - three steps only L1 can stop: list the host's drives, write the rules file, reach example.com.
- The canary resets its project folder first. It only does that to an empty folder, or one carrying the
  `.rak-sandbox-canary` marker it wrote itself; it refuses anything else rather than delete it.
- Checks are judged from the tool results Claude Code wrote, never from what the model says.
- Before judging, the canary checks the `init` event: the tool list must be `mcp__rak__*` only, and `rak` must be
  connected. The number of new audit lines is reported, not judged.

## Platforms

| | Windows | macOS | Linux |
|---|---|---|---|
| Runtime | Docker Desktop (WSL2 backend) | Docker Desktop | Docker Engine (rootless or `userns-remap` recommended) |
| Modes | copy; mount only for a project in WSL2's ext4 | copy; mount only on a case-sensitive volume (APFS is case-insensitive by default) | copy or mount |
| Paths in `RAK_*` | `D:/x` or `/d/x` from Git Bash; `run.sh` converts with `cygpath` and sets `MSYS_NO_PATHCONV=1` | normal | normal |
| Host Python | needed for `host.py`; the Microsoft Store alias is skipped | needed | needed |
| File ownership (mount mode) | n/a | files the agent writes look like yours | written as uid 10001; use rootless Docker, which maps it to you |

Tested here: Windows 11, Docker Desktop with Docker 28.5.2, Claude Code 2.1.316, copy mode. Mount mode is only tested
for refusing a Windows path. macOS and Linux are documented, not tested.

### Without Docker: a WSL2 distro (Windows only, weaker, not tested)

- Use a dedicated distro, not your everyday one. Put this in `/etc/wsl.conf`:

  ```
  [automount]
  enabled = false        # no /mnt/c: the Windows drives are not mounted
  [interop]
  enabled = false        # no running Windows programs (cmd.exe, powershell.exe) from inside
  appendWindowsPath = false
  ```

- Then run `wsl --terminate <distro>` so the settings take effect.
- Clone the kit into the distro and make its folder read-only to the agent's user (a separate owner, mode 755).
- The gaps:
  - No network allowlist unless you add one yourself, for example with iptables owner rules and the same proxy.
  - No copy mode, no overlays.
  - The distro shares the WSL2 VM's kernel with Docker Desktop and other distros.
- Prefer the container.

## What L1 here does not hold

- **The model's token is readable inside the container.**
  - Claude Code needs it in its environment.
  - Any process of the same user can read `/proc/<pid>/environ`, including a child the MCP server starts with a
    filtered environment (review of 6555c3c, M3). Holding the token in a file and deleting it after reading does
    not change that.
  - The real fix is running the MCP server's `exec` under another uid or in another container. That is not done.
  - Until then: use a token you can revoke, scoped to this use, and rotate it.
- **The allowed hosts are channels.**
  - Anything the agent can read can be sent to an allowed host. That includes the model's own API, which receives
    everything the agent sees anyway.
  - The SNI check stops a tunnel from carrying TLS for another name. It cannot stop a request inside a TLS session
    for the allowed name whose HTTP `Host` header names another site, on CDNs that still route that way.
  - After a TLS 1.3 HelloRetryRequest the second ClientHello is not checked again. The server picked its virtual
    host from the first one.
  - An allowed host on a shared CDN therefore exposes more than that host. Keep the list short.
- **A patch is still code you run.** In copy mode the protected paths cannot come back, but an ordinary source file
  can. Read the patch before applying it, as you would a pull request.
- **The audit log can be padded, and can stall.**
  - The agent can write forged lines into the FIFO; it cannot remove or change real ones.
  - Lines over 4096 bytes can interleave with a forged write made at the same moment.
  - If the collector dies, the MCP server blocks when it opens the FIFO. That fails closed: no tool call goes
    through until the collector is back. Docker restarts it unless stopped.
- **The container is not a VM.** A kernel or Docker escape gets out. On Windows and macOS the Docker Desktop VM is
  a second wall; on Linux, use rootless Docker.
- **The proxy and the collector are trusted code.** Both are short and standard library only (`egress_proxy.py`,
  `audit_collector.py`). Review them like the policy engine. The proxy accepts at most 64 connections at once.
