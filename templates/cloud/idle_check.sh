#!/usr/bin/env bash
# Idle guard, run every minute by a systemd timer on the VM (installed by startup.sh).
# Idle = GPU utilisation below IDLE_GPU_PCT AND the job's heartbeat older than IDLE_MINUTES, for IDLE_MINUTES
# consecutive checks. Then: final sync to GCS (with a timeout), then self-delete (VM + boot disk).
#
# Delete, not shutdown: a stopped VM stops compute billing but keeps billing its disk, and max-run counts from
# the last time it entered RUNNING, so nothing else will ever remove it.
# If self-delete fails (most often: the VM's service account lacks compute.instances.delete), it falls back to
# shutdown and logs a loud warning. That fallback looks like success from outside, which is why the external
# waiter - not this guard - is the primary cleanup, and why vm_job.sh tests the permission at start.
#
# Local test (prints what it would do; touches nothing):
#   DRY=1 IDLE_MINUTES=2 STATE=/tmp/c HEARTBEAT=/tmp/h OUT_DIR=/tmp/o ./idle_check.sh
set -uo pipefail

PCT=${IDLE_GPU_PCT:-5}
NEED=${IDLE_MINUTES:?IDLE_MINUTES is required}
STATE=${STATE:-/var/lib/rak/idle_count}
OUT_DIR=${OUT_DIR:-/root/rakout}
HEARTBEAT=${HEARTBEAT:-/var/lib/rak/heartbeat}
DRY=${DRY:-0}

# GPU utilisation; unreadable counts as 0 (a dead driver is itself a reason to stop paying)
util=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 || true)
util=${util:-0}; util=${util// /}
[[ "$util" =~ ^[0-9]+$ ]] || util=0

hb_age=999999
[[ -f "$HEARTBEAT" ]] && hb_age=$(( ( $(date +%s) - $(stat -c %Y "$HEARTBEAT") ) / 60 ))

count=0
[[ -f "$STATE" ]] && count=$(cat "$STATE" 2>/dev/null || echo 0)
[[ "$count" =~ ^[0-9]+$ ]] || count=0
# both conditions: GPU-only would kill a long pip install; heartbeat-only would miss a hung job that still beats
if (( util < PCT )) && (( hb_age >= NEED )); then count=$(( count + 1 )); else count=0; fi
mkdir -p "$(dirname "$STATE")" 2>/dev/null || true
echo "$count" > "$STATE"

say() { logger -t rak-idle "$*" 2>/dev/null || true; (( DRY )) && echo "$*"; return 0; }
say "gpu=${util}% heartbeat_age=${hb_age}min idle_count=${count}/${NEED}"

meta() {
  if (( DRY )); then echo "${DRY_META:-dry-value}"; return 0; fi
  curl -s -f -m 5 -H "Metadata-Flavor: Google" "http://metadata.google.internal/computeMetadata/v1/$1" 2>/dev/null
}
find_gcloud() {  # systemd's PATH is narrow
  for c in "${GCLOUD:-}" /usr/bin/gcloud /usr/local/bin/gcloud /snap/bin/gcloud /opt/google-cloud-sdk/bin/gcloud \
           "$(command -v gcloud 2>/dev/null)"; do
    [[ -n "$c" && -x "$c" ]] && { echo "$c"; return 0; }
  done
  return 1
}
final_sync() {
  local dest_file=${GCS_DEST_FILE:-/var/lib/rak/gcs_dest}
  [[ -s "$dest_file" ]] || { say "no GCS destination; outputs exist only on this disk"; return 1; }
  local dest g; dest=$(cat "$dest_file"); g=$(find_gcloud) || { say "gcloud not found"; return 1; }
  say "final sync $OUT_DIR -> $dest (timeout ${SYNC_TIMEOUT:-120}s)"
  (( DRY )) && [[ -z "${DRY_SYNC_RC:-}" ]] && return 0
  [[ -n "${DRY_SYNC_RC:-}" ]] && return "$DRY_SYNC_RC"
  timeout "${SYNC_TIMEOUT:-120}" "$g" storage rsync -r "$OUT_DIR" "$dest" >/dev/null 2>&1
}
self_delete() {
  local g name zone; g=$(find_gcloud) || { say "gcloud not found"; return 1; }
  name=$(meta instance/name) || return 1
  zone=$(meta instance/zone) || return 1
  zone=${zone##*/}
  [[ -n "$name" && -n "$zone" ]] || { say "metadata has no name/zone"; return 1; }
  say "self-delete $name ($zone), boot disk included"
  (( DRY )) && [[ -z "${DRY_DELETE_RC:-}" ]] && return 0
  [[ -n "${DRY_DELETE_RC:-}" ]] && return "$DRY_DELETE_RC"
  timeout 300 "$g" compute instances delete "$name" --zone="$zone" --quiet
}

if (( count >= NEED )); then
  say "idle for ${NEED} checks - finishing"
  if ! final_sync; then
    if [[ "${REQUIRE_SYNC:-0}" == 1 ]]; then say "final sync failed; REQUIRE_SYNC=1 -> not deleting, retry next minute (max-run is the backstop)"; exit 0; fi
    say "final sync failed; deleting anyway so the disk stops billing"
  fi
  if self_delete; then
    say "delete requested"
    (( DRY )) && echo "WOULD DELETE"
  else
    say "!!! SELF-DELETE FAILED - falling back to shutdown. The boot disk KEEPS BILLING until someone deletes the VM."
    say "!!! Usual cause: the VM's service account lacks compute.instances.delete (see install_sa.sh)."
    if (( DRY )); then echo "WOULD FALL BACK TO SHUTDOWN"; else /sbin/shutdown -h now "rak: idle (delete failed, disk still billing)"; fi
  fi
else
  (( DRY )) && echo "alive"
fi
exit 0
