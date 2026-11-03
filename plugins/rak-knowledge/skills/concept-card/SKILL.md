---
name: concept-card
description: Create or update a concept card in the markdown knowledge base (an idea, algorithm or problem used by several papers), with aliases in every language the base uses and a common-misconceptions section. Use when a concept needs a card, when the user asks to define or add a concept, or after add-paper proposes a concept that does not exist yet.
---

# concept-card

A concept card is a knowledge point that **several** papers use: an algorithm, an idea, a recurring problem. Something with one arXiv id or DOI is a paper, not a concept. Something that needs an editorial view across papers ("what are the routes to X") is a topic.

## 1. Check for duplicates first, including every alias

```bash
rg -i "<term>" concepts/*.md INDEX.md
rg -i "^(title|title_zh|aliases):.*<term>" concepts/
```

Try synonyms and the other languages the base uses: "imitation learning" / "behavior cloning" / the term in Chinese or any other language in the base. Most duplicates are the same idea under a different name.

**Create cards only after the user agrees.** When add-paper proposes concepts, ask before creating them, and never create them in bulk.

## 2. Create the card

- Copy the project's `templates/concept.md` to `concepts/<slug>.md`. If the project has none, use the one bundled with `rak` for the knowledge base's section preset: `python/rak/templates/<en|zh-TW>/concept.md`.
- **Slug**: the full English name in kebab-case, e.g. `proximal-policy-optimization`. Abbreviations go in `aliases`, not in the slug.

Frontmatter:

| Field | Content |
|---|---|
| `title` | full name; quote it if it contains a colon |
| `type` | one of the types `rak check` accepts |
| `aliases` | **every name people search for**: the abbreviation, the full name, and the name in each language of the base (`PPO`, `Proximal Policy Optimization`, and its translation) |
| `parents` | the broader concepts |
| `related` | peers at the same level |
| `tags` | at most 5, from `docs/vocabulary.md` |
| `summary`, `added`, `updated` | one sentence; dates as `"YYYY-MM-DD"` strings |

`aliases` matter more than any other field. They drive link resolution, query routing and search ranking. In particular, a search in a second language only works if this field has the name in that language.

**Do not list papers on the card.** The edge from a paper to a concept is declared once, on the paper's side, and back-links are computed at build time. A list kept on the card drifts out of sync.

## 3. Write the sections

The headings of the two built-in presets (`sections` in `rak.toml`):

| `en` (default) | `zh-TW` | Content |
|---|---|---|
| `Definition` | `一句話定義` | understandable on its own, without the rest of the card |
| `Intuition` | `直覺` | an analogy, not a restatement of the formula |
| `Formalism` (optional) | `形式化` | the formula, with every term explained |
| `Why it matters` | `為什麼重要` | what breaks or becomes possible because of it |
| `Common misconceptions` | `常見誤解` | **the most valuable section of the card**. Write the ones you have actually seen people make. If you have none, leave `> TODO` instead of padding |

## 4. Updating an existing card

If the definition changes, find every note that links to the card and check that none of them now contradicts it:

```bash
rg "\[\[<slug>" papers/ topics/ lessons/
```

## 5. Check

```bash
rak check
```

It must show 0 error. Report the card, its aliases, and any notes whose wording you had to check against the new definition. Do not commit unless the user asked you to.
