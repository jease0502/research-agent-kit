#!/usr/bin/env bash
# VM-side job engine. Started once by startup.sh as root:  RAK_OUT_URL=gs://.../out RAK_STEPS=/root/steps.sh vm_job.sh
# The experiment itself lives in steps.sh (a function run_steps calling `step`); this file is the state machine.
#
# status.txt (synced to $RAK_OUT_URL): RUNNING_<STEP> | DONE | FAIL_<REASON> | STOPPED_SYNCED
#   FAIL_SELFCHECK_*   the VM cannot do what the guards assume (GPU, delete itself, write the bucket)
#   FAIL_<STEP>_NO_OUTPUT  the step's declared outputs are missing, empty, or older than the step (whatever its exit code:
#                          simulators and app frameworks can swallow exceptions and exit 0)
#   FAIL_<STEP>_RC     outputs exist but the command failed
#   FAIL_<STEP>_TIMEOUT
#   FAIL_SYNC          outputs could not be verified in the bucket (also: REQUIRED.txt could not be published)
#   FAIL_REQUIRED_DECLARE  run_steps runs a command outside `step` (it would run during the declaration pass)
#   FAIL_REQUIRED_GLOB / FAIL_REQUIRED_PATH  a declared output is a glob, absolute, or contains ".."
# Before the first step: REQUIRED.txt ("# rak-required v1", then every declared output, sorted, one per line) is
# written to $OUT and synced, so a VM preempted mid-run has already said what it owed. It is not an output: it is
# kept out of the manifest, and a step that changes it is undone (from a copy in $RAKSTATE) before every sync.
# At any terminal state: MANIFEST.sha256 of every output, sync, verify the sync (dry run shows nothing to copy), then the
# final status. The waiter deletes the VM only after its own pull matches the manifest.
# Stop request: the object <prefix>/control/stop. The running step is killed, outputs synced, STOPPED_SYNCED.
set -uo pipefail
: "${RAK_OUT_URL:?}" "${RAK_STEPS:?}"
OUT=${OUT:-/root/rakout}
RAKSTATE=${RAKSTATE:-/var/lib/rak}
CONTROL=${RAK_OUT_URL%/out}/control/stop
STOP_POLL=${STOP_POLL:-30}
SYNC_TRIES=${SYNC_TRIES:-3}
mkdir -p "$OUT/logs"
export TERM=xterm      # no terminal under systemd: TERM=unknown makes `tabs`/`tput` fail, and `set -e` setup scripts die in 0 s
LOG="$OUT/driver.log"
REQ_KEEP="$RAKSTATE/REQUIRED.txt"   # the copy steps cannot reach; $OUT/REQUIRED.txt is restored from it
mkdir -p "$RAKSTATE"; rm -f "$REQ_KEEP"
say() { echo "[$(date -u +%FT%TZ)] $*" | tee -a "$LOG"; }
restore_required() {
  [ -f "$REQ_KEEP" ] || return 0
  if [ "$(cat "$REQ_KEEP")" != "$(cat "$OUT/REQUIRED.txt" 2>/dev/null)" ]; then
    say "REQUIRED.txt was changed or removed by a step; restored"; cp "$REQ_KEEP" "$OUT/REQUIRED.txt"
  fi
}

sync_out() {  # sync with retries; returns 0 only if a dry run afterwards shows nothing left to copy
  local i left
  for ((i = 1; i <= SYNC_TRIES; i++)); do
    timeout 300 gcloud storage rsync -r "$OUT" "$RAK_OUT_URL" >/dev/null 2>&1
    left=$(timeout 300 gcloud storage rsync -r --dry-run "$OUT" "$RAK_OUT_URL" 2>&1 | grep -c "Would copy")
    [ "$left" = 0 ] && return 0
    say "sync attempt $i left $left objects differing; retrying"
    sleep $((i * ${SYNC_BACKOFF:-10}))
  done
  return 1
}
set_status() { echo "$1" > "$OUT/status.txt"; say "STATUS $1"; timeout 120 gcloud storage cp "$OUT/status.txt" "$RAK_OUT_URL/status.txt" >/dev/null 2>&1 || say "status upload failed"; }

BG=()
start_background() {
  # stdout/stderr to /dev/null: a leftover `sleep` of a killed loop must not hold the caller's pipe open
  ( while kill -0 $$ 2>/dev/null; do touch "$RAKSTATE/heartbeat" 2>/dev/null; sleep "${HB_EVERY:-30}"; done ) >/dev/null 2>&1 & BG+=($!)
  ( while kill -0 $$ 2>/dev/null; do sleep "${SYNC_EVERY:-300}"; restore_required; timeout 300 gcloud storage rsync -r "$OUT" "$RAK_OUT_URL"; done ) >/dev/null 2>&1 & BG+=($!)
}

finish() {  # final status: manifest, sync, verify, then the status (last, so DONE never precedes its files)
  local final=$1
  for p in "${BG[@]}"; do kill "$p" 2>/dev/null; done
  wait 2>/dev/null
  say "finishing with $final"
  restore_required
  ( cd "$OUT" && find . -type f ! -name MANIFEST.sha256 ! -name status.txt ! -path ./REQUIRED.txt | sort | xargs -r sha256sum ) > "$OUT/MANIFEST.sha256"
  if sync_out; then set_status "$final"; exit_code=0; else set_status FAIL_SYNC; exit_code=1; fi
  [ "$final" = DONE ] || [ "$final" = STOPPED_SYNCED ] || exit_code=1
  exit $exit_code
}

stop_requested() { timeout 60 gcloud storage ls "$CONTROL" >/dev/null 2>&1; }

# step NAME TIMEOUT_S "OUTPUT1 OUTPUT2 ..." -- command ...
# Outputs are paths relative to $OUT. Success = every output exists, is non-empty, and is newer than the step start.
step() {
  local name=$1 tmo=$2 outs=$3; shift 4
  local marker="$OUT/logs/.start_$name" pid rc f bad=()
  set_status "RUNNING_$name"
  touch "$marker"; sleep 1   # mtime resolution: outputs written in the same second must still count as newer
  # exec: $pid is `timeout` itself, which on TERM signals the step's whole process group. (bash usually
  # execs the last command of a subshell anyway; this does not rely on that.)
  ( cd "$OUT" && TERM=xterm exec timeout "$tmo" bash -c "$*" ) > "$OUT/logs/$name.log" 2>&1 &
  pid=$!
  while kill -0 "$pid" 2>/dev/null; do
    if stop_requested; then
      say "stop requested during $name"; kill -TERM "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
      finish STOPPED_SYNCED
    fi
    sleep "$STOP_POLL" & wait $! 2>/dev/null
  done
  wait "$pid"; rc=$?
  for f in $outs; do
    if [ ! -s "$OUT/$f" ] || [ ! "$OUT/$f" -nt "$marker" ]; then bad+=("$f"); fi
  done
  echo -e "$name\t$rc\t${#bad[@]}" >> "$OUT/steps.tsv"
  if [ "$rc" = 124 ]; then say "$name timed out after $tmo s"; finish "FAIL_${name}_TIMEOUT"; fi
  if [ ${#bad[@]} -gt 0 ]; then say "$name rc=$rc but outputs missing/stale: ${bad[*]}"; finish "FAIL_${name}_NO_OUTPUT"; fi
  if [ "$rc" != 0 ]; then say "$name rc=$rc"; finish "FAIL_${name}_RC"; fi
  say "$name ok"
  if stop_requested; then finish STOPPED_SYNCED; fi
}

declare_required() {
  # Calls run_steps once with a `step` that only records its outputs. Run in a subshell, in an empty directory, with
  # PATH pointing nowhere: an external command in run_steps is refused instead of executed (it would run twice).
  # Limits: builtins, redirections and commands given by absolute path still run here; keep run_steps to `step` calls.
  local list="$RAKSTATE/required.list" flag="$RAKSTATE/required.flag" dir
  dir=$(mktemp -d); : > "$list"; rm -f "$flag"
  (
    cd "$dir" || exit 1
    PATH=/rak-declaration-pass-runs-no-commands
    command_not_found_handle() { echo "DECLARE run_steps runs '$1' outside a step" > "$flag"; return 127; }
    step() {
      local w words
      read -r -a words <<<"$3"   # no pathname expansion here, unlike `for f in $outs`
      for w in "${words[@]}"; do
        case $w in
          *[\*\?\[]*) echo "GLOB $1: '$w' is a pattern; declare explicit paths" > "$flag" ;;
          /* | .. | ../* | */../* | */..) echo "PATH $1: '$w' is not a path inside \$OUT" > "$flag" ;;
          *) printf '%s\n' "$w" >> "$list" ;;
        esac
      done
    }
    run_steps
  ) >/dev/null 2>&1
  rmdir "$dir" 2>/dev/null
  if [ -f "$flag" ]; then
    say "REQUIRED.txt not written: $(cut -d' ' -f2- "$flag")"
    finish "FAIL_REQUIRED_$(case $(cut -d' ' -f1 "$flag") in GLOB) echo GLOB ;; PATH) echo PATH ;; *) echo DECLARE ;; esac)"
  fi
  { echo "# rak-required v1"; LC_ALL=C sort -u "$list"; } > "$REQ_KEEP"
  cp "$REQ_KEEP" "$OUT/REQUIRED.txt"
  say "REQUIRED.txt: $(($(wc -l < "$REQ_KEEP") - 1)) declared outputs"
  sync_out || { say "REQUIRED.txt could not be verified in the bucket; not starting"; finish FAIL_SYNC; }
}

selfcheck() {
  if [ "${RAK_SKIP_GPU:-0}" != 1 ]; then
    nvidia-smi -L >/dev/null 2>&1 || { say "no GPU visible"; finish FAIL_SELFCHECK_GPU; }
  fi
  # Can this VM's service account really delete this VM and write the bucket? Tested as the VM itself, because a
  # policy that looks right can still not apply (conditions, propagation, the wrong account attached).
  local out
  out=$(${RAK_SELFCHECK_CMD:-selfcheck_permissions} 2>&1)
  echo "$out" > "$OUT/selfcheck.txt"
  grep -q "^DELETE_OK$" <<<"$out" || { say "service account cannot delete this VM"; finish FAIL_SELFCHECK_DELETE_PERMISSION; }
  grep -q "^WRITE_OK$" <<<"$out" || { say "service account cannot write the bucket"; finish FAIL_SELFCHECK_WRITE_PERMISSION; }
}

selfcheck_permissions() {  # uses the metadata token; prints DELETE_OK / WRITE_OK lines
  local M=http://metadata.google.internal/computeMetadata/v1 tok proj zone name bucket
  tok=$(curl -sf -H "Metadata-Flavor: Google" "$M/instance/service-accounts/default/token" | sed -E 's/.*"access_token":"([^"]+)".*/\1/')
  proj=$(curl -sf -H "Metadata-Flavor: Google" "$M/project/project-id")
  zone=$(curl -sf -H "Metadata-Flavor: Google" "$M/instance/zone"); zone=${zone##*/}
  name=$(curl -sf -H "Metadata-Flavor: Google" "$M/instance/name")
  curl -sf -X POST -H "Authorization: Bearer $tok" -H "Content-Type: application/json" \
    -d '{"permissions":["compute.instances.delete"]}' \
    "https://compute.googleapis.com/compute/v1/projects/$proj/zones/$zone/instances/$name/testIamPermissions" \
    | grep -q '"compute.instances.delete"' && echo DELETE_OK
  bucket=${RAK_OUT_URL#gs://}; bucket=${bucket%%/*}
  curl -sf -H "Authorization: Bearer $tok" \
    "https://storage.googleapis.com/storage/v1/b/$bucket/iam/testPermissions?permissions=storage.objects.create&permissions=storage.objects.get" \
    | grep -q '"storage.objects.create"' && echo WRITE_OK
}

say "=== vm_job start $(date -Is) out=$RAK_OUT_URL"
start_background
set_status RUNNING_SELFCHECK
selfcheck
# shellcheck source=/dev/null
source "$RAK_STEPS"
declare -F run_steps >/dev/null || finish FAIL_NO_RUN_STEPS
declare_required
run_steps
finish DONE
