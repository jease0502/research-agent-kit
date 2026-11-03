"""Reverse cross-review of the security fixes (2026-10-31). Each failed before its fix.

A1 attr_list lets markdown itself add attributes: event handlers, srcdoc / srcset and style must go
A2 the scheme check must see the URL the way a browser does: entities decoded, tabs / newlines /
   control characters removed (javascript&#58;, &#106;avascript:, java<TAB>script:)
"""
from __future__ import annotations

import pytest

from rak import build as B


def render(src):
    ctx = {"resolve": lambda t: None, "sink": [], "broken": [], "media": False, "videos": []}
    return B.make_renderer(ctx)(src)


@pytest.mark.parametrize("src", [
    '[ok](https://example.org){ onclick="alert(1)" }',
    'Text\n{: onmouseover="alert(1)" }',
    '![x](https://e.example/a.png){ onerror="alert(1)" }',
    '# Heading { onfocus="alert(1)" tabindex="0" }',
    '[ok](https://example.org){ ONCLICK="alert(1)" }',
])
def test_attr_list_cannot_add_event_handlers(src):
    out = render(src).lower()
    assert " on" not in out.replace("onclick", " on") or "alert" not in out, out
    assert "alert(1)" not in out, out


@pytest.mark.parametrize("src,attr", [
    ('![x](https://e.example/a.png){ srcset="javascript:alert(1) 1x" }', "srcset"),
    ('![x](https://e.example/a.png){ srcdoc="<script>alert(1)</script>" }', "srcdoc"),
    ('[x](https://example.org){ style="position:fixed;top:0;left:0;width:100%;height:100%" }', "style"),
    ('[x](https://example.org){ formaction="javascript:alert(1)" }', "formaction"),
])
def test_attr_list_dangerous_attributes_are_dropped(src, attr):
    assert f"{attr}=" not in render(src), render(src)


@pytest.mark.parametrize("src", [
    "[x](javascript&#58;alert(1))",
    "[x](&#106;avascript:alert(1))",
    "[x](java\tscript:alert(1))",
    "[x](&#x6A;avascript:alert(1))",
    "[x](javascript&colon;alert(1))",
    "[x][r]\n\n[r]: javascript:alert(1)",
    "[x](\x01javascript:alert(1))",
    '[x](https://example.org){ href="javascript:alert(1)" }',
])
def test_scheme_check_decodes_like_a_browser(src):
    out = render(src)
    assert "href=" not in out or "alert" not in out, out


def test_safe_attributes_survive():
    out = render('[a](https://example.org/x){ title="t" .cls #anchor }\n\n![i](img/a.png){ width="40" }')
    assert 'href="https://example.org/x"' in out and 'title="t"' in out and 'class="cls"' in out
    assert 'src="img/a.png"' in out and 'width="40"' in out
