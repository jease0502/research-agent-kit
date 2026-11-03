---
name: cloud-setup
description: Prepare a GCP project for rak-cloud - a dedicated runner service account that may only delete VMs with the configured name prefix and read/write the configured bucket, printed as a dry run for the project owner, then verified statically and by a tiny canary VM that tests the permissions as the account itself. Use once per project, and whenever idle VMs are found stopped instead of deleted.
license: Apache-2.0
compatibility: Needs the gcloud CLI and an account that can change IAM (the project owner). Applying is the owner's decision.
metadata:
  plugin: rak-cloud
  version: "0.1.0"
---

# Cloud setup: the runner service account

Why this exists: a VM created with the project's default compute service account often has **no compute
permissions**. Its idle guard then cannot delete it. It falls back to shutdown, the disk keeps billing, and
from outside a stopped VM looks handled. The audit log shows the failed call as
`Required 'compute.instances.delete' permission`.

## Steps

1. Fill `.rak/cloud.json` (`vm-run` skill), including `service_account` as `<name>@<project>.iam.gserviceaccount.com`
   and `name_prefix` (e.g. `rak-`).
2. **Dry run:** `bash <plugin>/scripts/install_sa.sh .rak/cloud.json` prints every command:
   - create the service account;
   - create a custom role `rakSelfDelete` (`compute.instances.get`, `compute.instances.delete`, `compute.zoneOperations.get`);
   - bind it at project level **with an IAM condition on the instance name prefix**;
   - grant `roles/storage.objectAdmin` on the bucket only;
   - let the user attach the account to VMs (`roles/iam.serviceAccountUser` on that account).
3. **Hand the printed commands to the project owner.** IAM changes are theirs to make. With their approval
   they run `--apply` (or paste the commands).
4. **Static check:** `install_sa.sh .rak/cloud.json --verify` (read-only). It checks that the account exists and the
   project and bucket bindings are present.
5. **Dynamic check:** `install_sa.sh .rak/cloud.json --canary` prints the command for an e2-micro VM
   (max-run 15 min, deletes itself). The VM runs, as the service account, the same permission test that
   `vm_job.sh` runs at start, and writes `DELETE_OK` / `WRITE_OK` to the bucket.
   - With `--canary --apply` the script creates the VM, waits for that file, and checks that the canary
     deleted itself. A canary that did not delete itself is the failure this whole setup is about, and the
     script prints the delete command for it.

## Limits

- The IAM condition on the instance name (`resource.name.extract('instances/{name}').startsWith(prefix)`) has not
  been verified on a live project yet. The canary is how you find out; if the condition is rejected, drop it
  and accept project-wide delete for this account, or use separate projects.
- The static check reads policies; it cannot prove that they apply. Only the canary (or the job's own self-check)
  proves that.
- Every job's `vm_job.sh` repeats the permission test, so a later policy change shows up as
  `FAIL_SELFCHECK_DELETE_PERMISSION` before any money is spent on the job.
