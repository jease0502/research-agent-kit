---
name: citation-check
description: Check that every citation in a draft, BibTeX file or knowledge-base note exists, and that its title and first author match the record (arXiv, Crossref, OpenAlex), without changing anything. Use before sending a draft, paper, report or slide deck that cites papers, when the user asks to verify references, or after an agent wrote text containing citations.
---

# citation-check

Language models produce references that look real and are not, and real references with the wrong title or author attached. This check runs **before** a draft leaves your hands.

## Run it

```bash
rak cite-check draft.md refs.bib                  # any mix of .md / .tex / .txt / .bib files or folders
rak cite-check papers/                             # every note in the knowledge base
rak cite-check refs.bib --json citecheck.json      # keep the full results
```

What it reads:

- **BibTeX entries**: title, author, year, `doi`, `eprint`, and arXiv or doi.org URLs.
- **Notes with YAML frontmatter** (`title`, `authors`, `arxiv` or `doi`): one claim per note.
- **Reference lists in any text**: a bullet, a numbered `[n]` line or a table row with an id or a year becomes a full claim (title, first author, year, id). Recognized titles: `Title: ...`, quotes, a markdown link's text, the longest bold or italic span, APA `Authors (Year). Title.`, and a table's first cell with words. A reference without an id is looked up by title, so it still counts.
- **arXiv ids (`arXiv:`, arxiv.org URLs) and DOIs elsewhere in the text**: existence checks only, since there is no claimed title to compare.

Where it looks:

- arXiv ids: the arXiv API, batched, about one request every 3.5 s.
- DOIs: Crossref, then OpenAlex if Crossref has no record.
- Entries with only a title: an OpenAlex title search, accepted only on a near-exact title match.

Set `contact` in `rak.toml` so the APIs see who is asking.

## Read the result

| Status | Meaning | What you do |
|---|---|---|
| `confirmed` | The record exists. The claimed title and first author, when given, match it | nothing |
| `mismatch` | The record exists, but the claimed title or first author is different. The report shows what the record actually says | **show the user both versions**. Usually the id points at another paper, or the author list was invented |
| `unconfirmed` | No record, the lookup failed, or the title search was ambiguous. Also: the citation adds a subtitle the record does not have, a title or first author that cannot be compared (no letters, an initial only, a non-Latin name, a partly overlapping surname), or a malformed id | **leave it marked**. Tell the user which ones and why |

Exit code 0 means everything is confirmed. 1 means at least one mismatch or unconfirmed entry, or that no citation was found at all (a bare `1707.06347` is not detected; write `arXiv:1707.06347`). 2 is a usage error.

## Rules

1. **Never delete, complete or "fix" a citation on your own.** Filling in whatever the search returned turns a fabricated reference into a plausible-looking real one, which is worse than an obviously broken one. The tool changes nothing, and neither do you, unless the user decides.
2. `unconfirmed` is not `wrong`. A network failure or a rate limit makes entries unconfirmed. Re-run later before telling the user a reference does not exist.
3. A `confirmed` existence check on a bare id says only that the id exists. It does not say that the paper supports the sentence it is attached to. When that matters, read the cited passage.
4. Report the counts and every non-confirmed line verbatim, for example: "11 citations: 6 confirmed, 2 mismatch, 3 unconfirmed", followed by the table rows.

## Known limits

- **Only the first author's surname is compared.** Two people with the same surname match: "Wang, Lei" is confirmed against a record whose first author is Jun Wang. Given names are not compared, because records abbreviate, reorder and transliterate them too often for a comparison to be reliable. If the first author matters, compare the full name by hand.
- **Co-authors are not checked.** A fabricated second author on a real paper is not caught.
- **Existence is not support.** A confirmed reference exists and has the claimed title and first author. Whether it says what the sentence citing it claims is not checked (rule 3).
