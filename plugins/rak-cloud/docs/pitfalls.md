# Cloud pitfalls and the guard (and test) for each

Every row happened in real agent-run jobs. The test named in the last column fails if the guard is removed;
this was checked by removing each guard on purpose (see README).

| Pitfall | What it looked like | Guard | Test |
|---|---|---|---|
| No terminal on the VM | Setup script died in 0 s with "'unknown': I need something more specific." (`set -e` + `tabs` with `TERM=unknown`) | `vm_job.sh` exports `TERM=xterm` globally and per step | `test_vm_side::test_done_with_manifest_and_term` |
| App framework swallows exceptions, exits 0 | "Successful" job, no outputs | Steps succeed only by declared outputs that exist, are non-empty and newer than the step start | `test_exit_zero_without_output_fails`, `test_stale_output_does_not_count` |
| Disk smaller than the image | Create failed in every zone; the dry run had passed | `precheck` reads `diskSizeGb` from the image and compares | `test_cloud::Precheck::test_disk_smaller_than_image` |
| Spot preempted right after boot | VM gone 6 minutes after creation, setup lost | `precheck` refuses SPOT without explicit acceptance; the waiter reports `VM_GONE` before terminal and pulls what exists | `test_spot_needs_explicit_acceptance`, `test_preempted_before_terminal` |
| CRLF line endings | Job script fails on the VM with `\r` errors; reported hashes do not match | `check_scripts` refuses CR bytes and `bash -n` failures in everything sent to a VM; manifests accept either `sha256sum` output mode | `test_crlf_script_refused`, `test_done_with_manifest_and_term` (manifest round trip) |
| "Could not ask" read as "gone" | Expired credentials made a watcher declare a VM gone; a guard then deleted the only copy of a log | `vm_state` returns GONE only on not-found; everything else is UNKNOWN and the waiter does nothing | `VmState::*`, `WaiterTests::test_unknown_state_is_not_gone` |
| Self-delete without permission | Idle VMs "self-deleted" but stayed stopped with billed disks | Dedicated service account (`install_sa.sh`); the job's self-check tests delete permission as itself; the waiter cleans up stopped VMs | `test_selfcheck_blocks_everything`, `test_guard_fallback_shutdown_is_cleaned_up`, `test_delete_failure_falls_back_loudly` |
| Deleting before the outputs are safe | A VM deleted while files were still syncing | Delete only after a pull with nothing left to copy and every file matching `MANIFEST.sha256` | `test_incomplete_pull_keeps_vm`, `test_hash_mismatch_keeps_vm`, `test_missing_manifest_keeps_vm` |
| `DONE` written before its files | The status said done while outputs were still uploading | Manifest, sync, verify sync, **then** status; unverifiable sync becomes `FAIL_SYNC` | `test_unverifiable_sync_is_fail_sync` |
| Budget line crossed with a blind delete | Stopping at the line would have thrown away partial checkpoints | Stop request → job syncs → `STOPPED_SYNCED` → pull, verify, delete; unconfirmed → left running and reported | `test_budget_report_then_stop_then_unconfirmed`, `test_stop_confirmed_is_pulled_and_deleted`, `test_stop_request` |
| Run without a time limit | A forgotten VM | Every create command must carry max-run + DELETE + disk auto-delete, enforced in code | `test_guard_refuses_unguarded_commands` |
| Default account / project | A background script followed the account the user last logged in with and got 403s | No defaults; account and project pinned into every gcloud call's environment | `test_every_key_required`, `test_account_and_project_pinned` |
| Typo in config silently disables a guard | `max_runn` would be ignored | Unknown keys raise | `test_unknown_key_raises` |
| Guard with a syntax error | VM runs with no guard and no error anywhere | Guard shipped as its own file, `bash -n` before install and in precheck | `test_crlf_script_refused` (covers `bash -n`) |
| Idle detection kills a long install | GPU idle during a 30-minute pip install | Idle = GPU low **and** heartbeat stale, for N consecutive checks; any activity resets the count | `test_busy_gpu_or_fresh_heartbeat_resets`, `test_needs_consecutive_checks` |
| Final sync fails, delete loses outputs | - | `REQUIRE_SYNC=1`: no delete until the final sync succeeds; max-run remains the backstop | `test_failed_final_sync_blocks_delete` |

Not covered by an automated test (checklist only):
- **Missing graphics library for Vulkan** (`libegl1`): the GPU is "not found" when the real problem is the ICD. Put
  the dependency in the image and run one rendering call in the first step.
- **The image boots without the NVIDIA kernel module.** Reboot the image builder and run `nvidia-smi` before you
  snapshot. The job's self-check stops the run if the GPU is missing.
- **Isaac Sim refuses to run as root.** Run those steps as a normal user (`sudo -u <user> -H`), as the example `steps.sh` notes.
