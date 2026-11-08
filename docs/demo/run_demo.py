#!/usr/bin/env python3
"""Run the demo for real and record every command with its real output and exit code.

Usage (inside WSL): python3.11 run_demo.py <out_transcript.json>
Each visible step is executed verbatim in one bash session; what is rendered is exactly what ran.
The setup step is not rendered; it is stored in the transcript so anyone can see it.
"""
import json, subprocess, sys

WORK = "/tmp/rak-demo"
SETUP = f"""set -e
rm -rf {WORK} && mkdir -p {WORK}/bin && ln -s /usr/bin/python3.11 {WORK}/bin/python
cd {WORK}
"""
EVIDENCE = {
    "g1_robot_static_friction_max_abs_dev": 0.0,
    "g1_robot_dynamic_friction_max_abs_dev": 0.0,
    "g1_ground_static_friction": 1.0,
    "g2_mean_success_drop_mu005_vs_mu08": 0.71,
    "g3_mean_abs_success_diff_override_vs_none": 0.01,
    "g4_control_mean_success_mu08": 0.93,
    "g5_zero_action_success_mu08": 0.62,
}
V = "experiments/friction-dr-anymal/verdict.py"
STEPS = [
    "git clone -q https://github.com/jease0502/research-agent-kit && git -C research-agent-kit log --oneline -1",
    "cd research-agent-kit/examples/friction-dr-anymal",
    "# hook: send a Bash command to the guard the way Claude Code does",
    "hook() {\n  printf '{\"hook_event_name\":\"PreToolUse\",\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"%s\"}}' \"$1\" |\n  python ../../plugins/rak-discipline/hooks/guard.py && echo \"allowed\"; }",
    "# 1. The agent starts training before deciding what success means",
    'hook "python train.py --seed 1"',
    "# 2. It freezes the pre-registration (prereg + verdict script hashed)",
    "python ../../plugins/rak-discipline/scripts/rak_discipline.py freeze docs/prereg/friction-dr-anymal.md | tail -1",
    'hook "RAK_PREREG=friction-dr-anymal python train.py --seed 1"',
    "# 3. Control evidence. TOY VALUES typed for this demo, not from a run:",
    "#    the do-nothing policy 'succeeds' 62% of the time: the metric can't be trusted",
    "cat gate_evidence.json",
    f"python {V} gate --evidence gate_evidence.json",
    "# 4. The agent asks for the verdict anyway",
    f'hook "RAK_PREREG=friction-dr-anymal python {V} judge --results results.json"',
    "# 5. It loosens the do-nothing threshold 0.05 -> 0.70 so the gate would pass",
    f"sed -i '/g5_zero_action/s/0.05/0.70/' {V} && grep -n g5_zero_action {V} | head -1",
    f"python {V} gate --evidence gate_evidence.json",
    'hook "RAK_PREREG=friction-dr-anymal python train.py --seed 2"',
]


def main():
    out = sys.argv[1]
    script = [SETUP, f"export PATH={WORK}/bin:$PATH", "exec 2>&1", "set +e"]
    for i, s in enumerate(STEPS):
        if i == 2:  # after cd: write the toy evidence file (setup, not rendered)
            script.append("python - <<'EOF'\nimport json\njson.dump(" + repr(EVIDENCE)
                          + ", open('gate_evidence.json','w'), indent=1)\nopen('gate_evidence.json','a').write('\\n')\nEOF")
        script.append(f"echo '@@BEGIN {i}'")
        script.append(s)
        script.append(f"echo \"@@END {i} $?\"")
    text = "\n".join(script) + "\n"
    p = subprocess.run(["bash", "-c", text], capture_output=True, text=True)
    steps, cur, buf = [], None, []
    for line in p.stdout.splitlines():
        if line.startswith("@@BEGIN "):
            cur, buf = int(line.split()[1]), []
        elif line.startswith("@@END "):
            _, i, code = line.split()
            steps.append({"cmd": STEPS[int(i)], "output": buf, "exit": int(code)})
            cur = None
        elif cur is not None:
            buf.append(line)
    json.dump({"setup_script": text, "returncode": p.returncode, "stderr": p.stderr, "steps": steps},
              open(out, "w"), indent=1)
    for s in steps:
        print("$", s["cmd"]); print("\n".join(s["output"])); print("[exit", s["exit"], "]")


if __name__ == "__main__":
    main()
