"""Re-record the network responses the citation tests replay.

    python tests/fixtures/citation/record.py          # from python/; needs network

Runs the real checker over the sample inputs in this folder with a fetcher that saves every response
to responses/ and indexes it in responses/index.json (url -> status, file). The tests then replay
those bytes, so they need no network and always see the same answers.

Re-record when a service changes its format, and look at the diff before committing it: a recorded
response is evidence, not a fixture to be massaged until the tests pass.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from rak import __version__, citation  # noqa: E402

OUT = HERE / "responses"
INPUTS = [HERE / "refs.bib", HERE / "note.md", HERE / "draft.md"]


class Recorder(citation.Fetcher):
    def __init__(self):
        super().__init__(f"research-agent-kit/{__version__} (test recording)")
        self.index: dict[str, dict] = {}

    def get(self, url):
        status, body = super().get(url)
        name = hashlib.sha256(url.encode()).hexdigest()[:16] + ".bin"
        (OUT / name).write_bytes(body)
        self.index[url] = {"status": status, "file": name}
        print(f"{status} {url}")
        return status, body


def main() -> int:
    OUT.mkdir(exist_ok=True)
    for f in OUT.glob("*.bin"):
        f.unlink()
    rec = Recorder()
    results = citation.check(citation.read_claims(INPUTS), rec)
    (OUT / "index.json").write_text(json.dumps(rec.index, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    print(citation.report(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
