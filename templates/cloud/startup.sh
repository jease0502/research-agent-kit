#!/usr/bin/env bash
# GCE startup script (runs on every boot). Static: everything per-run comes from instance metadata, set by
# rak_cloud.py create:
#   rak-job           gs:// prefix holding vm_job.sh and steps.sh
#   rak-out           gs:// prefix the job syncs its outputs to
#   rak-idle-minutes  idle guard threshold
#   rak-idle-check    the idle guard script itself (metadata-from-file)
# The job starts once: a reboot (maintenance, a crash) must not silently restart it from the beginning.
set -uo pipefail
exec > >(tee -a /var/log/rak-startup.log) 2>&1
echo "=== rak startup $(date -Is) ==="
META=http://metadata.google.internal/computeMetadata/v1/instance/attributes
meta() { curl -sf -m 5 -H "Metadata-Flavor: Google" "$META/$1"; }
JOB=$(meta rak-job) || { echo "no rak-job metadata"; exit 1; }
OUTURL=$(meta rak-out) || { echo "no rak-out metadata"; exit 1; }
IDLE=$(meta rak-idle-minutes) || { echo "no rak-idle-minutes metadata"; exit 1; }
[[ "$IDLE" =~ ^[0-9]+$ ]] || { echo "rak-idle-minutes is not a number: $IDLE"; exit 1; }

install -d -m 0755 /var/lib/rak
touch /var/lib/rak/heartbeat
echo 0 > /var/lib/rak/idle_count
echo "$OUTURL" > /var/lib/rak/gcs_dest
meta rak-idle-check > /usr/local/bin/rak-idle-check || { echo "no idle guard in metadata"; exit 1; }
chmod +x /usr/local/bin/rak-idle-check
# a guard with a syntax error would leave the VM running with no guard and no error anywhere
bash -n /usr/local/bin/rak-idle-check || { echo "idle guard has a syntax error"; exit 1; }
cat > /etc/systemd/system/rak-idle.service <<UNIT
[Unit]
Description=rak idle guard (final sync, then self-delete)
[Service]
Type=oneshot
Environment=IDLE_GPU_PCT=5
Environment=IDLE_MINUTES=${IDLE}
Environment=OUT_DIR=/root/rakout
Environment=REQUIRE_SYNC=1
Environment=SYNC_TIMEOUT=600
ExecStart=/usr/local/bin/rak-idle-check
UNIT
cat > /etc/systemd/system/rak-idle.timer <<'UNIT'
[Unit]
Description=Run the rak idle guard every minute
[Timer]
OnBootSec=10min
OnUnitActiveSec=1min
[Install]
WantedBy=timers.target
UNIT
systemctl daemon-reload
systemctl enable --now rak-idle.timer
systemctl is-active rak-idle.timer

if [ -f /var/lib/rak/job_started ]; then echo "job already started once (reboot?) - not restarting"; exit 0; fi
touch /var/lib/rak/job_started
for f in vm_job.sh steps.sh; do
  for i in 1 2 3; do gcloud storage cp "${JOB%/}/$f" "/root/$f" && [ -s "/root/$f" ] && break; sleep 15; done
  [ -s "/root/$f" ] || { echo "could not download $f"; exit 1; }
  bash -n "/root/$f" || { echo "$f has a syntax error"; exit 1; }
done
sha256sum /root/vm_job.sh /root/steps.sh
systemd-run --unit=rak-job --property=KillMode=process \
  --setenv=RAK_OUT_URL="$OUTURL" --setenv=RAK_STEPS=/root/steps.sh --setenv=HOME=/root \
  /bin/bash /root/vm_job.sh
echo "job started"
