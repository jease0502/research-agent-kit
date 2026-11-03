"""build_logs.py template: numbers come from logs, or the lesson does not render."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

TEMPLATE = Path(__file__).resolve().parent.parent.parent.parent / "templates" / "build_logs.py"


class BuildLogs(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp(prefix="rakl-"))
        src = TEMPLATE.read_text(encoding="utf-8").replace(
            "EXTRACTORS: dict[str, tuple[str, str, str, str]] = {",
            'EXTRACTORS: dict[str, tuple[str, str, str, str]] = {\n'
            '    "control_success": ("summary.json", "json", "arms.control.success", "{:.2f}"),\n'
            '    "final_loss": ("train.log", "regex", r"loss=([0-9.]+)", "{:.3f}"),')
        (self.d / "build_logs.py").write_text(src, encoding="utf-8")
        (self.d / "logs").mkdir()
        (self.d / "logs" / "summary.json").write_text(json.dumps({"arms": {"control": {"success": 0.8}}}))
        (self.d / "logs" / "train.log").write_text("step 1 loss=0.9\nstep 2 loss=0.4567\n")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def py(self, *a):
        return subprocess.run([sys.executable, "build_logs.py", *a], cwd=self.d, capture_output=True, text=True)

    def test_extract_render(self):
        self.assertEqual(self.py("extract", "--logs", "logs", "--out", "n.json").returncode, 0)
        n = json.loads((self.d / "n.json").read_text())
        self.assertEqual(n["final_loss"]["text"], "0.457")  # last match, formatted only for display
        (self.d / "l.src.md").write_text("## What happened\n\nsuccess {{control_success}}, loss {{final_loss}}\n")
        r = self.py("render", "--src", "l.src.md", "--numbers", "n.json", "--out", "l.md")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("success 0.80, loss 0.457", (self.d / "l.md").read_text())

    def test_missing_log_raises(self):
        (self.d / "logs" / "train.log").unlink()
        self.assertNotEqual(self.py("extract", "--logs", "logs", "--out", "n.json").returncode, 0)

    def test_regex_matching_nothing_raises(self):
        (self.d / "logs" / "train.log").write_text("no numbers here\n")
        self.assertNotEqual(self.py("extract", "--logs", "logs", "--out", "n.json").returncode, 0)

    def test_check_flags_unknown_key_and_hand_typed_number(self):
        self.py("extract", "--logs", "logs", "--out", "n.json")
        (self.d / "l.src.md").write_text("## What happened\n\n{{nope}} and typed 0.93 by hand\n\n## Next\n0.5 is fine here\n")
        r = self.py("check", "--src", "l.src.md", "--numbers", "n.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("unknown key", r.stderr)
        self.assertIn("bare decimal", r.stderr)
        self.assertNotIn("line 6", r.stderr)


if __name__ == "__main__":
    unittest.main()
