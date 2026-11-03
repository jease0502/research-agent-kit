---
name: cost-ledger
description: Compute cloud spending for rak VMs from the GCP audit log (instance insert until delete or preemption, at a conservative per-VM-hour price) instead of from memory or the create log, and report it against the report and stop lines. Use before creating a VM, when reporting a run, and when someone asks what an experiment cost.
license: Apache-2.0
compatibility: Needs the gcloud CLI with permission to read the project's audit logs (roles/logging.viewer).
metadata:
  plugin: rak-cloud
  version: "0.1.0"
---

# Cost ledger

## Steps

1. `python <plugin>/scripts/rak_cloud.py ledger --since YYYY-MM-DDT00:00:00Z`
2. Report the figure in this form: `US$X.XX (conservative: P/VM-hour, insert -> delete/preempt, since D)`, plus the
   list of VMs still running (`state` for each).

## How it counts, and why

- **Source:** the audit log entries `instances.insert`, `instances.delete` and `compute.instances.preempted` for
  VMs whose name starts with `name_prefix`. VMs other people create are ignored.
- **Interval:** from the earliest insert entry to the earliest delete or preemption entry. If neither exists, the
  interval runs until now: the VM may still be running, or its delete may have failed. Check with `state`.
- **A stop does not end the interval.** A stopped VM still bills its disk; counting it as free is how stopped VMs
  get forgotten.
- **Price:** `price_per_vm_hour` from `.rak/cloud.json`, chosen conservatively (compute + disk + some margin).
  The ledger is a guard, not an invoice. Billing export gives the real figure later.
- `precheck` uses the same ledger: spent so far + `max_run` × price must stay under `stop_at_usd`.

## Rules

- Never report "about US$N" from memory. Run the ledger.
- A VM whose state is `UNKNOWN` is reported as unknown, not as gone and not as free.
- If the ledger and the billing export disagree by more than the price margin, say so; do not quietly adjust the price.
