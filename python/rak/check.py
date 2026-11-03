#!/usr/bin/env python3
"""Validate the frontmatter, sections and links of papers/, concepts/, topics/ and lessons/.

Three levels:

  error   — must be fixed. Always makes the exit code non-zero.
  warning — a quality problem (unknown tag, summary too long, non-standard section, ...).
            With `--strict` it also makes the exit code non-zero; CI uses that to stop schema drift.
  note    — to-do information; never affects the exit code. Broken links are notes: they are the list of
            "concept cards we still owe ourselves", not errors.

    rak check
    rak check --stats     # plus statistics and the to-do ranking
    rak check --strict    # warnings fail too (for CI)
"""

from __future__ import annotations

import argparse
import sys
import unicodedata
from collections import Counter, defaultdict

from . import config, mdio
from . import schema
from .i18n import tr



class Report:
    def __init__(self):
        self.errors: list[tuple[str, str]] = []
        self.warnings: list[tuple[str, str]] = []
        self.notes: list[tuple[str, str]] = []

    def error(self, where, msg):
        self.errors.append((where, msg))

    def warn(self, where, msg):
        self.warnings.append((where, msg))

    def note(self, where, msg):
        self.notes.append((where, msg))


def norm_alias(s: str) -> str:
    return unicodedata.normalize("NFKC", str(s)).strip().lower()


def load_all(rep: Report) -> dict:
    """Read every content file. Returns {slug: item}."""
    items: dict[str, dict] = {}
    seen_paths: dict[str, str] = {}

    for kind, path in mdio.all_content_files():
        slug = path.stem
        rel = f"{schema.DIR_OF[kind]}/{path.name}"

        if not schema.is_slug(slug):
            rep.error(rel, tr("check.001", a0=slug))
            continue
        if slug in seen_paths:
            rep.error(rel, tr("check.002", a0=slug, a1=seen_paths[slug]))
            continue
        seen_paths[slug] = rel

        meta, body, err = mdio.parse_file(path)
        if err:
            rep.error(rel, err)
            continue

        items[slug] = {
            "slug": slug,
            "kind": kind,
            "rel": rel,
            "path": path,
            "meta": meta,
            "body": body,
            "sections": mdio.split_sections(body),
        }
    return items


def build_alias_map(items: dict, rep: Report) -> dict[str, str]:
    """alias (NFKC, lower case) -> slug. A collision is an error, because link resolution would become ambiguous."""
    amap: dict[str, str] = {}
    for slug, it in items.items():
        for a in it["meta"].get("aliases") or []:
            if not isinstance(a, str):
                continue
            key = norm_alias(a)
            if key in items and key != slug:
                rep.error(it["rel"], tr("check.003", a0=a, a1=key))
                continue
            if key in amap and amap[key] != slug:
                rep.error(it["rel"], tr("check.004", a0=a, a1=amap[key], a2=slug))
                continue
            amap[key] = slug
    return amap


def resolve(target: str, items: dict, amap: dict[str, str]) -> str | None:
    """Resolve a link: exact file name, then file name ignoring case, then alias."""
    t = target.strip()
    if t in items:
        return t
    low = t.lower()
    if low in items:
        return low
    return amap.get(norm_alias(t))


def check_items(items: dict, amap: dict, vocab: set, rep: Report) -> dict:
    """Validate each file, collecting edges and broken links on the way."""
    outgoing: dict[str, set[str]] = defaultdict(set)
    broken = Counter()
    broken_where: dict[str, set[str]] = defaultdict(set)

    for slug, it in sorted(items.items()):
        kind, rel, meta = it["kind"], it["rel"], it["meta"]

        errs, warns, notes = schema.validate(kind, meta, vocab)
        for msg in errs:
            rep.error(rel, msg)
        for msg in warns:
            rep.warn(rel, msg)
        for msg in notes:
            rep.note(rel, msg)

        headings = [h for h, _ in it["sections"] if h]
        sec_err, sec_warn = schema.check_sections(kind, headings)
        for msg in sec_err:
            rep.error(rel, msg)
        for msg in sec_warn:
            rep.warn(rel, msg)

        todos = mdio.count_todos(it["body"])
        it["todos"] = todos
        if todos and meta.get("status") == "read":
            rep.warn(rel, tr("check.005", a0=todos))

        # --- edges: frontmatter arrays ∪ [[…]] in the body ---
        targets: list[tuple[str, str]] = []
        for field in schema.EDGE_FIELDS[kind]:
            for t in meta.get(field) or []:
                if isinstance(t, str):
                    targets.append((t, f"frontmatter `{field}`"))
        for t in mdio.wikilinks(it["body"]):
            targets.append((t, tr("check.006")))

        for target, where in targets:
            hit = resolve(target, items, amap)
            if hit is None:
                broken[target] += 1
                broken_where[target].add(rel)
                rep.note(rel, tr("check.007", a0=target, a1=where))
            elif hit == slug:
                rep.warn(rel, tr("check.008", a0=target, a1=where))
            else:
                outgoing[slug].add(hit)

        # a concept does not list the papers that cite it: that edge is declared on the paper's side only
        if kind == "concept" and meta.get("papers"):
            rep.error(rel, tr("check.009"))

    return {"outgoing": outgoing, "broken": broken, "broken_where": broken_where}


def check_parent_cycles(items: dict, amap: dict, rep: Report) -> None:
    """Concept parents must form a DAG, or the breadcrumbs recurse forever."""
    graph = {
        s: [
            r
            for r in (resolve(p, items, amap) for p in (it["meta"].get("parents") or []))
            if r
        ]
        for s, it in items.items()
        if it["kind"] == "concept"
    }
    WHITE, GREY, BLACK = 0, 1, 2
    color = defaultdict(int)

    def walk(node, stack):
        color[node] = GREY
        for nxt in graph.get(node, []):
            if color[nxt] == GREY:
                cycle = " → ".join(stack[stack.index(nxt):] + [nxt])
                rep.error(items[nxt]["rel"], tr("check.010", a0=cycle))
            elif color[nxt] == WHITE:
                walk(nxt, stack + [nxt])
        color[node] = BLACK

    for node in graph:
        if color[node] == WHITE:
            walk(node, [node])


def print_stats(items: dict, links: dict, rep: Report) -> None:
    counts = Counter(it["kind"] for it in items.values())
    print(tr("check.011") + "─" * 44)
    print(
        tr("check.012", a0=counts['paper'], a1=counts['concept'], a2=counts['topic'], a3=counts['lesson'], a4=len(items))
    )

    status = Counter(
        it["meta"].get("status", "?") for it in items.values() if it["kind"] == "paper"
    )
    if status:
        print(tr("check.013") + " · ".join(f"{k} {v}" for k, v in sorted(status.items())))

    todo_files = sorted(
        ((it["todos"], it["rel"]) for it in items.values() if it.get("todos")),
        reverse=True,
    )
    total_todo = sum(n for n, _ in todo_files)
    print(tr("check.014", a0=total_todo, a1=len(todo_files)))
    for n, rel in todo_files[:5]:
        print(f"    {n:>2} × TODO  {rel}")

    if links["broken"]:
        print(tr("check.015"))
        for target, n in links["broken"].most_common(8):
            where = ", ".join(sorted(links["broken_where"][target])[:3])
            print(tr("check.016", a0=n, a1=target, a2=where))

    # a concept with degree <= 1 is noise: merge it into another card, or it is not used yet
    indeg = Counter()
    for src, dsts in links["outgoing"].items():
        for d in dsts:
            indeg[d] += 1
    orphans = [
        it["slug"]
        for it in items.values()
        if it["kind"] == "concept"
        and indeg[it["slug"]] + len(links["outgoing"].get(it["slug"], ())) <= 1
    ]
    if orphans:
        print(tr("check.017", a0=', '.join(sorted(orphans))))

    tags = Counter(
        t for it in items.values() for t in (it["meta"].get("tags") or [])
    )
    if tags:
        print(tr("check.018") + " · ".join(f"{t}({n})" for t, n in tags.most_common(12)))
    print("─" * 52)


def main() -> int:
    mdio.enable_utf8_output()
    ap = argparse.ArgumentParser(description=tr("check.019"))
    ap.add_argument("--stats", action="store_true", help=tr("check.020"))
    ap.add_argument("--strict", action="store_true", help=tr("check.021"))
    ap.add_argument("--quiet", action="store_true", help=tr("check.022"))
    args = ap.parse_args()

    rep = Report()
    vocab = mdio.load_vocabulary(config.current().vocabulary_path)
    if not vocab:
        rep.warn("docs/vocabulary.md", tr("check.023"))

    items = load_all(rep)
    amap = build_alias_map(items, rep)
    links = check_items(items, amap, vocab or None, rep)
    check_parent_cycles(items, amap, rep)

    if not args.quiet:
        for level, entries, mark in (
            ("error", rep.errors, "✗"),
            ("warning", rep.warnings, "!"),
            ("note", rep.notes, "·"),
        ):
            if not entries:
                continue
            if level == "note" and not args.stats:
                continue
            print(f"\n{mark} {level} ({len(entries)})")
            for where, msg in entries:
                print(f"  {where}: {msg}")

    if args.stats:
        print_stats(items, links, rep)

    print(
        tr("check.024", a0=len(items), a1=len(rep.errors), a2=len(rep.warnings), a3=len(rep.notes))
    )

    if rep.errors:
        return 1
    if args.strict and rep.warnings:
        print(tr("check.025"))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
