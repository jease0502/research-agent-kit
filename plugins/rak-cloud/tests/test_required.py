"""The waiter reads REQUIRED.txt (the outputs every step declared, published by vm_job.sh before the first step;
5f61a54) when a VM is gone: the required list decides, the manifest supplies the hashes.

  gone             every manifest entry verified here, and every required path is one of them
  gone_unverified  anything else; OUTPUTS_UNVERIFIED lists every unverified path, not the first two
  REQUIRED.txt missing, or with a header other than "# rak-required v1": the required list is unknown, and the
  manifest-only rule applies (as before REQUIRED.txt existed). REQUIRED.txt with an absolute or ".." path cannot
  come from vm_job (it refuses those), so it is invalid: gone_unverified (cross-review of 8e0c5ee).
  A declared directory ("train" or "train/") is satisfied by at least one manifest entry under it: vm_job accepts
  a non-empty directory as an output, and the manifest lists only files (cross-review of 8e0c5ee).

The delete path (job ended, VM still there) is unchanged: it deletes once everything the job wrote is verified,
whether or not the declared outputs are all there, because a failed job is missing them by design. Missing
declared outputs are recorded there instead: REQUIRED_MISSING, the trace, and instances.json (maintainer, after 8e0c5ee).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))
import rak_cloud as rc  # noqa: E402
import test_bt_lifecycle as tl  # noqa: E402

FILES = {"model.pt": b"weights", "eval/summary.json": b'{"s": 1}'}


class Required(tl.BranchEnv):
    def outputs(self, files=FILES, manifest=True, required=None, header="# rak-required v1", status="RUNNING_TRAIN"):
        for n, data in files.items():
            (self.out / n).parent.mkdir(parents=True, exist_ok=True)
            (self.out / n).write_bytes(data)
        if manifest:
            (self.out / "MANIFEST.sha256").write_text("".join(f"{rc.sha256_file(self.out / n)}  ./{n}\n" for n in files))
        if required is not None:
            (self.out / "REQUIRED.txt").write_text("\n".join([header, *required]) + "\n")
        (self.out / "status.txt").write_text(status + "\n")

    def gone(self):
        (self.fake / "instances.json").write_text("{}")
        return self.w.poll()

    def test_all_required_verified_is_gone(self):
        self.outputs(required=["eval/summary.json", "model.pt"])
        self.assertEqual(self.gone(), "gone")
        self.assertEqual(self.w.bb["required"], ["eval/summary.json", "model.pt"])

    def test_required_file_never_written_is_gone_unverified(self):
        self.outputs(required=["eval/summary.json", "model.pt", "plots/curve.png"])
        self.assertEqual(self.gone(), "gone_unverified")
        self.assertEqual(self.w.bb["unverified"], ["required, not in the manifest: plots/curve.png"])

    def test_no_manifest_lists_every_required_path(self):
        self.outputs(files={"model.pt": b"half"}, manifest=False,
                     required=["eval/summary.json", "model.pt", "plots/curve.png"])
        self.assertEqual(self.gone(), "gone_unverified")
        self.assertEqual(self.w.bb["unverified"], [
            "MANIFEST.sha256 missing",
            "required, missing: eval/summary.json",
            "required, here but no hash to check: model.pt",
            "required, missing: plots/curve.png"])
        line = self.kw("OUTPUTS_UNVERIFIED")[0]
        for p in ("eval/summary.json", "model.pt", "plots/curve.png"):
            self.assertIn(p, line)
        self.assertNotIn("required list unknown", line)

    def test_hash_mismatch_of_a_required_file_is_listed_once(self):
        self.outputs(required=["eval/summary.json", "model.pt"])
        (self.out / "model.pt").write_bytes(b"changed after the manifest")
        self.assertEqual(self.gone(), "gone_unverified")
        self.assertEqual(self.w.bb["unverified"], ["hash differs model.pt"])

    def test_header_only_means_nothing_declared(self):
        self.outputs(required=[])
        self.assertEqual(self.gone(), "gone")

    def test_unknown_header_falls_back_to_the_manifest(self):
        self.outputs(required=["model.pt", "plots/curve.png"], header="# rak-required v2")
        self.assertEqual(self.gone(), "gone")                     # v2 is not guessed at: manifest-only rule
        self.assertIn("header", self.w.bb["required_source"])

    def test_unknown_header_without_manifest_says_list_unknown(self):
        self.outputs(manifest=False, required=["model.pt"], header="rak-required v1")
        self.assertEqual(self.gone(), "gone_unverified")
        self.assertEqual(self.w.bb["unverified"], ["MANIFEST.sha256 missing (required list unknown)"])

    def test_bad_paths_make_the_list_invalid_not_unknown(self):
        for bad in ("/etc/passwd", "../x", "a/../../b", "C:/x"):
            self.lines.clear()
            self.setUp_again()
            self.outputs(required=["model.pt", bad])                  # the manifest itself verifies
            self.assertEqual(self.gone(), "gone_unverified", bad)
            self.assertTrue(self.w.bb["unverified"][0].startswith("REQUIRED.txt invalid"), (bad, self.w.bb["unverified"]))

    def setUp_again(self):
        self.tearDown(); self.setUp()

    def test_delete_path_is_unchanged_by_required(self):
        self.outputs(required=["model.pt", "plots/curve.png"], status="FAIL_PLOT_NO_OUTPUT")
        self.assertEqual(self.w.poll(), "done")                   # everything written was verified: VM deleted

    # -- cross-review of 8e0c5ee
    def test_declared_directory_is_satisfied_by_files_under_it(self):
        for decl in ("train", "train/"):
            self.lines.clear(); self.setUp_again()
            self.outputs(files={"train/m.pt": b"w", "train/log.txt": b"l"}, required=[decl])
            self.assertEqual(self.gone(), "gone", decl)

    def test_declared_directory_with_nothing_under_it_is_unverified(self):
        self.outputs(files={"trainer.txt": b"x"}, required=["train"])      # a prefix, not a directory
        self.assertEqual(self.gone(), "gone_unverified")
        self.assertEqual(self.w.bb["unverified"], ["required, not in the manifest: train"])

    def test_declared_directory_without_manifest(self):
        self.outputs(files={"train/m.pt": b"w"}, manifest=False, required=["eval", "train"])   # sorted, as vm_job writes it
        self.assertEqual(self.gone(), "gone_unverified")
        self.assertEqual(self.w.bb["unverified"], ["MANIFEST.sha256 missing",
                                                   "required, missing: eval",
                                                   "required, here but no hash to check: train"])

    def test_end_line_says_what_the_verification_rested_on(self):
        self.outputs(required=["model.pt"])
        self.assertEqual(self.gone(), "gone")
        self.assertIn("outputs verified (REQUIRED.txt and manifest)", self.kw("END")[-1])
        self.lines.clear(); self.setUp_again()
        self.outputs()
        self.assertEqual(self.gone(), "gone")
        self.assertIn("outputs verified (manifest only; required list unknown)", self.kw("END")[-1])

    # -- maintainer, after 8e0c5ee: the delete path records missing declared outputs
    def test_delete_path_records_required_missing(self):
        self.outputs(required=["model.pt", "plots/curve.png", "train"], status="FAIL_PLOT_NO_OUTPUT")
        self.assertEqual(self.w.poll(), "done")
        line = self.kw("REQUIRED_MISSING")[0]
        self.assertIn("plots/curve.png", line); self.assertIn("train", line); self.assertNotIn("model.pt", line)
        rec = json.loads(rc.instances_file(self.root).read_text())[self.NAME]
        self.assertEqual(rec["required_missing"], ["plots/curve.png", "train"])
        r = [x for x in self.trace_file() if x["path"].endswith("pull_and_verify")][-1]
        self.assertIn("plots/curve.png", r["reason"])

    def test_delete_path_without_missing_outputs_records_nothing(self):
        self.outputs(required=["model.pt"], status="DONE")
        self.assertEqual(self.w.poll(), "done")
        self.assertFalse(self.kw("REQUIRED_MISSING"))
        self.assertNotIn("required_missing", json.loads(rc.instances_file(self.root).read_text())[self.NAME])
