---
name: kb-query
description: Answer a keyword or topic question from the markdown knowledge base, with every fact pointing to a file and section, and outside knowledge explicitly labeled. Use when the user asks what the knowledge base says about a term, method, paper or problem, or asks a research question the base may cover.
---

# kb-query

The knowledge base is worth something only because its answers can be traced. If an answer mixes in unlabeled model memory, nobody can tell which sentences came from the base, and the base stops being trustworthy without anyone noticing.

## Search, from exact to fuzzy

Stop as soon as you have enough:

```bash
rg -i "^(title|title_zh|aliases):.*<kw>" concepts/ papers/   # 1. is there a card or note for it?
rg -i "<kw>" INDEX.md                                        # 2. scan the one-line summaries
rg -n -i "<kw>" papers/ concepts/ topics/ lessons/           # 3. full text
```

- **Try synonyms and every language the base uses.** Notes are often written in one language with English technical terms. "imitation learning" / "behavior cloning" / the local-language term can each find notes the others miss.
- Read only what you need: the `TL;DR` and the sections that matched. Do not dump whole files.
- `INDEX.md` is the generated table of contents, one line per item. Read it instead of globbing every file.

## Answer format

```
### Direct answer
3–5 sentences, conclusion first.

### Sources
- [[paper-slug]] §Method: …
- [[concept-slug]] §Common misconceptions: …

### Related concepts
[[a]] [[b]] [[c]]

### Gaps
The base does not cover X. Papers worth adding: … Shall I add them (add-paper)?
```

## Rules

1. **Every fact points to a file and a section** in the base.
2. Anything from outside the base is labeled inline: *(outside the knowledge base, unverified)*.
3. If the base has nothing on the question, **say "we have no notes on this yet"**, then suggest 2–3 papers worth adding. Do not present general knowledge as if it came from the base.
4. Numbers are quoted exactly as the note gives them, with the note's section. If two notes disagree, show both and say so; do not average or pick one silently.
5. A note whose `status` is `queued` or whose section is `> TODO` has not been checked against its source. Say so when you rely on it.
