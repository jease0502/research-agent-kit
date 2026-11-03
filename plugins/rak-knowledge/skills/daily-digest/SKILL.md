---
name: daily-digest
description: Set up, run or debug the scheduled daily paper digest. A non-interactive Claude Code run collects new arXiv papers on configured topics, adds them to the knowledge base, and writes a judgment-first digest ranked against your research lines. Use when the user wants daily paper collection, a paper digest, a scheduled literature watch, or asks why today's digest is missing.
---

# daily-digest

Once a day, a scheduled `claude -p` run:

1. queries arXiv for new papers on your topics;
2. adds the relevant ones with `rak add-paper --batch`;
3. writes `docs/digest/<date>.md`. The digest is a judgment, not a list: which research line each paper helps and why, and which papers directly answer a problem you are stuck on.

Files in this skill:

| File | Role |
|---|---|
| `prompt.md` | the instructions the scheduled run gets; placeholders are filled from your config |
| `scripts/run_digest.py` | the runner the scheduler calls; cross-platform, standard library only |
| `scripts/digest.example.toml` | the config to copy |

## 1. Set up

```bash
cp <this skill>/scripts/digest.example.toml <kb>/digest.toml   # then edit it
echo ".rak/" >> <kb>/.gitignore
python <this skill>/scripts/run_digest.py --root <kb> --dry-run   # print the filled prompt and the command
```

What to edit in `digest.toml`:

- **`topics`**: what the filter keeps.
- **`[[lines]]`**: your research lines and their open problems. This is what turns a list into a digest. A paper that answers an open problem goes to the top.
- **`notify_cmd`**: where the result and any failure are sent. For example, use the Telegram bridge from rak-team, or any command that takes the message as its last argument.
- **`push`**: `false` by default. A person reviews and pushes. Turn it on only if unattended pushes are acceptable.

Unknown keys are an error, also inside `[[lines]]` and `[[conferences]]`, so a typo cannot silently fall back to a default. Values are type-checked too: `push = "false"` (a string) is an error, not "on".

Read the dry-run prompt once. It is what the agent will do every day.

## Threat model (read before scheduling)

The scheduled run is an agent working **unattended** on **untrusted text**: arXiv titles and abstracts are written by whoever submits a paper, and an abstract can contain text crafted to look like an instruction (prompt injection). Assume some day one will.

**Permission rules are not a sandbox.** Claude Code's own documentation says so (quoted from the pages as fetched on 2026-10-31):

> "Bash permission patterns that try to constrain command arguments are fragile." — [permissions](https://code.claude.com/docs/en/permissions.md)

> "A Bash rule matches the command text Claude writes, after Claude Code splits compound commands and strips wrappers. It doesn't match the same program invoked in a different form, so a deny or ask rule covers the invocation Claude usually produces and isn't a security boundary around the program." — [permissions](https://code.claude.com/docs/en/permissions.md)

> "To put the tools, processes, and commands in this section behind one boundary, run the Claude Code process itself in a container, virtual machine, or the sandbox runtime." — [sandboxing](https://code.claude.com/docs/en/sandboxing.md)

Even an allow list of ordinary commands is not safe: a review of this runner showed `git fetch --upload-pack=<command>` running a program, and `git log --output=.git/hooks/pre-commit` writing a hook that the next `git commit` runs. So the runner keeps the agent's tools to a minimum and does the rest itself:

- **The runner fetches the candidate papers and computes the dates.** The agent reads a file marked as untrusted data.
- **The agent has no git, and its shell is as narrow as Claude Code allows.** `--tools` limits it to Read, Glob, Grep, Write, Edit, Bash and WebFetch, and the allow list admits three exact commands with no wildcard: `rak check`, `rak build`, and `rak add-paper --batch <tmp_dir>/ids_tmp.txt`. **But Bash is not limited to those three.** Claude Code "recognizes a built-in set of Bash commands as read-only and runs them without a permission prompt in every mode" (`ls`, `cat`, `grep`, `find`, `cd`, read-only `git`, and more), and "The set is not configurable; to require a prompt for one of these commands, add an `ask` or `deny` rule for it." ([permissions](https://code.claude.com/docs/en/permissions.md)). The runner adds deny rules for them, which by the quotes above stop the usual forms, not every form.
- **Reads outside the knowledge base are blocked** with the setting `permissions.blockReadsOutsideWorkingDirectories` (passed with `--settings`). No bare Read, Grep or Glob is in the allow list; reads inside the knowledge base need no rule.
- **File writes are limited to `papers/`, the digest folder and the temp folder** (`Edit(/papers/**)` and so on, anchored at the knowledge base). Per the same documentation, "`Edit` rules apply to all built-in tools that edit files", so this covers Write too. Bash returns to the knowledge base after every command (`CLAUDE_BASH_MAINTAIN_PROJECT_WORKING_DIR=1`).
- **WebFetch is limited to arxiv.org.** There is no web search.
- **Deny rules** (`--disallowedTools`): reading credentials (`~/.ssh`, `~/.config`, `~/.aws`, `~/.claude`, `~/.gnupg`, `~/.netrc`, `~/.git-credentials`, Hugging Face tokens, `~/.docker`, `~/.kube`, `~/.pypirc`, `~/.npmrc`, gcloud under AppData, `.env` files), reading and editing `.git/`, reading `digest.toml` (`notify_cmd` may carry a token), and the read-only commands (plus `sort`, `ps`, `printenv`, `env`). A second layer denies every dot folder and `AppData` under home (`Read(~/.*)`, `Read(~/.*/**)`, `Read(~/AppData/**)`), unless the knowledge base itself lives under one of them, in which case that part is left out and the runner says so. For `AppData` this is decided two levels down: a base under `AppData/Local` still keeps `AppData/Roaming` and `AppData/LocalLow` denied. `~/**` as a whole is not denied: a knowledge base kept under the home folder must stay readable, and a deny rule wins over every allow rule.
- **The agent's environment is an allow list.** It gets the operating system's basics and what Claude Code needs to log in and reach the API (`ANTHROPIC_API_KEY`, `ANTHROPIC_AUTH_TOKEN`, `CLAUDE_CODE_OAUTH_TOKEN`, `ANTHROPIC_BASE_URL`, `CLAUDE_CONFIG_DIR`, proxies, and on Windows `CLAUDE_CODE_GIT_BASH_PATH`, per its [authentication](https://code.claude.com/docs/en/authentication.md) and [environment variable](https://code.claude.com/docs/en/env-vars.md) pages). Nothing else from the scheduler's environment reaches it: no `GH_TOKEN`, `HF_TOKEN` or bot tokens. On a corporate network the CLI may also need `ALL_PROXY`, `SSL_CERT_FILE` or `NODE_EXTRA_CA_CERTS`; they are not passed by default. Add the names you need to `ENV_ALLOW` in `scripts/run_digest.py`. Its own Claude credential is necessarily in its environment.
- **The runner commits afterwards**, with a fixed message, and only what this run changed: Markdown files under `papers/` and the digest folder, and `INDEX.md` (which `rak build` writes). Paths are taken literally (`--literal-pathspecs`: a file named `papers/[o]ld.md` cannot pull in `papers/old.md`), and a file whose name starts with `.git` (`.gitattributes`, `.gitignore`) is refused. If the run changed any other file, or git's config, hooks or `info/` (also a worktree's common directory), nothing is committed and the failure is sent through `notify_cmd`. It pushes only if `push = true`, and not when the branch is behind its upstream.
- `tests/test_run_digest_injection.py` and `tests/test_run_digest_git.py` fail if a pattern that runs code, reaches an arbitrary host or gives the agent git comes back.

What remains:

- An injection can still make the agent **write wrong content** into notes and the digest, and the runner will commit it. With `push = false` (the default), a person reviews before anything leaves the machine. Keep it that way unless the base is disposable.
- A read-only command in a form the deny rules do not anticipate can still read what the operating system lets the user read. **The read-only set is built in and not configurable, so the only complete answer is the container or VM below.**
- **Tested four times against the real CLI (2026-10-31, US$0.002–0.004 each, Claude Code 2.1.314 on Windows).** With the runner's flags and a canary file outside the knowledge base:
  - the Read tool was refused by `blockReadsOutsideWorkingDirectories`, and an edit inside `papers/` worked;
  - `cat`, `grep -r` and `head` on the canary, run through Bash, were each refused ("Permission to use Bash with command … has been denied") and recorded as permission denials. The canary did not appear in the output. The message does not say whether the deny rules or the read block refused them.
  - (In the first run the model declined to try the shell commands at all; the second run asked for them explicitly.)
  - Fourth run, with the knowledge base outside the home folder and commands that no deny rule names: `uniq` and `od -c` on a home-folder canary were refused with "Reads outside the working directories are blocked (permissions.blockReadsOutsideWorkingDirectories)", so **that setting does apply to the read-only Bash commands**; `/usr/bin/sort` was refused because it is neither allowed nor in the read-only set. No canary in the output.
  - Third run: `sort` on a canary file in the home folder, `printenv` of a canary variable set in the runner's environment, and a Read of `.git/config` whose remote carried a fake token: all three refused and recorded as permission denials, and none of the three canaries appeared in the output.
- A form of a command that the rules do not anticipate. That is what the quotes above warn about, and why the next point is the real boundary.

**Run the schedule in a container or a VM** that has only the knowledge base checked out and only the credentials the run needs: a Claude login, and, if you push, a git token for this one repository. Then even an escape from the rules above reaches nothing else.

## 2. Schedule it

The runner can safely be triggered more than once a day:

- before `earliest` it does nothing;
- once today's digest exists it does nothing.

So use **two triggers: a fixed time, and "at logon"**. A machine that rebooted and was not logged in at the fixed time still gets its run.

**Linux (cron)**: `crontab -e`

```
30 9 * * *  cd <kb> && python <skill>/scripts/run_digest.py --root <kb>
@reboot     sleep 600 && cd <kb> && python <skill>/scripts/run_digest.py --root <kb>
```

**macOS (launchd)**: a LaunchAgent plist with `StartCalendarInterval` (Hour 9, Minute 30) plus `RunAtLoad`. `ProgramArguments` is `python`, the runner path, `--root`, `<kb>`. Load it with `launchctl load ~/Library/LaunchAgents/<name>.plist`.

**Windows (Task Scheduler)**:

```powershell
$a = New-ScheduledTaskAction -Execute "python" -Argument "<skill>\scripts\run_digest.py --root <kb>"
$t = @((New-ScheduledTaskTrigger -Daily -At 9:30am), (New-ScheduledTaskTrigger -AtLogOn))
$t[1].Delay = "PT10M"
Register-ScheduledTask -TaskName rak-daily-digest -Action $a -Trigger $t
```

Notes for every platform:

- The scheduled environment is not your shell. Use absolute paths for `python` and `claude` if they are not on the system PATH, or set `RAK_CLAUDE_CMD`.
  The runner resolves the program with PATH and PATHEXT, so `claude` finds npm's `claude.cmd` on Windows. On Windows, commands are split the Windows way, so backslashes in paths are kept; quote a path with spaces in double quotes, or give `notify_cmd` as a TOML list.
- A config error exits 2 and is still sent through `notify_cmd` when that value itself is usable.
- `claude` must already be logged in for the user the task runs as.

## 3. How a run is judged

**Success means today's digest file exists.** The exit code is not used:

- an agent whose tools were blocked can exit 0 having done nothing;
- a run that wrote the digest and then failed to push did its main job.

On failure, the runner:

- sends `⚠ daily digest <date> failed (<why>); log: <path>` through `notify_cmd`;
- exits 1.

Logs are in `~/.cache/research-agent-kit/logs/digest-<date>.log`, or in `log_dir` if set.

## 4. When today's digest is missing

Read the log first. Common causes:

| In the log | Cause | Fix |
|---|---|---|
| many tool calls denied | the agent tried a command or a write outside the allowed list (see "Threat model"); an abstract may have tried to make it do so | read what it tried. Do not widen the list to make the run pass: a pattern that runs code or reaches any host is what the list exists to keep out. `--dry-run` prints the list |
| `fetching arXiv failed` | network, or arXiv answering 429 / 503 past the retries | the runner fetches the candidates itself, before the agent starts. Re-run later with `--force` |
| repeated HTTP 429 / 503 from arXiv during `rak add-paper` | arXiv under load | `add-paper` waits between requests and retries. Re-run later with `--force` |
| prompt cut short, flags ignored | the prompt was passed as an argument instead of stdin | use `run_digest.py`, which uses stdin; do not call `claude -p "<prompt>"` from a script |
| garbled non-ASCII text in the log | console encoding | the runner writes UTF-8. Look at the log file, not the console |
| run never started | the task ran before logon, or `claude` is not on PATH for the task | add the at-logon trigger; set `RAK_CLAUDE_CMD` to an absolute path |

To re-run the same day, move today's digest away, or pass `--force`.

## 5. Reading a digest

When the user asks about today's papers:

- start with the "⚠ Directly relevant" section;
- then the per-line paragraphs;
- quote the coverage numbers from the top (fetched / after filtering / added).

Every paper the digest adds is `status: queued`: only the TL;DR and motivation are filled, from the abstract. Say so before relying on it.
