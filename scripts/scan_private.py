#!/usr/bin/env python3
"""開源前的 deny-list 掃描：私有名稱、帳號、專案 ID、bucket、本機路徑、token。

    python scripts/scan_private.py                 # 掃工作區（git 追蹤的檔＋還沒 ignore 的新檔）
    python scripts/scan_private.py PATH ...        # 只掃指定的檔或資料夾
    python scripts/scan_private.py --history       # 另外掃 git 歷史裡每個 blob 與每則 commit 訊息
    python scripts/scan_private.py --list-rules

結束碼：0 乾淨、1 有命中、2 用法錯誤或（在 CI 裡）找不到私有名單。只用標準函式庫，CI 與本機都能跑。

## 兩種規則

1. **樣式（regex）**：任何專案都不該公開的東西 —— 本機使用者路徑、email、GCP 自動產生的專案 ID、
   具體的 gs:// bucket、Tailscale（CGNAT）IP、各家 token 與私鑰。規則寫在下面 RULES，公開無妨。
2. **私有名稱**：專案名、帳號名這類「寫出來就洩漏」的字。**名單不進 repo，任何形式都不行**
   （雜湊也不行：短名稱可以被暴力猜回來，等於把名單公開）。
   - 名單是明文、一行一個字、`#` 開頭是註解。位置：環境變數 `RAK_DENY_FILE`，
     沒設就用 `~/.config/research-agent-kit/deny.txt`。
   - CI：名單放在 repository secret `RAK_DENY_TERMS`，workflow 寫到暫存檔再設 `RAK_DENY_FILE`。
   - **找不到名單時：在 CI（`CI=true`）判失敗（結束碼 2）；在本機只印警告**、照樣跑樣式規則。
     CI 不能「沒名單就當作沒有私有名稱」：那正是名單被誤刪時會發生的事。
   - 比對時把文字切成詞、取 1–4 個相鄰詞接起來比（`Acme Corp`、`acme_corp`、`acmecorp` 都會中）；
     中日韓字用名單字長的滑動視窗比對。

## 核可的 commit 身分

使用者決定 commit 身分不重寫（2026-11-01），所以 `--history` 的 author／committer 欄位可以豁免**核可的身分**：
`名字 <email>` 一行一個，名字與 email 都要**逐字完全相同**才豁免（大小寫、空白、不同 email 都照樣命中），
author 與 committer 各自判斷。只豁免這兩個欄位：commit 訊息、檔案內容、路徑裡出現同一個名字照樣命中。
名單跟私有名單一樣不進 repo：環境變數 `RAK_ALLOW_IDENTITIES`（檔案路徑），沒設就用
`~/.config/research-agent-kit/allow_identities.txt`；CI 用 secret `RAK_ALLOW_IDENTITIES` 寫成暫存檔。
找不到名單就照舊判命中。輸出只印豁免了幾個欄位，不印身分。

## 命中時不印出命中的字

CI 的 log 是公開的。輸出只有 `檔案:行:欄  規則  遮罩後的片段`；私有名稱只印它在名單的第幾行。

## 放行

- 該行加註 `rak-scan: allow <規則>`（例如文件裡示範路徑長相）。私有名稱沒有放行機制。
- `.rak-scan-allow`：一行 `<glob> <規則>`，整個檔放行某條樣式規則。
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import os
import re
import subprocess
import sys
import unicodedata
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_DENY_FILE = Path.home() / ".config" / "research-agent-kit" / "deny.txt"
DEFAULT_IDENTITIES_FILE = Path.home() / ".config" / "research-agent-kit" / "allow_identities.txt"
IDENTITY_LINE = re.compile(r"^(?P<name>[^<>]*[^<>\s])\s<(?P<email>[^<>\s]+)>$")
ALLOW_FILE_NAME = ".rak-scan-allow"
MAX_BYTES = 5 * 1024 * 1024
MAX_JOIN = 4  # 私有名稱最多由幾個相鄰詞組成（例如 IP 的四段）

# RFC 2606 保留給文件與測試的網域，加上 commit attribution 用的 noreply
EMAIL_OK_DOMAINS = ("example.com", "example.org", "example.net", ".example", ".invalid", ".test", ".localhost",
                    "anthropic.com", "users.noreply.github.com")
EMAIL_OK_EXACT = {"git@github.com"}
FILE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "svg", "webp", "ico", "pdf", "bmp", "tif", "tiff", "avif"}
HOME_OK_USERS = {"user", "runner", "ubuntu", "you", "me", "example", "root", "username"}
BUCKET_OK = re.compile(r"^(bucket|my-bucket|example[a-z0-9._-]*|your-[a-z0-9._-]*|fake[a-z0-9._-]*)$")

RULES: dict[str, tuple[re.Pattern, str]] = {
    "user-path": (re.compile(r"(?i)(?<![a-z0-9])[a-z]:[\\/]+users[\\/]+[^\\/\s\"'`<>]+"
                             r"|/[a-z]/users/[^/\s\"'`<>]+|/Users/[A-Za-z][^/\s\"'`<>]*"),
                  "本機使用者目錄"),
    "drive-path": (re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/](?![\\/])[A-Za-z0-9_.-]+[\\/]|/mnt/[a-z]/[A-Za-z0-9_.-]+"),
                   "本機磁碟路徑"),
    "home-path": (re.compile(r"/home/([A-Za-z_][A-Za-z0-9_.-]*)"), "Linux 家目錄"),
    # bounded local part (RFC 5321 allows 64): unbounded, a long line without "@" backtracks quadratically
    "email": (re.compile(r"[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63}){0,8}\.[A-Za-z]{2,24}"),
              "email"),
    "gcp-project-id": (re.compile(r"\bproject-[0-9a-f]{8}-[0-9a-f]{4}"), "GCP 自動產生的專案 ID"),
    "gcs-bucket": (re.compile(r"gs://([a-z0-9][a-z0-9._-]{2,})"), "具體的 GCS bucket"),
    "cgnat-ip": (re.compile(r"\b100\.(?:6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.\d{1,3}\.\d{1,3}\b"),
                 "Tailscale／CGNAT IP"),
    "telegram-token": (re.compile(r"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b"), "Telegram bot token"),
    "hf-token": (re.compile(r"\bhf_[A-Za-z0-9]{30,}"), "Hugging Face token"),
    "github-token": (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{50,})"), "GitHub token"),
    "aws-key": (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key"),
    "google-api-key": (re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"), "Google API key"),
    "anthropic-key": (re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}"), "Anthropic API key"),
    "openai-key": (re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9]{32,}"), "OpenAI API key"),
    "slack-token": (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"), "Slack token"),
    "private-key": (re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----"), "私鑰"),
    "gcp-sa-key": (re.compile(r"\"private_key_id\"\s*:\s*\"[0-9a-f]{20,}\""), "GCP 服務帳號金鑰"),
}

INLINE_ALLOW = re.compile(r"rak-scan:\s*allow\s+([a-z0-9-]+(?:\s*,\s*[a-z0-9-]+)*)")
ASCII_TOKEN = re.compile(r"[a-z0-9]+")
CJK_RUN = re.compile(r"[぀-ヿ㐀-䶿一-鿿豈-﫿ᄀ-ᇿ㄰-㆏가-힯]+")


# ── 私有名稱 ────────────────────────────────────────────────────────────────

class TermsError(ValueError):
    """A malformed deny-list entry. The message names the line number and the problem, never the entry."""


def normalize_term(term: str) -> tuple[str, str]:
    """(kind, normalized), kind "ascii" or "cjk" (CJK ideographs, kana, Hangul).

    Errors never contain the term: they end up in CI logs, which are public."""
    t = term.strip().lower()
    if CJK_RUN.fullmatch(t):
        return "cjk", t
    if CJK_RUN.search(t):
        raise TermsError("mixes CJK/kana/Hangul with Latin letters or digits; split it into two entries")
    toks = ASCII_TOKEN.findall(t)
    if not toks:
        raise TermsError("has no letters or digits")
    if len(toks) > MAX_JOIN:
        raise TermsError(f"has more than {MAX_JOIN} words")
    return "ascii", "".join(toks)


class Terms:
    """私有名稱名單。只存在記憶體裡；輸出時只用「名單第幾行」指稱。"""

    def __init__(self, entries: dict[str, int], cjk_lens: set[int]):
        self.entries, self.cjk_lens = entries, cjk_lens

    @classmethod
    def empty(cls) -> "Terms":
        return cls({}, set())

    @classmethod
    def from_lines(cls, lines) -> "Terms":
        entries: dict[str, int] = {}
        lens: set[int] = set()
        for n, line in enumerate(lines, 1):
            line = line.lstrip("\ufeff").strip()          # a BOM on the first line is not part of the entry
            if not line or line.startswith("#"):
                continue
            try:
                kind, norm = normalize_term(line)
            except TermsError as e:
                raise TermsError(f"deny list line {n} {e}") from None
            entries.setdefault(norm, n)
            if kind == "cjk":
                lens.add(len(norm))
        return cls(entries, lens)

    @classmethod
    def load(cls, path: Path) -> "Terms":
        return cls.from_lines(path.read_text(encoding="utf-8-sig").splitlines())

    def __len__(self) -> int:
        return len(self.entries)

    def find(self, line: str):
        """(column, list line) for each private name in one line."""
        for ln, col, idx in self.find_in_text(line):
            yield col, idx

    def find_in_text(self, text: str):
        """(line, column, list line) for each private name in a text, including the variants the review
        found missed (M14): camelCase or digits glued on (ZorblaxBot, acmeCorpLab, zorblax2), percent-encoding,
        full-width forms (NFKC), and a name split across a line break (acme / corp, zor- / blax).
        Simplified and traditional CJK are not converted: list both forms."""
        seen = set()
        for form in _forms(text):
            lines = form.split("\n")
            toks = []
            for ln, line in enumerate(lines, 1):
                split = _CAMEL.sub(" ", line).lower()
                toks += [(ln, m.start() + 1, m.group()) for m in ASCII_TOKEN.finditer(split)]
            for i in range(len(toks)):
                joined = ""
                for j in range(i, min(i + WINDOW, len(toks))):
                    joined += toks[j][2]
                    idx = self.entries.get(joined)
                    if idx is not None and (toks[i][0], toks[i][1], idx) not in seen:
                        seen.add((toks[i][0], toks[i][1], idx))
                        yield toks[i][0], toks[i][1], idx
            for ln, line in enumerate(lines, 1):
                low = line.lower()
                nxt = lines[ln].lstrip().lower() if ln < len(lines) else ""
                runs = [(m.start(), m.group()) for m in CJK_RUN.finditer(low)]
                if runs and low.rstrip().endswith(runs[-1][1]) and CJK_RUN.match(nxt):
                    runs[-1] = (runs[-1][0], runs[-1][1] + CJK_RUN.match(nxt).group())   # wrapped CJK name
                for start, run in runs:
                    for n in self.cjk_lens:
                        for k in range(len(run) - n + 1):
                            idx = self.entries.get(run[k:k + n])
                            if idx is not None and (ln, start + k + 1, idx) not in seen:
                                seen.add((ln, start + k + 1, idx))
                                yield ln, start + k + 1, idx


_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Za-z])(?=\d)|(?<=\d)(?=[A-Za-z])")
WINDOW = 2 * MAX_JOIN        # camelCase and digit splitting can turn one listed word into several tokens


def _forms(text: str) -> list[str]:
    """The text as scanned: NFKC-normalized (full-width -> ASCII), plus its percent-decoded form."""
    norm = unicodedata.normalize("NFKC", text)
    forms = [norm]
    if "%" in norm:
        dec = urllib.parse.unquote(norm)
        if dec != norm:
            forms.append(dec)
    return forms


def deny_file() -> Path:
    env = os.environ.get("RAK_DENY_FILE")
    return Path(env).expanduser() if env else DEFAULT_DENY_FILE


def load_terms() -> tuple[Terms | None, str]:
    """回傳 (名單, 說明)。找不到或是空的就回傳 None。"""
    f = deny_file()
    if not f.is_file():
        return None, f"找不到私有名單 {f}"
    try:
        terms = Terms.load(f)
    except TermsError as e:
        raise TermsError(str(e)) from None
    except UnicodeDecodeError:
        raise TermsError("deny list is not UTF-8") from None
    if not len(terms):
        # no path: in CI it is a temp file, and "empty" there means the secret was not set
        return None, "私有名單是空的（在 CI：secret RAK_DENY_TERMS 沒設或是空的）"
    return terms, f"私有名單 {len(terms)} 項"


def load_identities_file(f: Path) -> set[tuple[str, str]]:
    """`名字 <email>` 一行一個；`#` 開頭是註解。行首行尾的空白不算，名字中間的空白照原樣比。"""
    out = set()
    for n, line in enumerate(f.read_text(encoding="utf-8-sig").splitlines(), 1):   # Notepad writes a BOM
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = IDENTITY_LINE.match(line)
        if not m:
            raise TermsError(f"identity list line {n} is not `Name <email>`")
        out.add((m["name"], m["email"]))
    return out


def load_identities() -> tuple[set[tuple[str, str]], str]:
    env = os.environ.get("RAK_ALLOW_IDENTITIES")
    f = Path(env).expanduser() if env else DEFAULT_IDENTITIES_FILE
    if not f.is_file():
        return set(), "沒有核可身分名單"
    try:
        ids = load_identities_file(f)
    except UnicodeDecodeError:
        raise TermsError("identity list is not UTF-8") from None
    if not ids:
        return ids, "核可身分名單是空的（在 CI：secret RAK_ALLOW_IDENTITIES 沒設或是空的）"
    return ids, f"核可身分 {len(ids)} 項"


# ── 樣式 ────────────────────────────────────────────────────────────────────

def _rule_hit_ok(rule: str, m: re.Match) -> bool:
    """少數規則有「看起來像但其實是占位符」的合法值。"""
    if rule == "email":
        s = m.group().lower()
        local, domain = s.split("@", 1)
        if s in EMAIL_OK_EXACT or local == "git":                 # ssh://git@host/repo is not an address
            return True
        if domain.rsplit(".", 1)[-1] in FILE_EXTENSIONS:         # icon@2x.png is an image name
            return True
        # whole domains only: myexample.com is not example.com
        return any(domain == d.lstrip(".") or domain.endswith("." + d.lstrip(".")) for d in EMAIL_OK_DOMAINS)
    if rule == "home-path":
        return m.group(1).lower() in HOME_OK_USERS
    if rule == "gcs-bucket":
        return bool(BUCKET_OK.match(m.group(1)))
    return False


def mask(s: str) -> str:
    return s[:3] + "…" if len(s) > 3 else "…"


def display_path(path: str, terms: "Terms") -> str:
    """The path as it may be printed: each component that contains a private name is replaced by
    <private-term line N>, so a privately named folder never reaches the (public) CI log."""
    out = []
    for comp in path.split("/"):
        hits = sorted({idx for _, idx in terms.find(comp)})
        out.append("<private-term line " + ",".join(map(str, hits)) + ">" if hits else comp)
    shown = "/".join(out)
    # a name the matcher finds only across folders (acme/corp) or in a form no single folder shows:
    # print a hash of the whole path, never the original
    if list(terms.find_in_text(shown.replace("/", " "))) or (shown == path and list(terms.find_in_text(path.replace("/", " ")))):
        return "<private-path " + hashlib.sha256(path.encode("utf-8")).hexdigest()[:12] + ">"
    return shown


def load_allow(root: Path) -> list[tuple[str, str]]:
    f = root / ALLOW_FILE_NAME
    out = []
    if f.is_file():
        for n, line in enumerate(f.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = line.split("#", 1)[0].strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) != 2 or parts[1] not in RULES:
                raise SystemExit(f"{f}:{n}: 格式是 `<glob> <規則>`，規則要是 {sorted(RULES)} 之一")
            out.append((parts[0], parts[1]))
    return out


def scan_text(name: str, text: str, terms: Terms, allow_rules: set[str] = frozenset()):
    """產生 (name, 行, 欄, 規則, 說明)。"""
    for n, col, idx in terms.find_in_text(text):
        yield name, n, col, "private-term", f"private name (deny list line {idx})"
    for n, line in enumerate(text.splitlines(), 1):
        inline = set()
        m = INLINE_ALLOW.search(line)
        if m:
            inline = {r.strip() for r in m.group(1).split(",")}
        for rule, (rx, desc) in RULES.items():
            if rule in allow_rules or rule in inline or (rule == "email" and "@" not in line):
                continue
            for hit in rx.finditer(line):
                if not _rule_hit_ok(rule, hit):
                    # an address is personal even in part: nothing of it is printed
                    shown = "email：<redacted>" if rule == "email" else f"{desc}：{mask(hit.group())}"
                    yield name, n, hit.start() + 1, rule, shown



def is_binary(data: bytes) -> bool:
    return b"\0" in data[:8192]


def decode(data: bytes) -> str | None:
    """Text of a file, or None if it is binary. UTF-16 (with a BOM, or with the NUL pattern of mostly
    ASCII text) is decoded before the NUL check would call it binary."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16", errors="replace")
    head = data[:8192]
    if len(head) >= 4 and head[1::2].count(0) > len(head) // 4 and head[0::2].count(0) == 0:
        return data.decode("utf-16-le", errors="replace")
    if len(head) >= 4 and head[0::2].count(0) > len(head) // 4 and head[1::2].count(0) == 0:
        return data.decode("utf-16-be", errors="replace")
    if is_binary(data):
        return None
    return data.decode("utf-8", errors="replace")


def git_files(root: Path) -> list[str] | None:
    try:
        out = subprocess.run(["git", "ls-files", "-co", "--exclude-standard", "-z"], cwd=root,
                             capture_output=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return [p for p in out.stdout.decode("utf-8").split("\0") if p]


def walk(paths: list[Path], root: Path):
    for p in paths:
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file() and ".git" not in f.relative_to(p).parts:
                    yield f
        elif p.is_file():
            yield p


def scan_files(files, root: Path, terms: Terms, allow: list[tuple[str, str]]):
    for f in files:
        rel = f.relative_to(root).as_posix() if f.is_relative_to(root) else f.as_posix()
        shown = display_path(rel, terms)
        allow_rules = {r for g, r in allow if fnmatch.fnmatch(rel, g)}
        # the path itself counts: private names often appear in folder names
        yield from scan_text(f"{shown} (path)", rel, terms, allow_rules | {"drive-path", "user-path"})
        text = decode(f.read_bytes())
        if text is not None:
            yield from scan_text(shown, text, terms, allow_rules)


def _git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", *args], cwd=root, capture_output=True, check=True).stdout


def scan_staged(root: Path, terms: Terms, allow: list[tuple[str, str]]):
    """The staged blobs: what the commit will contain, which can differ from the working tree
    (a file cleaned after `git add` still commits the dirty version). Deleted files are skipped."""
    names = _git(root, "diff", "--cached", "--name-only", "-z", "--diff-filter=ACMRT").decode("utf-8", "replace")
    paths = [x for x in names.split("\0") if x]
    for path in paths:
        allow_rules = {r for g, r in allow if fnmatch.fnmatch(path, g)}
        shown = display_path(path, terms)
        yield from scan_text(f"{shown} (path, staged)", path, terms, allow_rules | {"drive-path", "user-path"})
        text = decode(_git(root, "cat-file", "blob", f":{path}"))
        if text is not None:
            yield from scan_text(f"{shown} (staged)", text, terms, allow_rules)
    return paths


def scan_history(root: Path, terms: Terms, allow: list[tuple[str, str]],
                 identities: set[tuple[str, str]] = frozenset(), exempted: list | None = None):
    """Everything in git history that would be published with the repository:
    commit messages, author and committer names and emails, annotated tag names and messages, every path any
    commit touched (including names a later rename removed), and every blob (no size limit; UTF-16 decoded).
    An author, committer or tagger field whose (name, email) is exactly one of `identities` is not scanned; each
    such field is appended to `exempted`, so the caller can count them."""
    log = _git(root, "log", "--all", "--format=%H%x00%an%x00%ae%x00%cn%x00%ce%x00%B%x01").decode("utf-8", "replace")
    for rec in filter(None, (r.strip("\n") for r in log.split("\x01"))):
        sha, an, ae, cn, ce, msg = (rec.split("\x00") + [""] * 6)[:6]
        yield from scan_text(f"commit {sha[:10]} message", msg, terms)
        for field, name, email in (("author", an, ae), ("committer", cn, ce)):
            if (name, email) in identities:
                if exempted is not None:
                    exempted.append((sha, field))
                continue
            yield from scan_text(f"commit {sha[:10]} {field}", f"{name} <{email}>", terms)
    tags = _git(root, "for-each-ref", "refs/tags",
                "--format=%(objectname)%00%(refname:short)%00%(taggername)%00%(taggeremail)%00%(contents)%01")
    for rec in filter(None, (r.strip("\n") for r in tags.decode("utf-8", "replace").split("\x01"))):
        sha, name, tn, te, msg = (rec.split("\x00") + [""] * 5)[:5]
        label = f"tag {sha[:10]}"
        yield from scan_text(f"{label} name", name, terms)
        yield from scan_text(f"{label} message", msg, terms)
        te = te.strip()
        te = te[1:-1] if te.startswith("<") and te.endswith(">") else te
        if tn or te:                        # annotated tags only; the tagger is judged like an author
            if (tn, te) in identities:
                if exempted is not None:
                    exempted.append((sha, "tagger"))
            else:
                yield from scan_text(f"{label} tagger", f"{tn} <{te}>", terms)
    # every path any commit touched; --no-renames lists a renamed file's old path as a deletion
    paths = set(_git(root, "log", "--all", "--no-renames", "--format=", "--name-only", "-z").decode("utf-8", "replace")
                .replace("\n", "\0").split("\0"))
    for path in sorted(p for p in paths if p):
        allow_rules = {r for g, r in allow if fnmatch.fnmatch(path, g)}
        yield from scan_text(f"{display_path(path, terms)} (path, history)", path, terms,
                             allow_rules | {"drive-path", "user-path"})
    objs = _git(root, "rev-list", "--all", "--objects").decode("utf-8", "replace")
    seen = set()
    for line in objs.splitlines():
        sha, _, path = line.partition(" ")
        if not path or sha in seen:
            continue
        seen.add(sha)
        if _git(root, "cat-file", "-t", sha).decode().strip() != "blob":
            continue
        text = decode(_git(root, "cat-file", "blob", sha))
        if text is not None:
            allow_rules = {r for g, r in allow if fnmatch.fnmatch(path, g)}
            yield from scan_text(f"{display_path(path, terms)}@{sha[:10]}", text, terms, allow_rules)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("paths", nargs="*", type=Path)
    ap.add_argument("--root", type=Path, default=None, help="repo 根目錄（預設：這支腳本的上一層）")
    ap.add_argument("--history", action="store_true", help="另外掃 git 歷史")
    ap.add_argument("--staged", action="store_true",
                    help="only the staged blobs (what the next commit contains); used by scripts/hooks/pre-commit")
    ap.add_argument("--list-rules", action="store_true")
    a = ap.parse_args(argv)
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass

    if a.list_rules:
        for r, (_, d) in RULES.items():
            print(f"{r:16} {d}")
        print(f"{'private-term':16} 私有名稱（名單：RAK_DENY_FILE 或 {DEFAULT_DENY_FILE}）")
        return 0
    try:
        terms, note = load_terms()
        identities, id_note = load_identities() if a.history else (set(), "")
    except TermsError as e:
        print(f"✗ {e}. Fix that line; nothing was scanned.", file=sys.stderr)
        return 2
    if terms is None:
        if os.environ.get("CI", "").lower() == "true":
            print(f"✗ {note}。CI 裡沒有名單就不能宣稱乾淨：設 secret RAK_DENY_TERMS（見 .github/workflows/ci.yml）。",
                  file=sys.stderr)
            return 2
        print(f"! {note} —— 只跑樣式規則，私有名稱沒有檢查。名單放在 RAK_DENY_FILE 或 {DEFAULT_DENY_FILE}。",
              file=sys.stderr)
        terms = Terms.empty()

    root = (a.root or HERE.parent).resolve()
    allow = load_allow(root)
    if a.staged:
        hits = list(scan_staged(root, terms, allow))
        for name, n, col, rule, desc in hits:
            print(f"{name}:{n}:{col}  {rule}  {desc}")
        print(f"staged ｜ {note} ｜ 命中 {len(hits)}", file=sys.stderr)
        return 1 if hits else 0
    if a.paths:
        files = list(walk([p.resolve() for p in a.paths], root))
    else:
        rels = git_files(root)
        files = [root / r for r in rels if (root / r).is_file()] if rels is not None else list(walk([root], root))
    hits = list(scan_files(files, root, terms, allow))
    exempted: list = []
    if a.history:
        hits += list(scan_history(root, terms, allow, identities, exempted))
        note += f" ｜ {id_note}（豁免 {len(exempted)} 個 author/committer 欄位）"
    for name, n, col, rule, desc in hits:
        print(f"{name}:{n}:{col}  {rule}  {desc}")
    print(f"掃了 {len(files)} 個檔{'＋git 歷史' if a.history else ''} ｜ {note} ｜ 命中 {len(hits)}",
          file=sys.stderr)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
