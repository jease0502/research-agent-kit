---
name: add-paper
description: Add a paper to the markdown knowledge base from an arXiv id, DOI or URL, then fill its note from the abstract without inventing anything. Use when the user gives an arXiv id/link or DOI and asks to add, save, note or read a paper into the knowledge base.
---

# add-paper

Adds one paper (or a batch) to a knowledge base created with `rak init`. The metadata (title, authors, year, venue) **comes from the arXiv or Crossref API, never from model memory**. The note body comes from the abstract or the full text, and every number in it must be one the source states.

Requires the `rak` CLI: `pip install -e python` from this repository (the package is not published on PyPI). Run commands from the knowledge-base root (the folder with `rak.toml`), or pass `rak --root DIR`.

## 1. Create the skeleton

```bash
rak add-paper 2307.15818                      # arXiv id, abs/pdf URL, or arXiv:… form
rak add-paper --doi 10.1038/nature14236       # non-arXiv paper
rak add-paper --manual --title "…" --authors "A. Chen; B. Lin" --year 2024 --url https://…
rak add-paper 2307.15818 --dry-run            # print, write nothing
rak add-paper 2307.15818 --refresh            # re-fetch metadata, keep the human-written body
rak add-paper --batch ids.txt                 # one id per line, any number; 10 ids per API request, 8 s apart
```

- **Never write the frontmatter by hand.** Author names and years from memory are the most common silent error in a knowledge base: they look right and nobody checks them.
- If the tool says the paper is **already in the database**, do not create a second note. Update the existing one.
- Several papers: always use `--batch`. One call per paper hits arXiv repeatedly and gets rate-limited (HTTP 429). The tool waits between requests on its own.
- Before a batch, remove ids that are already in the base: `grep -h '^arxiv:' papers/*.md`.

## 2. Read before writing

Open `papers/<slug>.md` and read the abstract section (the last section of the note) **in full**.

- Abstracts are often 1,200–1,800 characters, and the numbers are mostly in the last third.
- If you read in pieces, read all of them. Do not conclude "the abstract gives no numbers" from the first half.

**If the abstract is not enough to write the method and results sections responsibly, say so.** Either ask the user for the relevant passages, or read the full text from the source links (arXiv abstract page, HTML full text, PDF). Do not fill the gap from memory.

## 3. Fill the note

The section headings come from the knowledge base's configuration (`sections` in `rak.toml`; by default the preset that matches `locale`). They are written into the note by the tool. Use them exactly; `rak check` reports missing or misspelled ones.

The two built-in presets, in order:

| `en` (default) | `zh-TW` | Content |
|---|---|---|
| `TL;DR` | `TL;DR` | ≤ 3 sentences |
| `Problem and motivation` | `問題與動機` | what gap the paper addresses |
| `Method` | `方法` | how it works, at a level a reader can check against the paper |
| `Experiments and results` | `實驗與結果` | setups and numbers, all from the source |
| `Critique` | `我的評論` | limits, where it does not apply, what it is compared against, which claim does not hold up. "Good paper, worth reading" is not a critique |
| `Key concepts` | `關鍵知識點` | `- [[concept-slug]] — how this paper uses or advances it` |
| `Further reading` | `延伸閱讀` | related papers |
| `Abstract` | `原文摘要` | filled by the tool; do not edit |

Rules:

- **Leave `> TODO` rather than invent.** A TODO is visible and someone will fill it. An invented number looks like every other number and nobody will find it. This is the most important rule of the knowledge base.
- Every number must appear in the source.
- If you did not read the full text, say which sections came from the abstract only.

Then fill the frontmatter:

- `summary`: one sentence of at most 80 characters.
- `tags`: at most 5, and only tags listed in `docs/vocabulary.md`. To add a new tag, add a line to that file in the same commit.
- `status`: set it to `reading`. Only a person who has checked the note against the source may set `read`.
- `updated`: today's date.

## 4. Link concepts

Propose 3–6 concepts. For each one:

1. Check whether a card already exists. Include aliases in the search, in every language the base uses:
   ```bash
   rg -i "^(title|title_zh|aliases):.*<term>" concepts/
   ```
2. If it exists, link it with `[[slug]]`.
3. If it does not exist, **ask the user** before creating it. See the `concept-card` skill. Do not create cards in bulk without confirmation.

A link to a card that does not exist yet is fine. It appears in `rak check --stats` as a gap to fill later.

## 5. Check and report

```bash
rak check            # must show 0 error
```

Report to the user:

- what was added;
- which concepts it links to;
- which sections are still TODO, and why;
- whether the method and results came from the full text or only the abstract.

**Do not commit unless the user asked you to.** When several sessions share the repository, commit only your own paths (`git commit -m … -- papers/<slug>.md`), never `git add -A`.
