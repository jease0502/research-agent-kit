"""Host-side steps for run.sh (Python, so the path logic is the same on Windows, macOS and Linux).

Two modes (README.md):

copy (default): the project never reaches the container. pack() copies the tracked and untracked-but-not-ignored
files into a tar, leaving out .git and every protected path; run.sh loads it into a fresh volume; the agent works
there; run.sh exports the volume; inspect() judges the change from the tar entries alone, never extracting them on the host;
run.sh then has git write the patch inside a container. A patch that touches a protected
path (any spelling: case, trailing dots or spaces, 8.3 short names), a symlink or a special file is refused whole.
Nothing on the host changes until the user reviews the patch and runs `git apply`. (Review of 1a90306: on NTFS,
/work/.GIT and /work/GIT~1 reach .git through a read-only overlay mounted at /work/.git.)

mount: the project is mounted read-write with read-only overlays (mounts()). Only on a case-sensitive filesystem
without 8.3 names (check_mount_fs(): Linux, a case-sensitive macOS volume, WSL2 ext4); refused on Windows paths and
whenever the check cannot tell. backup() before and restore() after: any change to a protected path is moved to a
quarantine folder and the original is put back, then reported (exit 3).

    python host.py check     PROJECT KIT AUDIT     # refuse unsafe folder choices; prints the three resolved paths
    python host.py pack      PROJECT TAR           # copy mode: the project, minus .git and protected paths
    python host.py inspect   BASE_TAR NEW_TAR OUT  # copy mode: OUT/summary.json; exit 3 refused, 4 changes, 0 none
    python host.py mountfs   PROJECT               # mount mode: refuse unless case-sensitive, no 8.3 names
    python host.py mounts    PROJECT EMPTY         # mount mode: -v arguments for the read-only overlays
    python host.py missing   PROJECT               # mount mode: overlay folders the project lacks
    python host.py cleanup   PROJECT LIST          # mount mode: remove those mount points if still empty
    python host.py backup    PROJECT DIR           # mount mode: copy protected files before the run
    python host.py restore   PROJECT DIR QUAR      # mount mode: after; quarantine and undo changes, exit 3 if any
"""
from __future__ import annotations

import filecmp
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import unicodedata
from pathlib import Path

def _load_policy_names():
    """The policy engine's P1 lists and name check (python/rak/policy/checks_policy.py), loaded from this kit by
    file, without importing the engine: L1 and L2 share one judgement of "is this a protected name" (maintainer, after
    the review of 2528365)."""
    import importlib.util
    path = Path(__file__).resolve().parents[2] / "python" / "rak" / "policy" / "checks_policy.py"
    spec = importlib.util.spec_from_file_location("rak_checks_policy_for_sandbox", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P1 = _load_policy_names()
# What can be mounted read-only over the project (mount mode): P1's folders and files without a wildcard.
# Everything else on P1 (plugins/*/hooks, ...) is still refused at any depth by protected().
RO_DIRS = tuple("/".join(d) for d in P1.PROTECTED_DIRS if "*" not in d)
RO_FILES = tuple(f[0] for f in P1.PROTECTED_FILES if len(f) == 1)
KIT_ONLY = ()                                   # one source now: nothing on P1 is left to the kit mount alone
# In .git, what can make the host run something; objects and logs cannot, and are large
GIT_SKIP = ("objects", "logs", "lfs")
SHORT_NAME = P1.SHORT_NAME


class Refused(Exception):
    pass


def norm(p: str | Path) -> str:
    return os.path.normcase(os.path.realpath(p))


def inside(child: str, parent: str) -> bool:
    return child == parent or child.startswith(parent.rstrip("\\/") + os.sep)


def host_path(p: str) -> str:
    return p.replace("\\", "/")


# ---- what counts as protected, in any spelling a host filesystem might resolve to the real name

def _invisible(ch: str) -> bool:
    """Default-ignorable code points: HFS+ ignores some of them in names, so '.g‌it' can be '.git' there."""
    o = ord(ch)
    return (unicodedata.category(ch) == "Cf" or 0xFE00 <= o <= 0xFE0F or 0xE0100 <= o <= 0xE01EF
            or o in (0x034F, 0x115F, 0x1160, 0x17B4, 0x17B5, 0x3164, 0xFFA0) or 0x180B <= o <= 0x180F)


def _canon(part: str) -> str:
    """The name as a case-insensitive, dot-dropping, normalizing filesystem might see it: Windows drops trailing
    dots and spaces and ignores case; macOS normalizes Unicode; HFS+ ignores invisible characters."""
    part = "".join(ch for ch in unicodedata.normalize("NFC", part) if not _invisible(ch))
    return part.rstrip(". ").casefold()


def protected(rel: str) -> str | None:
    """The protected entry `rel` (a project-relative path) falls under, at any depth and in any spelling, or None.
    The judgement is the policy engine's (checks_policy.protected_name: case, trailing dots and spaces, 8.3 short
    names, nested folders and files). Each component is first put in NFC and stripped of invisible characters,
    the two spellings macOS filesystems also fold together."""
    parts = [p for p in rel.replace("\\", "/").split("/") if p not in ("", ".")]
    cleaned = ["".join(ch for ch in unicodedata.normalize("NFC", p) if not _invisible(ch)) for p in parts]
    return P1.protected_name("/".join(cleaned))


# ---- folder choices

def check(project: str, kit: str, audit: str, home: str | None = None) -> tuple[str, str, str]:
    paths = {}
    for name, p in (("RAK_PROJECT", project), ("RAK_KIT", kit), ("RAK_AUDIT", audit)):
        if not p or not os.path.isdir(p):
            raise Refused(f"{name}={p!r} is not a folder")
        paths[name] = norm(p)
    pr, kt, au = paths["RAK_PROJECT"], paths["RAK_KIT"], paths["RAK_AUDIT"]
    home_n = norm(home or Path.home())
    if os.path.dirname(pr) == pr:
        raise Refused("RAK_PROJECT is a drive or filesystem root")
    if pr == home_n or inside(home_n, pr):
        raise Refused("RAK_PROJECT is your home folder or contains it")
    for a, b, why in ((kt, pr, "RAK_KIT must not be inside RAK_PROJECT (the agent could write the policy)"),
                      (pr, kt, "RAK_PROJECT must not be inside RAK_KIT (it is mounted read-only)"),
                      (au, pr, "RAK_AUDIT must be outside RAK_PROJECT"),
                      (pr, au, "RAK_PROJECT must not be inside RAK_AUDIT")):
        if inside(a, b):
            raise Refused(why)
    return pr, kt, au


# ---- copy mode

def project_files(project: str) -> list[str]:
    """Tracked plus untracked-but-not-ignored files (git), or every file (no git). Either list can name files
    reached through a link (Git for Windows walks into junctions); pack() checks where each one really is."""
    p = Path(project)
    if (p / ".git").exists():
        out = subprocess.run(["git", "-C", project, "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                             capture_output=True, check=True).stdout.decode("utf-8", "surrogateescape")
        return sorted({f for f in out.split("\0") if f})
    out = []
    for r, dirs, fs in os.walk(p):                 # links to folders are not followed, but listed so pack reports them
        linked = [d for d in dirs if _is_link(Path(r, d))]
        out += [Path(r, n).relative_to(p).as_posix() for n in fs + linked]
        dirs[:] = [d for d in dirs if d not in linked]
    return sorted(out)


def _is_link(p: Path) -> bool:
    """A symlink, or a Windows junction (Path.is_junction exists from Python 3.12; realpath works everywhere)."""
    return p.is_symlink() or bool(getattr(p, "is_junction", lambda: False)()) \
        or norm(p) != os.path.normcase(os.path.abspath(p))


def pack(project: str, tar_path: str) -> dict:
    """Only regular files whose real path is the path they are listed under, inside the project: nothing reached
    through a symlink or junction, at any level (review of 2528365: a junction to a folder outside was packed)."""
    left_out, skipped = [], []
    root = norm(project)
    with tarfile.open(tar_path, "w") as tf:
        for rel in project_files(project):
            src = Path(project, rel)
            if protected(rel):
                left_out.append(rel)
                continue
            real = norm(src)
            if (src.is_symlink() or not src.is_file() or not inside(real, root)
                    or real != os.path.normcase(os.path.join(root, *rel.split("/")))):
                skipped.append(rel)                 # a link (here or in a parent) could point anywhere on the host
                continue
            info = tf.gettarinfo(str(src), arcname=rel)
            info.uid = info.gid = 10001
            info.uname = info.gname = ""
            with open(src, "rb") as f:
                tf.addfile(info, f)
    return {"left_out_protected": left_out, "skipped_links_or_special": skipped}


WINDOWS_RESERVED = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(10)), *(f"lpt{i}" for i in range(10))}
WINDOWS_BAD = re.compile(r'[<>:"\\|?*\x00-\x1f]')
SMALL = 64 * 1024


def _members(tar_path: str) -> tuple[dict[str, tuple], dict[str, bytes], list[str]]:
    """name -> (kind, sha256, mode) for every entry, read from the tar only: never extracted on the host, whose
    filesystem may fold .GIT, .git. and GIT~1 into .git (review of 1a90306). Also the content of small files named
    config or HEAD, to recognise a git repository under another name."""
    import hashlib
    out, small, problems = {}, {}, []
    with tarfile.open(tar_path) as tf:
        for m in tf.getmembers():
            name = m.name[2:] if m.name.startswith("./") else m.name
            if name in ("", "."):
                continue
            if name.startswith("/") or ".." in name.split("/"):
                problems.append(f"{name}: path leaves the project")
                continue
            if m.isdir():
                out[name + "/"] = ("dir", "", m.mode & 0o777)
            elif m.isfile():
                data = tf.extractfile(m).read()
                out[name] = ("file", hashlib.sha256(data).hexdigest(), m.mode & 0o111)
                if _canon(name.rsplit("/", 1)[-1]) in ("config", "head") and len(data) <= SMALL:
                    small[name] = data
            else:
                out[name] = ("symlink" if m.issym() else "link or special file", m.linkname or "", 0)
    return out, small, problems


def name_problems(rel: str) -> list[str]:
    """Names that would land somewhere else, or nowhere, when the patch is applied on Windows or macOS."""
    out = []
    for part in rel.rstrip("/").split("/"):
        if part != part.rstrip(". "):
            out.append(f"{rel}: '{part}' ends in a dot or space (Windows drops it)")
        if part.split(".")[0].casefold() in WINDOWS_RESERVED:
            out.append(f"{rel}: '{part}' is a reserved name on Windows")
        if WINDOWS_BAD.search(part):
            out.append(f"{rel}: '{part}' has a character Windows does not allow")
        if any(_invisible(ch) for ch in part):
            out.append(f"{rel}: '{part.encode('unicode_escape').decode()}' has an invisible character "
                       "(HFS+ ignores some of them)")
    return out


def git_dirs(names: set[str], small: dict[str, bytes]) -> list[str]:
    """Folders that look like a git repository under another name (a bare repo: HEAD with objects/ and refs/, or a
    config with a [core] section). git would read its config when run there; safe.bareRepository=explicit is the
    host-side defence (review of 2528365)."""
    found = set()
    for n in names:
        folder, _, base = n.rstrip("/").rpartition("/")
        prefix = folder + "/" if folder else ""
        if _canon(base) == "head" and any(m.startswith(prefix + "objects/") for m in names) \
                and any(m.startswith(prefix + "refs/") for m in names):
            found.add(folder or ".")
        if _canon(base) == "config" and re.search(rb"^\s*\[\s*core\b", small.get(n, b""), re.I | re.M):
            found.add(folder or ".")
    return sorted(found)


def inspect(base_tar: str, new_tar: str, out: str) -> int:
    """Copy mode, after the run: 0 no changes, 4 changes that may be applied, 3 refused (summary.json says why).
    A refusal covers the whole run: nothing is written that could be applied."""
    outp = Path(out)
    outp.mkdir(parents=True, exist_ok=True)
    base, _, _ = _members(base_tar)
    new, small, problems = _members(new_tar)
    changed = sorted(k for k in set(base) | set(new) if base.get(k) != new.get(k) and not k.endswith("/"))
    changed_dirs = sorted(k for k in set(new) - set(base) if k.endswith("/"))
    for name in changed + changed_dirs:
        why = protected(name.rstrip("/"))
        if why:
            problems.append(f"{name}: under {why}")
        kind = new.get(name, ("removed",))[0]
        if kind not in ("file", "dir", "removed"):
            problems.append(f"{name}: a {kind}")
        problems += name_problems(name)
    new_small = {k: v for k, v in small.items() if k in changed}
    for d in git_dirs({k for k in changed + changed_dirs}, new_small):
        problems.append(f"{d}/: looks like a git repository (HEAD, objects/, refs/ or a [core] config)")
    folded: dict[str, str] = {}
    for name in new:
        key = _canon(name.rstrip("/"))         # case, Unicode normalization, invisible characters
        if key in folded and folded[key] != name.rstrip("/"):
            problems.append(f"{name}: differs from {folded[key]} only by case or Unicode form")
        folded.setdefault(key, name.rstrip("/"))
    summary = {"changed": changed, "new_folders": changed_dirs, "problems": sorted(set(problems))}
    (outp / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    if problems:
        print("SANDBOX: the agent's changes touch protected paths or names the host cannot hold faithfully; the "
              f"whole run is refused and nothing was written to apply. See {host_path(str(outp))}/summary.json:",
              file=sys.stderr)
        for p in summary["problems"]:
            print(f"  {p}", file=sys.stderr)
        return 3
    return 4 if changed else 0


# ---- mount mode

def check_mount_fs(project: str) -> None:
    """Refuse unless the project's filesystem is case-sensitive and has no 8.3 names. When in doubt, refuse."""
    pr = host_path(project)
    if os.name == "nt" and not pr.lower().startswith(("//wsl.localhost/", "//wsl$/")):
        raise Refused("mount mode needs a case-sensitive filesystem; on Windows put the project in WSL2 "
                      "(\\\\wsl.localhost\\<distro>\\...) or use the default copy mode")
    probe = Path(project, f".rak-case-probe-{secrets.token_hex(4)}")
    try:
        probe.write_text("x")
        twin = Path(project, probe.name.upper())
        insensitive = twin.exists()
    except OSError as e:
        raise Refused(f"cannot check the project's filesystem ({e}); use copy mode") from None
    finally:
        probe.unlink(missing_ok=True)
    if insensitive:
        raise Refused("the project's filesystem ignores case (/work/.GIT would reach .git); use copy mode, or a "
                      "case-sensitive volume")


def mounts(project: str, empty: str) -> list[str]:
    args = []
    for d in RO_DIRS:
        src = os.path.join(project, d)
        if os.path.islink(src):
            raise Refused(f"{d} in the project is a symlink; refusing to mount over it")
        args += ["-v", f"{host_path(src if os.path.isdir(src) else empty)}:/work/{d}:ro"]
    for f in sorted(os.listdir(project)):       # the files as they are spelled here (P1 keeps names in lower case)
        src = os.path.join(project, f)
        if os.path.isfile(src) and not os.path.islink(src) and protected(f):
            args += ["-v", f"{host_path(src)}:/work/{f}:ro"]
    return args


def missing(project: str) -> list[str]:
    """Overlay folders the project does not have, outermost first, including parents (scripts/ for scripts/hooks).
    Docker creates them as mount points; cleanup() removes the ones still empty."""
    out = []
    for d in RO_DIRS:
        parts = Path(d).parts
        for i in range(1, len(parts) + 1):
            sub = Path(*parts[:i]).as_posix()
            if not os.path.lexists(os.path.join(project, sub)) and sub not in out:
                out.append(sub)
    return out


def cleanup(project: str, created: list[str]) -> None:
    for d in reversed(created):
        try:
            os.rmdir(os.path.join(project, d))   # only if empty: anything left there stays, and is reported
        except OSError:
            pass


def watched(project: str) -> list[str]:
    """Every file or link at a protected path, at any depth and in any spelling (review of 2528365: nested
    sub/.claude/settings.json was not watched). Inside a git folder, objects, logs and lfs are skipped: they cannot
    make the host run anything, and they are large. Links are not followed."""
    root = Path(project)
    out = []
    for r, dirs, files in os.walk(root):
        rel_r = Path(r).relative_to(root).as_posix()
        if _canon(Path(r).name) == ".git":
            dirs[:] = [d for d in dirs if d not in GIT_SKIP]
        for n in files + [d for d in dirs if Path(r, d).is_symlink()]:
            rel = n if rel_r == "." else f"{rel_r}/{n}"
            if protected(rel):
                out.append(rel)
    return sorted(out)


def _link_file(p: Path) -> Path:
    return p.with_name(p.name + ".symlink")


def backup(project: str, store: str) -> None:
    for rel in watched(project):
        src, dst = Path(project, rel), Path(store, rel)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            _link_file(dst).write_text(os.readlink(src), encoding="utf-8")
        else:
            shutil.copy2(src, dst)
    Path(store, ".rak-index.json").write_text(json.dumps(watched(project)))


def restore(project: str, store: str, quarantine: str) -> list[str]:
    before = set(json.loads(Path(store, ".rak-index.json").read_text()))
    now = set(watched(project))
    changes = []
    for rel in sorted(before | now):
        cur, saved = Path(project, rel), Path(store, rel)
        saved_link = _link_file(saved)
        if rel in now and rel not in before:
            kind = "created"
        elif rel in before and rel not in now:
            kind = "removed"
        elif saved_link.exists():
            if cur.is_symlink() and os.readlink(cur) == saved_link.read_text(encoding="utf-8"):
                continue
            kind = "changed"
        elif cur.is_symlink() or not filecmp.cmp(cur, saved, shallow=False):
            kind = "changed"
        else:
            continue
        changes.append(f"{kind}: {rel}")
        if rel in now:
            q = Path(quarantine, rel)
            q.parent.mkdir(parents=True, exist_ok=True)
            if cur.is_symlink():
                _link_file(q).write_text(os.readlink(cur), encoding="utf-8")
                cur.unlink()
            else:
                shutil.move(str(cur), str(q))
        if rel in before:
            cur.parent.mkdir(parents=True, exist_ok=True)
            if saved_link.exists():
                os.symlink(saved_link.read_text(encoding="utf-8"), cur)
            elif saved.exists():
                shutil.copy2(saved, cur)
    return changes


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(newline="\n")      # run.sh reads lines with `read`/`mapfile`: no \r from Windows
    try:
        cmd = argv[0]
        if cmd == "check":
            print("\n".join(host_path(p) for p in check(*argv[1:4])))
        elif cmd == "pack":
            r = pack(argv[1], argv[2])
            if r["left_out_protected"] or r["skipped_links_or_special"]:
                print(f"SANDBOX: not copied in: {len(r['left_out_protected'])} protected, "
                      f"{len(r['skipped_links_or_special'])} links or special files", file=sys.stderr)
        elif cmd == "inspect":
            return inspect(argv[1], argv[2], argv[3])
        elif cmd == "mountfs":
            check_mount_fs(argv[1])
        elif cmd == "mounts":
            print("\n".join(mounts(argv[1], argv[2])))
        elif cmd == "missing":
            print("\n".join(missing(argv[1])))
        elif cmd == "cleanup":
            cleanup(argv[1], [x for x in Path(argv[2]).read_text(encoding="utf-8").splitlines() if x])
        elif cmd == "backup":
            backup(argv[1], argv[2])
        elif cmd == "restore":
            changes = restore(argv[1], argv[2], argv[3])
            if changes:
                print("SANDBOX WARNING: protected files changed during the run. They were moved to "
                      f"{host_path(argv[3])} and the originals put back:", file=sys.stderr)
                for c in changes:
                    print(f"  {c}", file=sys.stderr)
                return 3
        else:
            raise Refused(f"unknown command {cmd}")
    except Refused as e:
        print(f"run.sh: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
