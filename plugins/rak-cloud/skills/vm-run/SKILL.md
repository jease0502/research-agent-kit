---
name: vm-run
description: Run one experiment job on a GCP GPU VM with the spending decisions outside the agent - precheck (credentials, disk vs image, max-run with delete, worst-case budget, service account), create from a dry-run-printed command, a VM-side job whose steps succeed only by fresh outputs, and an external waiter that pulls and verifies against a manifest before deleting. Use whenever an experiment needs a cloud GPU.
license: Apache-2.0
compatibility: Needs the gcloud CLI, bash on the VM image, Python 3.9+ locally. Claude Code or any agent that can run shell commands.
metadata:
  plugin: rak-cloud
  version: "0.1.0"
---

# Run a job on a cloud VM

The agent may create a VM and must clean it up. Every spending decision lives in a file the agent does not
edit mid-run (`.rak/cloud.json`) and in checks that run before and outside it.

## Before the first run in a project

1. Copy `templates/cloud/cloud.json` to `.rak/cloud.json` and fill **every** key. There are no defaults.
   An unknown key raises, because a typo must not silently turn off a guard.
2. Have the project owner set up the runner service account (`cloud-setup` skill). Without it, idle VMs
   cannot delete themselves.

## Per job

1. **Write the job.**
   - `templates/cloud/vm_job.sh` is the engine; do not edit it.
   - Your experiment goes in a `steps.sh` defining `run_steps`, made of `step NAME TIMEOUT "OUTPUTS" -- command` lines.
   - Declare the outputs that prove each step worked. A step succeeds only if they exist, are non-empty and
     are newer than the step's start. The exit code alone never counts.
   - Upload `vm_job.sh` and `steps.sh` to `gs://<bucket>/<name>/job/`.
2. **Precheck:** `python <plugin>/scripts/rak_cloud.py precheck --job-hours <estimate>`. It refuses when:
   - the credentials have expired (the user has to log in; do not work around it);
   - the bucket is unreadable;
   - `disk_gb` is smaller than the image (otherwise the create fails in every zone);
   - spent-so-far plus max_run × price would cross the stop line;
   - the run is SPOT without `accept_spot_preemption`;
   - the service account is missing;
   - a script contains CR bytes or fails `bash -n`.
3. **Create:** `rak_cloud.py create <prefix-name> --job gs://.../job/`.
   - It is a dry run by default and prints the exact command.
   - Show that command to whoever approves spending, then re-run with `--yes`.
   - Every create carries `--max-run-duration`, `--instance-termination-action=DELETE` and `--boot-disk-auto-delete`; a command without them is refused in code.
   - Zones are tried in order, and the zone that worked is recorded.
4. **Wait:** `rak_cloud.py wait <name>`, under a monitor that notifies.
   - It prints one keyword per line: PROGRESS, STALL, VM_STATE_UNKNOWN, VM_GONE, BUDGET_REPORT, BUDGET_STOP,
     PULL_INCOMPLETE, PULLED_OK, DELETED, DELETE_CHECK_FAILED, DELETE_GAVE_UP, OUTPUTS_UNVERIFIED,
     REQUIRED_MISSING, TRACE_WRITE_FAILED, END. Exit codes: 0 done, 2 gone (outputs verified), 3 delete not
     confirmed after 3 tries, 4 gone before the outputs verified, 5 stop not confirmed (VM still running)
     (see the plugin README).
   - **Only an explicit "not found" counts as gone.** Expired credentials or a network error is UNKNOWN, never a reason to act.
   - At a terminal status (or a stopped VM): pull, check that nothing is left to copy, and check every file
     against `MANIFEST.sha256`. Only then delete, and confirm that both the VM and its disk are gone.
   - At the stop line it asks the job to stop, and waits for `STOPPED_SYNCED`. If that is not confirmed, the
     VM is **left running and reported**; max-run is the backstop. Unverified outputs are never deleted.
   - A VM that disappeared ends `gone` only if every file in its manifest verified and every declared output in
     `REQUIRED.txt` is among them (manifest alone if there is no usable `REQUIRED.txt`); otherwise
     `gone_unverified` with the full list of what is missing. Report that list; do not treat the run as complete.
   - Before a delete, declared outputs that were never produced are printed as REQUIRED_MISSING and kept in
     `.rak/cloud/instances.json`. Report them with the result; the VM is still deleted.
   - Where it stopped is in `.rak/cloud/trace/<name>.jsonl` (one line per tree node per poll).
5. **Report** the END line and the ledger (`cost-ledger` skill) before writing any result anywhere.

## What the VM does by itself

- `startup.sh` installs the idle guard and starts the job **once**; a reboot does not restart it.
- `vm_job.sh` runs a self-check first:
  - a GPU is visible;
  - the VM's own service account can delete this VM and write the bucket (testIamPermissions as itself).
  If either fails, nothing runs and the status says why.
- Before the first step it publishes `out/REQUIRED.txt`: every output the steps declare, read by calling `run_steps`
  with a `step` that only records. Keep `run_steps` to `step` calls (an external command there is refused), and
  declare explicit paths (a glob, an absolute path or `..` is refused). If the list cannot be verified in the bucket,
  nothing runs. A VM preempted mid-run has therefore already said which files it owed.
- Heartbeat, periodic sync, and a stop object it polls between and during steps.
- At the end: manifest, then sync, then verify the sync, then the status — in that order, so `DONE` never appears before its files do.
- The idle guard (`idle_check.sh`) deletes the VM after N idle minutes, but only after a successful final sync.
  If the delete fails, it falls back to shutdown with a loud log line. The waiter, not the guard, is the primary cleanup.

## Rules

- Do not raise `stop_at_usd`, `max_run` or the price to make a precheck pass; ask.
- Do not "retry until it works" across zones and machine types without telling anyone; stockouts get reported.
- Before you report a cost, check that the VM is gone. Read the state; do not infer it from the create log.
- See `docs/pitfalls.md` in this plugin for the failures each guard came from.
