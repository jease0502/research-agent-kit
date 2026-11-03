#!/usr/bin/env bash
# Example steps for vm_job.sh. Each `step` declares the outputs that prove it worked; the exit code alone never does.
#   step NAME TIMEOUT_S "OUTPUTS relative to \$OUT" -- command (runs in \$OUT, with TERM=xterm)
# A step that must not run as root (Isaac Sim refuses root) wraps its command in `sudo -u <user> -H`.
run_steps() {
  step SETUP 3600 "versions.txt" -- 'python3 --version > versions.txt && nvidia-smi --query-gpu=name,driver_version --format=csv >> versions.txt'
  step TRAIN 7200 "train/metrics.json train/model_final.pt" -- 'mkdir -p train && echo "replace with the real training command"; exit 1'
  step EVAL 1800 "eval/summary.json" -- 'mkdir -p eval && echo "replace with the real evaluation command"; exit 1'
}
