---
name: collision-search
description: Before committing to a research claim or a prereg, search for prior work that already has the same mechanism, the same guaranteed quantity or the same ablation argument - searching by mechanism rather than application area - and, when it collides, reposition instead of abandoning. Use before writing a prereg, a paper outline or a proposal, and when a reviewer or teammate says "isn't this X?".
license: Apache-2.0
compatibility: Needs web or arXiv search (WebSearch/WebFetch or the rak-knowledge search tools). Works in any agent.
metadata:
  plugin: rak-discipline
  version: "0.1.0"
---

# Collision search

Do this before writing, not before submitting. Finding a collision after the draft means rewriting the
framing; finding it before costs an hour.

## Why it lives in rak-discipline

The output is a commitment, not a reading list: the prereg's §1 must cite this record and name the
difference the run tests. The search tools belong to rak-knowledge; the rules for what counts as a
collision and what to do about it are discipline. If rak-knowledge is installed, use its search and
paper-adding tools for the queries below.

## What to search (in this order)

Space requests to a public API politely (for arXiv, at least 3 seconds between requests).

1. **Your mechanism, not your application.** People who collide with you often work in another field.
   Search the method in its own words ("complementary signals" AND "conformal risk control"),
   not your domain ("uncertainty of a robot planner").
2. **The form of the quantity you guarantee or measure.** `abs:"<the quantity you bound>" AND abs:"<method family>"`.
3. **Your ablation argument.** If the selling point is "A plus B beats either alone", the combination is the query.
4. **Once across fields.** The same template often appears first in NLP or vision.
5. **Generalisations and exceptions of the theorem you rely on** (what happens when its assumption fails).
6. **Renamed fields.** Your words find people who use your words. List two or three other names the idea
   could go by (other communities' terms, older terms) and search those too.

Read prior internal docs on the same line first; a collision already found by a teammate is not a new finding.

## What counts as a collision

| Collides | Does not collide |
|---|---|
| The algorithm template (the components and how they connect) | Application domain, robot body, dataset |
| The **form** of the guaranteed quantity (not its value) | Experiment scale, real hardware or not |
| The form of the ablation argument ("A+B beats each alone") | The specific model used |

Check the full text, not the abstract. Something that looks like a collision in the abstract can turn
out to be one of your ablations; something that looks different can turn out to be the same template.

## When it collides: reposition, do not abandon

1. Open the intro with a **"What is not new"** paragraph that states, at the level of equations, what
   already exists and who did it.
2. Rank the remaining differences; keep the strongest one or two and design an ablation that **could
   refute** each.
3. Turn the colliding work into a baseline or an ablation arm ("our A1 is their method").
4. Update the topic doc: keep the original (wrong) novelty judgement and append a correction
   (`erratum` skill). Do not delete it.

## Citation checking

Quote from the original. Read the PDF when you can; if you fall back to the HTML version, quote verbatim
and say "not checked against the PDF". A summarising tool's paraphrase is not a check. Check that the
PDF's title matches the metadata before quoting: an ID can resolve to a different paper.

## Output

A record `docs/collision/<topic>-<date>.md` with: queries (verbatim), date, hits read, verdict per hit
(collides / does not / is our ablation), the "what is not new" paragraph, and the difference the prereg
will test. Link it from prereg §1.
