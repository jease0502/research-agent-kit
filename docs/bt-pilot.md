# Behaviour-tree pilot: the rak-cloud job lifecycle

Status: pilot, done for `rak-cloud` only (2026-10-31; second round after cross-review of 534dfdd, see §7). The lifecycle decisions moved from Python control flow into a
declarative tree (`plugins/rak-cloud/trees/lifecycle.json`) run by a small executor (`plugins/rak-cloud/scripts/bt.py`).
Behaviour is meant to be unchanged; section 4 says how that was checked and how far it goes.

## 1. Before: the lifecycle as it was (rak_cloud.py at 47e424a)

```
create NAME [--yes]                                   wait NAME  (the CLI calls poll() every poll_s seconds)
  precheck ── any failure ──> CloudError, nothing     poll():
  for zone in cfg.zones (in order):                     st = status.txt from the bucket, vm = describe
    cmd = create_command(...)  ── bad name ──> raise    PROGRESS on change / STALL after stall_min
    guard_command(cmd) ── no max-run/DELETE ──> raise    vm UNKNOWN ──> VM_STATE_UNKNOWN, keep polling
    no --yes: print first zone's command, return None   budget: BUDGET_REPORT once; BUDGET_STOP once ->
    gcloud create ── ok ──> record, CREATED, return        write control/stop, STOP_SENT
                  └─ fail ──> CREATE_FAIL, next zone     vm GONE ──> (VM_GONE if not terminal) pull,
  all zones failed ──> CloudError                           verify, END ──> "gone"
                                                         terminal status or VM stopped ──> pull, verify
                                                           incomplete ──> PULL_INCOMPLETE, keep polling
                                                           ok ──> PULLED_OK, delete, check VM+disk gone
                                                             DELETED ──> END ──> "done"
                                                             DELETE_CHECK_FAILED ──> keep polling
                                                         stop sent and stop_wait_min passed ──>
                                                           STOP_UNCONFIRMED ──> "stop_unconfirmed"
                                                         else keep polling
```

### Failure handling, and what the brief listed

| Failure | Handling | Where |
|---|---|---|
| Expired credentials, network error, timeout on `describe` | `UNKNOWN`, never `GONE`; the waiter keeps polling and deletes nothing | `vm_state`, waiter |
| Stockout in a zone | next zone in `zones`, in order; one pass, no backoff | `create` |
| Every zone stocked out | error, nothing created | `create` |
| Preemption, max-run expiry, deletion elsewhere | `GONE` before a terminal status: `VM_GONE`, pull what is there, report verified or `INCOMPLETE`, end `gone`. *Second round: `gone` only if every manifest entry verified; otherwise `OUTPUTS_UNVERIFIED` with the full list, end `gone_unverified`, exit 4* | waiter |
| Pull incomplete, file missing, hash differs | VM kept; the next poll pulls again (the "retry" is the next poll, unbounded; max-run is the backstop) | waiter |
| Delete leaves the VM or the disk | `DELETE_CHECK_FAILED`, keep polling (the next poll pulls and deletes again). *Second round: at most `DELETE_ATTEMPTS` = 3, then `DELETE_GAVE_UP`, end `delete_unverified`, exit 3* | waiter |
| Budget | report line, then a stop file for the job, then `STOP_UNCONFIRMED` after `stop_wait_min` with the VM left running | waiter |
| max-run, idle | **not in the local lifecycle**: `--max-run-duration` with `DELETE` is in every create command (`guard_command` refuses one without it); idle self-delete runs on the VM (`templates/cloud/idle_check.sh`) | create command, VM |
| Spot -> STANDARD | **does not exist.** SPOT needs `accept_spot_preemption: true` at precheck; there is no fallback to STANDARD | precheck |

Spot -> STANDARD was in the brief but not in the code, so the pilot does not add it: it would change behaviour, and
it changes money. `price_per_vm_hour` is one number used by the precheck's worst case and by the waiter's budget
lines; a VM that falls back to STANDARD costs several times a SPOT price, and both checks would undercount it. Adding
it needs a second price (`price_per_vm_hour_standard`) and the owner's decision; in the tree it would be one more
Fallback child after `zones`.

Two behaviours found while mapping, kept as they were in the first round (equivalence first) and changed in the
second by the maintainer's decision (§7):
- after `DELETE_CHECK_FAILED` every poll pulled again and called delete again, with no limit;
- a `GONE` VM ended `gone` (exit 2) whether its outputs verified or not; the line said which.

## 2. Design

**Tree file** (`trees/lifecycle.json`, JSON so the executor stays standard library). Nodes: `Sequence`,
`Fallback`, `Condition`, `Action`, and the decorators `Retry` and `Timeout`. Statuses `SUCCESS`, `FAILURE`, `RUNNING`.
Numbers can be read from the blackboard (`"$n_zones"`). The format is in the `bt.py` docstring.

**Tick model.** Every tick starts at the root (reactive); `RUNNING` means "ask again next tick". One `wait` poll is
one tick; `create` is one tick. State that must outlive a tick is on the **blackboard**, not in nodes: VM name, zone,
creation time, bucket prefix, local folder, last status and VM state, budget flags, the time the stop was sent,
the list of verified files (`verified`, from the manifest), and the end reason.

**Retry** re-ticks its child on `FAILURE` within the same tick (create in the next zone). **Timeout** fails without
ticking its child once `seconds` have passed since `since`, a blackboard time. `since` is required during the pilot:
a Timeout that kept its own start time restarted after it fired and was never halted when its branch stopped being
ticked (cross-review), so the validator refuses one.

**Exceptions are not statuses.** A guard that raises (`guard_command`, the name prefix) is recorded in the trace as
`ERROR` and re-raised: it stops the whole create, as before, instead of being read as "this zone failed, try the next".
A trace that cannot be written prints `TRACE_WRITE_FAILED` and the run goes on; it never replaces the tick's own
exception.

**Trace.** Every tick writes one JSON line per node it visited (`tick`, `path`, `status`, `reason`) to
`.rak/cloud/trace/<name>.jsonl`. `bt.leaf_at()` on a tick's records returns the leaf the tree is waiting or stuck
in. A dry-run create writes no trace (as before, it leaves no files).

**What actually protects the tree.** No LLM is in the tree; it runs as code. The guarantee is narrower than the
first round claimed (cross-review):
- **The guarantee: a change to the tree has to appear in the diff together with a change to its pin.**
  `rak_cloud.py` pins each tree's canonical hash (`TREE_SHA256`; sorted-key JSON, so CRLF checkouts and formatting do
  not change it), and an edited tree stops `create` and `wait` with "not to be edited by the agent". Whoever can edit
  the tree can edit the pin and the hook too. What makes this hold is review and git: a commit that touches
  `trees/` without the pin fails the tests, and one that touches both is visible in review. A project can also list
  the plugin's `trees/` in a prereg's `frozen_trees`.
- **The hook is a speed bump, not a wall.** `hooks/tree_guard.py` blocks file tools under `trees/` and Bash segments
  that name a tree file. A reviewer got past it with: a glob for the file name, a name split by quotes, `git checkout` on the
  whole `trees` folder, `rm -r` on the folder, and `xargs sed`. No more hook rules will be added for these: matching
  command text can always be got around. The policy engine ([policy-engine.md](policy-engine.md)) is where this
  gets handled once for every hook.

## 3. After: the trees

```
create (Sequence)                        wait (Sequence)                        one tick = one poll
├─ precheck                              ├─ observe                  PROGRESS / STALL
└─ zones (Retry × $n_zones)              ├─ vm_known (Fallback)
   └─ create_in_next_zone                │  ├─ vm_state_known?
                                         │  └─ report_unknown        RUNNING: never GONE on a failed query
                                         ├─ budget                   BUDGET_REPORT / BUDGET_STOP + stop file
                                         └─ outcome (Fallback)
                                            ├─ vm_gone (Sequence)
                                            │  ├─ vm_is_gone?
                                            │  ├─ salvage_outputs    VM_GONE, pull, verify
                                            │  └─ gone_outcome (Fallback)
                                            │     ├─ verified (Sequence)
                                            │     │  ├─ outputs_verified?
                                            │     │  └─ report_gone  END -> "gone" (exit 2)
                                            │     └─ report_gone_unverified
                                            │                        OUTPUTS_UNVERIFIED, END -> "gone_unverified" (4)
                                            ├─ finished (Sequence)
                                            │  ├─ job_ended_or_vm_stopped?
                                            │  ├─ pull_and_verify    RUNNING while incomplete (retry next tick)
                                            │  └─ delete_or_give_up (Fallback)
                                            │     ├─ deleted (Sequence)
                                            │     │  ├─ delete_vm    RUNNING if VM or disk still listed;
                                            │     │  │               FAILURE at the 3rd unconfirmed delete
                                            │     │  └─ report_done  END -> "done" (exit 0)
                                            │     └─ give_up_delete  DELETE_GAVE_UP, END -> "delete_unverified" (3)
                                            ├─ stop_requested (Sequence)
                                            │  ├─ stop_sent?
                                            │  └─ stop_or_give_up (Fallback)
                                            │     ├─ stop_wait (Timeout $stop_wait_s since $stop_sent_at)
                                            │     │  └─ await_stop   RUNNING
                                            │     └─ give_up_stop    STOP_UNCONFIRMED -> "stop_unconfirmed"
                                            └─ keep_waiting          RUNNING
```

## 4. Equivalence: how it was checked

- **The 62 existing rak-cloud tests pass unchanged** (no test file edited).
- **Differential test** (`tests/test_bt_lifecycle.py::Differential`): the pre-tree `rak_cloud.py` is kept as a frozen
  copy (`tests/legacy_rak_cloud.py`). 300 random waiter scenarios (status, outputs good / tampered / missing, VM
  running / stopped / gone, expired credentials, network failure, rsync dropping a file, disk left, delete failing,
  clock steps that include the 25- and 30-minute edges, 30% starting past the stop line) and 60 random create
  scenarios run on both, and every step must give the same printed lines (timestamps removed), return value or
  exception, gcloud calls in order, and `instances.json`. All three endings occur.
- **The differential test catches changes.** Three mutants, each caught: UNKNOWN treated as known (the waiter
  goes on to budget and outcome), an incomplete pull returning FAILURE instead of RUNNING (the waiter falls through
  to the stop branch and can give up early), and the Timeout's `>=` turned into `>` (caught only after the 25-minute
  edge and the late-start scenarios were added; before that, only the branch tests caught it).
- **Branch tests**: stockout in one zone and in all zones, failed precheck, guard exception, preemption, a missing
  file, expired credentials with the VM really gone (still `report_unknown`, no delete call), budget stop timing out,
  delete check failing; each asserts the node path from the trace.

What this does not show: behaviour against real gcloud output that the fake does not produce, and the wall-clock
difference inside one poll (the old code read the clock several times per poll; so does the new, in the same places).

## 5. Trace example

Outputs pulled with one file missing, then the credentials expire:

```
{"tick": 1, "path": "wait/observe", "status": "SUCCESS", "reason": "vm=RUNNING status=DONE"}
{"tick": 1, "path": "wait/vm_known/vm_state_known", "status": "SUCCESS"}
{"tick": 1, "path": "wait/vm_known", "status": "SUCCESS", "reason": "at vm_state_known"}
{"tick": 1, "path": "wait/budget", "status": "SUCCESS", "reason": "US$0.00"}
{"tick": 1, "path": "wait/outcome/vm_gone/vm_is_gone", "status": "FAILURE"}
{"tick": 1, "path": "wait/outcome/vm_gone", "status": "FAILURE", "reason": "at vm_is_gone"}
{"tick": 1, "path": "wait/outcome/finished/job_ended_or_vm_stopped", "status": "SUCCESS"}
{"tick": 1, "path": "wait/outcome/finished/pull_and_verify", "status": "RUNNING", "reason": "objects in the bucket still differ from the local copy; missing model.pt"}
{"tick": 1, "path": "wait/outcome/finished", "status": "RUNNING", "reason": "at pull_and_verify"}
{"tick": 1, "path": "wait/outcome", "status": "RUNNING", "reason": "at finished"}
{"tick": 1, "path": "wait", "status": "RUNNING", "reason": "at outcome"}
{"tick": 2, "path": "wait/observe", "status": "SUCCESS", "reason": "vm=UNKNOWN status=none"}
{"tick": 2, "path": "wait/vm_known/vm_state_known", "status": "FAILURE"}
{"tick": 2, "path": "wait/vm_known/report_unknown", "status": "RUNNING", "reason": "vm state UNKNOWN: query failed, not treated as gone"}
{"tick": 2, "path": "wait/vm_known", "status": "RUNNING", "reason": "at report_unknown"}
{"tick": 2, "path": "wait", "status": "RUNNING", "reason": "at vm_known"}
```

Create with the first zone stocked out (the `t` field is the wall clock):

```
{"t": ..., "tick": 1, "path": "create/precheck", "status": "SUCCESS"}
{"t": ..., "tick": 1, "path": "create/zones/create_in_next_zone", "status": "FAILURE", "reason": "z-a: ERROR: The zone 'z-a' does not have enough resources (ZONE_RESOURCE_POOL_EXHAUSTED)"}
{"t": ..., "tick": 1, "path": "create/zones/create_in_next_zone", "status": "SUCCESS", "reason": "z-b"}
{"t": ..., "tick": 1, "path": "create/zones", "status": "SUCCESS", "reason": "attempt 2 of 2"}
{"t": ..., "tick": 1, "path": "create", "status": "SUCCESS", "reason": "all children"}
```

The trace grows by about 1 KB per poll (about 0.5 MB for an 8-hour job at one poll a minute); nothing rotates it.

## 6. Code size (first round)

`rak_cloud.py` +159 / −63 lines (the waiter's leaves are split out of `poll()`); new: `bt.py` 177, the tree 40,
the hook 87 + 16; tests: `test_bt.py` 161, `test_bt_lifecycle.py` about 370, plus the 496-line frozen reference copy.

## 7. Second round (cross-review of 534dfdd, the maintainer's decisions)

| Item | Change | Test (red before the change) |
|---|---|---|
| A1 | A trace write that fails prints `TRACE_WRITE_FAILED` and the waiter and create go on; the tick's own exception is never replaced | `test_bt_round2.py`: trace path made unwritable; with a failing tick, the original `JSONDecodeError` comes out |
| A2 | The verified list uses the manifest parser of `verify_pull` (`manifest_line`), binary ` *` and `./` included | manifest with ` *./model.pt` and a name with a space |
| A3 | `create` with no zones says "every zone failed", as before (it said "None") | direct call with `zones=[]`; the create differential includes it |
| B1–B4 | Differential: exceptions compared by type and message; gcloud missing, a corrupt `instances.json`, a file where the pull folder should be; VM states STOPPED, SUSPENDED, STOPPING, PROVISIONING, STAGING, REPAIRING; manifests in binary mode, with several files, partly missing, empty, with an unreadable line, and a job cut off with outputs but no manifest; counters assert that the stop-wait, stall, report and stop edges are each landed on exactly at least once | 400 waiter scenarios, every ending reached |
| C | §2 rewritten: the guarantee is "tree and pin change together in the diff"; the hook is a speed bump; the reviewer's bypasses listed | — |
| D | Timeout without `since` refused by the validator | `test_validator_refuses_timeout_without_since` |
| 2a / E | At most 3 unconfirmed deletes, then `DELETE_GAVE_UP`, `delete_unverified`, exit 3 | `test_delete_gives_up_after_three_unconfirmed_attempts`, `test_cli_exit_3_for_delete_unverified` |
| 2b | `gone` only when every manifest entry verified; otherwise `gone_unverified`, exit 4, `OUTPUTS_UNVERIFIED` lists every unverified file (no manifest: "MANIFEST.sha256 missing (required list unknown)") | `test_gone_*`, `test_cli_exit_4_for_gone_unverified` |

**Deliberate non-equivalence.** 2a and 2b change behaviour on purpose. The differential test checks those two cases
against the old behaviour instead of skipping them: where the new waiter ends `delete_unverified`, the old one
returned None with the same lines except `DELETE_GAVE_UP` and `END`, after exactly 3 `DELETE_CHECK_FAILED`; where
the new one ends `gone_unverified`, the old one ended `gone` with `INCOMPLETE` and the same lines except
`OUTPUTS_UNVERIFIED`. Everything else must still match step by step. One of the 62 original tests,
`test_cloud.py::test_preempted_before_terminal`, asserted the old 2b behaviour. With the maintainer's approval its
expectation is now `gone_unverified`, with the reason next to it and added assertions on exit 4 and the unverified
list. The other 61 are unchanged.

**REQUIRED.txt.** 5f61a54 makes the VM publish `REQUIRED.txt` (the declared outputs) before the first step.
When a VM is gone, the waiter now judges by that list, with the manifest supplying the hashes (`tests/test_required.py`):
`gone` only if every manifest entry verifies and every required path is one of them; otherwise every unverified path
is listed (with no manifest: each required path as missing or "here but no hash to check"). A missing file, a header
other than `# rak-required v1`, or an absolute or `..` path makes the list unknown, and the manifest-only rule above
applies; the differential scenarios have no `REQUIRED.txt`, so they check that fallback against the old code.
The delete path is unchanged: a job that ended is deleted once everything it wrote is verified, even if declared
outputs are missing, because a failed job (`FAIL_<STEP>_NO_OUTPUT`) is missing them by design.

**Third round (maintainer's decisions and cross-review of 8e0c5ee).**
- `stop_unconfirmed` exits 5 instead of 2, a **breaking change**: 2 also meant `gone`, and the two mean opposite
  things to a monitor (a VM gone with its outputs verified, against a VM still running and billing).
- The delete path records declared outputs that were never produced (`REQUIRED_MISSING`, the trace,
  `instances.json` → `required_missing`) without stopping the delete.
- A declared directory is met by at least one manifest entry under it (vm_job accepts a non-empty directory as an
  output; the manifest lists files). A `REQUIRED.txt` with an absolute or `..` path is invalid (vm_job never writes
  one), so it ends `gone_unverified` rather than falling back. The `END` line of `gone` names what the check rested
  on; the differential test removes that suffix before comparing, a deliberate difference.
