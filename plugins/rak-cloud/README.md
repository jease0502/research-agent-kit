# rak-cloud

Cloud GPU job lifecycle with spending kept outside the agent: pre-create checks, VM-side job state machine, an external waiter that only treats 'not found' as gone, verify-every-file-before-delete, idle self-delete, max-run, a cost ledger, and a local GPU lock.

**Status: 0.1, GCP only.** Tested against a fake gcloud and fake VM (below); not yet run against a live project.

**Requires Claude Code 2.1.295 or later.** Its guard hook sets `"onFailure": "block"`; on older versions a hook that times out or cannot start lets the call through. A SessionStart check warns when the version is older or cannot be read.

## Install

```
/plugin install rak-cloud --marketplace <owner>/<repo>
```

The repository location is not decided yet; replace `<owner>/<repo>` once it is published.

## Pieces

| Skill / file | What it does |
|---|---|
| `cloud-setup`, `scripts/install_sa.sh` | Runner service account limited to deleting `name_prefix*` VMs and the bucket. Dry run by default; `--verify` (static) and `--canary` (live permission test as the account) |
| `vm-run`, `scripts/rak_cloud.py precheck/create/wait/state/delete` | Precheck, guarded create (dry run prints the command), waiter that pulls + verifies against a manifest before deleting |
| `trees/lifecycle.json`, `scripts/bt.py` | The create and wait decisions as a behaviour tree, run by a small executor; each tick appends its trace (node path, status, reason) to `.rak/cloud/trace/<name>.jsonl`. The tree's hash is pinned in `rak_cloud.py`, and `hooks/tree_guard.py` blocks the agent from editing `trees/` ([docs/bt-pilot.md](../../docs/bt-pilot.md)) |
| `cost-ledger`, `rak_cloud.py ledger` | Spending from the audit log, insert → delete/preempt, conservative price |
| `templates/cloud/vm_job.sh` + `steps.sh` | VM-side state machine: self-check (GPU, delete and write permission as itself), steps judged by fresh outputs, heartbeat, sync with retries, stop request, manifest → sync → verify → status |
| `templates/cloud/startup.sh`, `idle_check.sh` | Start the job once per VM; idle guard (GPU low + stale heartbeat, N consecutive checks → final sync → self-delete, loud fallback) |
| `templates/cloud/cloud.json` | Configuration: every key required, no defaults, unknown keys raise |
| `docs/pitfalls.md` | Each known failure, its guard, and the test that proves the guard |
| `scripts/gpulock.py` | Local GPU mutual exclusion for parallel agents: `gpulock.py --lock PATH run OWNER [--wait S] -- cmd` (exit 75 if busy). Lock path required (`--lock` or `RAK_GPU_LOCK`); a stale lock (holder gone, or not renewed) is removed only under a separate breaker lock after re-checking it, so two waiters cannot both take it over; release only removes your own lock. On Windows, "access denied" while another process deletes or reads the lock counts as busy (retried until `--wait` runs out), not as an error |

## Tests

```
python -m pytest -q tests        # from this folder
```

- `test_cloud.py` drives `rak_cloud.py` through `tests/fake_gcloud.py`. The fake is backed by a folder, and has
  knobs for expired credentials, network failure, timeouts, zone stockouts, delete failures, leftover disks
  and incomplete syncs.
- `test_vm_side.py` runs the real `vm_job.sh` and `idle_check.sh` under bash, with the same fake gcloud and a fake
  `nvidia-smi`. It needs a bash with coreutils: Linux, or Git Bash on Windows; `RAK_TEST_BASH` selects one.
  It is skipped if none is found.
- `test_bt.py` covers the executor; `test_bt_lifecycle.py` sends each failure down its branch and checks the trace,
  compares the tree-driven create and waiter step by step with the pre-tree code (`tests/legacy_rak_cloud.py`, a
  frozen copy) on randomized scenarios, and checks the hash pin and the hook.
- Each guard was removed on purpose once, and the suite turned red each time (see `docs/pitfalls.md` for which test catches what).

## `wait` exit codes and keywords

| Exit | End | Meaning |
|---|---|---|
| 0 | `done` | outputs pulled and verified against the manifest, VM and disk deleted. Declared outputs (`REQUIRED.txt`) that were never produced do not stop the delete; they are printed as `REQUIRED_MISSING` and kept in `.rak/cloud/instances.json` (`required_missing`) |
| 1 | — | configuration or gcloud error (`rak-cloud: ...` on stderr) |
| 2 | `gone` | the VM disappeared (preempted, max-run, deleted elsewhere); every manifest entry verified locally, and every path in `REQUIRED.txt` (the declared outputs) is one of them. Without a usable `REQUIRED.txt` the manifest alone decides |
| 3 | `delete_unverified` | outputs verified, but 3 deletes in a row did not confirm the VM and disk gone; check by hand |
| 4 | `gone_unverified` | the VM disappeared before its outputs verified; `OUTPUTS_UNVERIFIED` lists every unverified file |
| 5 | `stop_unconfirmed` | budget stop sent, the job did not confirm within `stop_wait_min`; **VM left running and billing**. Was 2 until 2026-10-31 (breaking change) |

Exit 2 is also Python argparse's usage-error code, so a mistyped command looks like `gone` to a script that only reads
the code. Known, to be settled before release; read the `END` line. The `END` line of `gone` says what the check
rested on: `(REQUIRED.txt and manifest)` or `(manifest only; required list unknown)`.

Keywords, one per line, for a monitor to grep: `PROGRESS STALL VM_STATE_UNKNOWN VM_GONE BUDGET_REPORT BUDGET_STOP
STOP_SENT STOP_SEND_FAILED STOP_UNCONFIRMED PULL_INCOMPLETE PULLED_OK DELETED DELETE_CHECK_FAILED DELETE_GAVE_UP
OUTPUTS_UNVERIFIED REQUIRED_MISSING TRACE_WRITE_FAILED END`.

## Limits

- GCP only. The waiter, ledger and checks are written against gcloud's CLI; AWS / SkyPilot would be adapters.
- The IAM condition that limits deletion to `name_prefix*` VMs has not been verified on a live project. The canary
  in `cloud-setup` is the test for it.
- `price_per_vm_hour` is yours to set conservatively; the ledger is a guard, not an invoice.
- Nothing here can stop someone from creating VMs by hand outside these scripts. The ledger only counts `name_prefix*`.
- **GPU lock: remaining race window.** A lock counts as stale when its holder process is gone, **or when its
  timestamp is older than `stale_s` (default 3 h)**. If the holder is alive but its timestamp has aged past
  `stale_s`, and it releases at the same moment another waiter re-checks under the breaker, the waiter can
  remove the holder's successor's lock.

  Recommendations:
  - A holder must refresh the lock's timestamp regularly. `gpu()` already does this from a background thread
    every `renew_s` (default 10 min); keep `renew_s` well below `stale_s`.
  - Tools that hold the lock without `gpu()` (a shell script, a long job started some other way) must `touch` the lock
    file periodically.
  - A holder that can be suspended for hours (laptop sleep, a stopped process) can lose its lock to the age rule.
    For such jobs, raise `stale_s` or do not rely on age.
