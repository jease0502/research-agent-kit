# Security

What the kit touches, what it stores, how it can be bypassed, and what we have not verified.
Report vulnerabilities privately to the maintainers (see the repository's security policy once published);
do not open a public issue for them.

## Credentials

| Credential | Where it lives | Notes |
|---|---|---|
| Cloud (gcloud) | gcloud's own credential store; the kit never reads or writes it | Every gcloud call has the account and project pinned through `CLOUDSDK_CORE_ACCOUNT` / `CLOUDSDK_CORE_PROJECT` in the child environment. A background job does not follow whichever account was used last |
| VM identity | The runner service account attached to each VM | Tokens come from the metadata server on the VM; nothing is copied to the VM |
| Telegram bot token (fallback bridge in `rak-team`) | `~/.config/claude-tg/tg.env` (or `$TG_HOME`), outside any repository | Plain file in your home directory. Restrict its permissions. Prefer the official Channels plugin, which stores its token in its own configuration |
| Literature APIs (optional keys) | Environment variables | Never in files under version control |
| Plugin options | Not used yet | Claude Code's `userConfig` with `sensitive: true` (OS credential store) is the intended route for any future secret option |

Rules:
- No token ever goes into a repository, a command line that is logged, or a file under version control.
- Job outputs are synced to a bucket. Do not write secrets into a job's output directory: everything there is uploaded and listed in the manifest.

## Hooks: known limits

`rak-discipline` installs a PreToolUse hook (`hooks/guard.py`). It is a second line of defence, not a sandbox.

- **It matches command text.** It cannot see what a script does after it starts:
  - a launch through a wrapper, a renamed script or `python -c` is not recognised as an experiment;
  - a file rewritten from inside a program is not seen as an edit.
- **Claude Code documents hook filtering as best effort.** Hard rules belong in the permission system.
- **It fails closed.** A crash or a configuration with unknown keys blocks the call instead of letting it through.
  *Correction (2026-10-31): that was true only of errors inside the hook. Claude Code lets the call through when a PreToolUse hook times out, exits with a code other than 0 or 2, or cannot start (missing interpreter, wrong path), unless the hook sets `"onFailure": "block"` (Claude Code 2.1.295 or later; harness-landscape §0). Every plugin hook now sets it, and a test checks that. Checked with the real CLI (2.1.316, haiku): without it an exit-1 hook let the call through; with it, exit 1, a timeout and a missing interpreter were all blocked.*
- **Git hooks can be skipped** with `--no-verify`. The append-only check must also run in CI to be a guarantee.
- **The rak-discipline hook only acts in projects that opted in** (`.rak/discipline.json`). Elsewhere it does nothing.
- **The rak-team hook** (`git_guard.py`) blocks whole-tree staging and committing in every repository unless `.rak/team.json`
  opts out. It reads command text too, so a script or alias that runs git is not seen.

Review hooks from any plugin before installing it. A hook runs with your user's permissions on every matching tool call.

## Cloud permissions: least privilege

- **Runner service account** (`install_sa.sh`):
  - a custom role with only `compute.instances.get`, `compute.instances.delete` and `compute.zoneOperations.get`, bound with an IAM condition on the instance-name prefix;
  - `roles/storage.objectAdmin` on the one bucket;
  - the person creating VMs gets `roles/iam.serviceAccountUser` on this account only.
- **The install script is a dry run by default.** IAM changes are the project owner's decision.
- **Not verified yet:** the IAM condition on the instance name has not been tested on a live project. If GCP rejects
  or ignores it, the account can delete any VM in the project. The `--canary` run and the job's self-check show whether
  deletion works; they do not show that the condition *restricts* it. Until that is verified, use a project that holds
  only these jobs.
- **VM scopes:** VMs run with the `cloud-platform` scope. What the VM can actually do is limited by the service account's
  IAM roles, not by the scope. A VM running untrusted code can do anything those roles allow.
- **Spending guards run outside the agent.** max-run with DELETE, the waiter and the ledger are not instructions to the model.
  The ledger's price is a configured estimate. Set a budget alert in the billing console as well; an alert does not
  stop spending by itself.

## Running untrusted code

- Experiment code runs on the VM as root, unless a step drops privileges; `steps.sh` documents how.
- The VM is the isolation boundary. Do not attach a service account with broader roles to save a step.
- Locally, nothing is sandboxed. Treat repositories you clone for an experiment as untrusted data:
  - read them before running anything from them;
  - run interpreters in isolated mode (`python -I`).

## Private-name scanning: limits

`scripts/scan_private.py` runs in CI over the working tree and the full history.

- **Pattern rules** catch email addresses, local home paths, GCS buckets, auto-generated project IDs and common token
  formats. Reserved placeholder forms (`example.com`, `.example`, `fake-*` buckets) are accepted. Real values that look
  like placeholders are not caught.
- **The private-name list lives outside the repository** (a CI secret, or a local file named by `RAK_DENY_FILE`). It is
  only as complete as the people who maintain it, and it matches words, not meaning:
  - a private project described without its name passes;
  - so does a number that identifies it.
- **A missing list is a failure, not a pass.** CI fails if the list is absent. Pull requests from forks get no secrets and fail
  that job; a maintainer re-runs them from a branch.
- **Rewriting history** removes a leak from this repository, not from clones made before the rewrite. Rotate anything that was exposed.

## Notifications and remote control

- **Approvals over chat.** With the official Channels plugin, **anyone on the allowlist who can reply can approve tool
  use**, if permission relay is on. Allowlist only people you would trust at your keyboard.
- **Group chats.** In a group with other people or other agents, their messages are not the user's instructions or approvals.
  `rak-team` says so; Claude Code also does not let a peer session approve a permission prompt. A forwarded message can
  still carry instructions, so treat it as data.
- **Bot ownership.** The fallback Telegram bridge pairs with a one-time code:
  - `setup` (or `pair`) prints an 8-character code in your terminal, valid for 15 minutes and for one use.
  - Only a private message that carries the code, before it expires, records its sender as the user.
  - Everyone else is ignored and nothing is recorded for them, including someone who finds the bot first. A code posted in a group does not pair.
  - Only the code's hash is stored, and it is deleted when used.

  Confirm with `tg.py check`; if the wrong account was paired, `tg.py pair` issues a new code and forgets the old user
  and group. The code protects pairing, not the token: anyone who has the bot token can read the bot's updates, so
  keep it private and use one bot per project.

## Supply chain

- Plugins are installed from a marketplace that pins sources. Review a plugin's hooks, scripts and MCP servers before installing.
- The VM steps install pinned versions. Re-read the installed source before registering a mechanism that depends on it
  (a different version can have different defaults; see `docs/failure-modes.md` C7).
