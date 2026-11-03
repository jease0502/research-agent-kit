# rak-knowledge

Markdown research knowledge base: add papers from arXiv/DOI, concept cards, cited keyword queries, daily digests, and a static site with a local-only Q&A bridge.

**Claude Code 2.1.295 or later is recommended** (the kit's guard hooks in the other plugins need it to fail closed).

## Skills

| Skill | What it does |
|---|---|
| `add-paper` | add a paper from arXiv/DOI with metadata from the API, never from memory; fill the note without inventing numbers |
| `concept-card` | create or update a concept card, deduplicated by alias, with a common-misconceptions section |
| `kb-query` | answer from the knowledge base with every fact pointing to a file and section |
| `daily-digest` | scheduled, non-interactive paper collection plus a judgment-first digest; success is judged by the digest file, not the exit code. The agent reads untrusted abstracts, so it gets no code execution and no free network access; run it in a container or VM (see the skill's "Threat model"). Its environment is an allow list: behind a corporate proxy, add `ALL_PROXY`, `SSL_CERT_FILE` or `NODE_EXTRA_CA_CERTS` to `ENV_ALLOW` if the CLI needs them |
| `citation-check` | check that citations exist and that title and first author match (arXiv, Crossref, OpenAlex); changes nothing |

Requires the `rak` CLI from `python/` (`pip install -e python`). Collision search before a claim lives in `rak-discipline`.

## Install

```
/plugin install rak-knowledge --marketplace <owner>/<repo>
```

The repository location is not decided yet; replace `<owner>/<repo>` once it is published.
