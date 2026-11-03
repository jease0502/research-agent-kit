# Contributing

Thanks for helping. The kit's value is that its checks can be trusted. Contributions are held to the same standard
the kit asks of experiments: say what you changed, show it was checked, and keep the record honest.

## Before you start

- Read `docs/architecture.md` (what is enforced by what) and `docs/design-rationale.md` (why).
- For anything larger than a fix, open an issue first and describe the failure it addresses. If it is a new failure
  mode, add it to `docs/failure-modes.md` in the same pull request, using the format symptom / cause / guard.

## Layout and conventions

- **Skills.** One folder per skill with a `SKILL.md`, following the [Agent Skills](https://agentskills.io) format:
  - `name` equals the folder name; `description` says when to use the skill;
  - keep the body under 500 lines; put long material in `references/` and executables in `scripts/`.
- **Hooks are Claude Code specific.** Mark them as such in the plugin README. A hook must fail closed (block when it
  crashes) and must do nothing in projects that have not opted in.
- **Python:** standard library only in plugins (`python/rak` declares its own dependencies). 3.9+ for plugin
  scripts, 3.11+ for `python/rak`.
- **Shell scripts that run on VMs:** LF line endings (`.gitattributes` enforces it), `bash -n` clean, `set -uo pipefail`.
- **Configuration:** no defaults for values that differ between users (accounts, projects, buckets, prices, paths).
  Unknown keys raise.
- **Language:** English in code, docs and skills. Technical terms stay as they are.

## Tests

Each plugin keeps its tests in `plugins/<name>/tests`, and each example in `examples/<name>/tests`. CI runs all of them.

```bash
python -m pytest -q plugins/rak-discipline/tests
python -m pytest -q plugins/rak-cloud/tests          # VM-side tests need bash with coreutils (Linux, or Git Bash on Windows)
(cd examples/friction-dr-anymal && python -m pytest -q tests)
python -m pytest -q python/tests
# the policy engine: edit python/rak/policy/ only, then copy it into the plugins and commit both
python scripts/vendor_policy.py
```

Requirements for a new guard or check:
1. **A case it must refuse and a case it must allow.** A test that only covers the happy path does not count.
2. **Show the test can fail.** Remove or break the guard locally and confirm at least one test turns red. Say in the pull
   request which test caught it. (Our own suites were checked this way.)
3. **No live cloud resources in tests.** Use the fake gcloud in `plugins/rak-cloud/tests/fake_gcloud.py`, and extend it
   when you need a new call. Unknown calls exit 2 on purpose, so a new call cannot pass silently.
4. **Write files with LF on every platform** (`newline="\n"`). A test that passes only on one OS hides a bug.

## Private material

CI scans the working tree and history for private names, accounts, local paths, buckets and tokens
(`scripts/scan_private.py`). CI runs after the push, and history cannot be cleaned by a later commit, so
**install the pre-commit hook once per clone**:

```bash
git config core.hooksPath scripts/hooks      # a finding in the staged content blocks the commit
python scripts/scan_private.py --staged      # the same check by hand
```

- Only the staged content blocks, because it is what the commit contains. The hook scans the rest of the working
  tree too, but a finding there only warns ("N finding(s), not in this commit"). Several sessions may share one
  working tree, and another session's untracked or unstaged file must not stop your commit. CI still scans the
  whole tree and the history, so the warning is not the end of it: whoever owns those files has to fix them.
- The hook uses `$RAK_PYTHON`, then `python`, then `python3`. It needs no packages.
- Private names are checked only if a list is present (`RAK_DENY_FILE` or `~/.config/research-agent-kit/deny.txt`).
  Without one, the hook still runs the pattern rules and prints a warning.
- Do not bypass it with `--no-verify`. If it is wrong, fix the scanner and add a test.
- **Use reserved placeholders:** `example.com` / `.example` addresses, `fake-*` buckets, `<PLACEHOLDER>` values.
- **Do not add allow-list entries to make a finding pass.** Change the text instead.
- **If you committed a secret:** rotate it first, then tell a maintainer. Removing it from history does not undo the exposure.

CI needs two repository secrets, set by a maintainer (`gh secret set <NAME> < file`):

- `RAK_DENY_TERMS`: the private names, one term per line. Without it the scan fails on purpose.
- `RAK_ALLOW_IDENTITIES`: approved commit identities, one exact `Name <email>` per line
  (`Your Name <you@example.com>`). Without it every author and committer e-mail is a finding.

In a fork without these secrets, CI is red. Run the scan locally with your own lists instead.

## Pull requests

- One topic per pull request. Commit only the files you mean to change (`git add <paths>`, never `git add -A` in a shared tree).
- The description says:
  - what changed;
  - what was checked and how (commands and results);
  - what was not checked.
- If a change corrects an earlier claim in the docs, keep the original sentence and add the correction; do not rewrite history silently.
- Numbers in docs (costs, timings, test counts) come from a run you can point to, or are marked as estimates.

## Licensing

- Code: Apache-2.0 (`LICENSE`).
- Documentation, templates, `SKILL.md` and `README.md` files: CC BY 4.0 (`docs/LICENSE-docs.md`).

By contributing you agree that your contribution is licensed the same way.
