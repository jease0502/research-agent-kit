# The README demo

`demo.gif` is drawn from `transcript.json`, which `run_demo.py` produced by running every command for real.

- **What ran:** a fresh `git clone` of this repository (commit `1f6f391`), then the commands shown in the GIF, one bash
  session, in `examples/friction-dr-anymal`. No model and no API key are involved; the hook is called with the
  same JSON Claude Code sends it. Cost 0.
- **What is not real:** the gate evidence values (step 3). They are typed in `run_demo.py` (`EVIDENCE`) so that the
  do-nothing control fails. No training or evaluation was run.
- **Setup that is not shown in the GIF:** a fresh `/tmp/rak-demo`, `python` pointing at Python 3.11, and writing
  the toy `gate_evidence.json`. The full script that ran is stored in `transcript.json` (`setup_script`).
- **Rendering:** `render_gif.py` draws the transcript text as it is, wrapping only lines wider than the terminal.

Reproduce (Linux or WSL, Python 3.11, git, network):

```bash
python3.11 docs/demo/run_demo.py /tmp/transcript.json   # prints each command, its output and exit code
python docs/demo/render_gif.py /tmp/transcript.json /tmp/demo.gif   # needs Pillow; set RAK_DEMO_FONT to a monospace .ttf
```
