# Third-party notices

| Component | Where | License | Upstream |
|---|---|---|---|
| KaTeX (`katex.min.js`, `katex.min.css`, fonts) | `python/rak/web/assets/vendor/katex/` | MIT. The full text is in that folder's `LICENSE` | https://github.com/KaTeX/KaTeX |

KaTeX is vendored, not loaded from a CDN, so the built site works offline.

Python dependencies are installed by pip and are not redistributed here: PyYAML (MIT), Markdown (BSD-3-Clause) and certifi (MPL-2.0).
