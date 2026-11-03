"""Telegram bridge for Claude Code: one bot, one user, optionally one group. Standard library only.

This is the FALLBACK. Prefer the official Claude Code Channels Telegram plugin (see ../SKILL.md);
use this bridge only where Channels is not available.

Config lives in $TG_HOME (default ~/.config/claude-tg/), never in a repository:
    tg.env      TG_BOT_TOKEN=..., TG_CHAT_ID=... (written when the user sends the one-time pairing code),
                TG_PAIR_SHA256 / TG_PAIR_EXPIRES (the pending code's hash and expiry; removed once used),
                TG_GROUP_ID=... (written by the user's first message in a group)

Pairing: `setup` (or `pair`) prints a one-time code in the terminal. Only a private message containing that
code, before it expires, makes its sender the user; the code is then deleted. Messages from anyone else -
including someone who finds the bot first - are ignored, and nothing is recorded for them.
    tg.offset   getUpdates offset, so each message is delivered once
    tg_media/   photos / files / videos / voice received

Commands:
    python tg.py setup <BOT_TOKEN> [--ttl-min N] store the token, print a one-time pairing code (default 15 min)
    python tg.py pair [--ttl-min N]              new pairing code for the same bot (forgets the paired user and group)
    python tg.py wait                            long-poll until a message arrives, print it, exit (for a Monitor loop)
    python tg.py send "text"                     message the user (private chat)
    python tg.py send-group "text"               message the group
    python tg.py send-file PATH [caption] [--group]   send a photo / video / file (private by default)
    python tg.py check                           health check: offset, webhook, pairing, privacy mode
"""
import hashlib
import hmac
import json
import mimetypes
import os
import secrets
import sys
import time
import urllib.parse
import urllib.request

HOME = os.environ.get("TG_HOME") or os.path.join(os.path.expanduser("~"), ".config", "claude-tg")
ENV = os.path.join(HOME, "tg.env")
OFFSET = os.path.join(HOME, "tg.offset")
MEDIA = os.path.join(HOME, "tg_media")


def load_env():
    env = {}
    if os.path.exists(ENV):
        with open(ENV, encoding="utf-8") as f:
            for line in f:
                if "=" in line:
                    k, v = line.strip().split("=", 1)
                    env[k] = v
    if "TG_BOT_TOKEN" not in env:
        sys.exit(f"no TG_BOT_TOKEN; run: python tg.py setup <BOT_TOKEN> (config file {ENV})")
    return env


def save_env(env):
    os.makedirs(HOME, exist_ok=True)
    with open(ENV, "w", encoding="utf-8") as f:
        for k, v in env.items():
            f.write(f"{k}={v}\n")
    try:
        os.chmod(ENV, 0o600)
    except OSError:
        pass


def api(token, method, params=None, timeout=70):
    url = f"https://api.telegram.org/bot{token}/{method}"
    data = urllib.parse.urlencode(params or {}).encode()
    with urllib.request.urlopen(url, data=data, timeout=timeout) as r:
        return json.load(r)


def read_offset():
    if not os.path.exists(OFFSET):
        return 0
    raw = open(OFFSET, "rb").read().strip()
    try:
        return int(raw)
    except ValueError:
        # A corrupted offset (it has turned into a run of NUL bytes before) makes every wait fail, which
        # looks exactly like "no messages". Re-reading old messages is better than silently losing new ones.
        print(f"[tg.py] tg.offset corrupted ({raw[:16]!r}), reset to 0", file=sys.stderr)
        return 0


def save_media(tok, m):
    """Save a photo / file / video / voice / sticker to tg_media/ and return its path; None if no attachment."""
    if m.get("text"):
        return None
    if m.get("photo"):
        fid, name = m["photo"][-1]["file_id"], f"{m['message_id']}.jpg"
    elif m.get("document"):
        fid, name = m["document"]["file_id"], f"{m['message_id']}_{m['document'].get('file_name', 'file')}"
    else:
        for k, ext in (("video", ".mp4"), ("animation", ".mp4"), ("voice", ".ogg"), ("audio", ".mp3"),
                       ("video_note", ".mp4"), ("sticker", ".webp")):
            if m.get(k):
                fid, name = m[k]["file_id"], f"{m['message_id']}_{k}{ext}"
                break
        else:
            keys = [k for k in m if k not in ("message_id", "from", "chat", "date")]
            return f"not downloaded: {keys}"   # e.g. someone joined or left the group
    try:
        fp = api(tok, "getFile", {"file_id": fid})["result"]["file_path"]
        os.makedirs(MEDIA, exist_ok=True)
        out = os.path.join(MEDIA, os.path.basename(name))
        urllib.request.urlretrieve(f"https://api.telegram.org/file/bot{tok}/{fp}", out)
        return out
    except Exception as e:  # bots can only download files up to 20 MB
        return f"download failed: {e}"


CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   # no 0/O, 1/I: typed on a phone


def norm_code(s):
    return "".join(ch for ch in s.upper() if ch.isalnum())


def code_hash(code):
    return hashlib.sha256(norm_code(code).encode()).hexdigest()


def new_pairing(env, ttl_min=15, now=None):
    """Forget the paired user and group, store a fresh one-time code (hash + expiry), return the code."""
    raw = "".join(secrets.choice(CODE_ALPHABET) for _ in range(8))
    env.pop("TG_CHAT_ID", None)
    env.pop("TG_GROUP_ID", None)
    env["TG_PAIR_SHA256"] = code_hash(raw)
    env["TG_PAIR_EXPIRES"] = str(int((now or time.time()) + ttl_min * 60))
    return f"{raw[:4]}-{raw[4:]}"


def pairing_state(env, now=None):
    if "TG_CHAT_ID" in env:
        return "paired"
    if "TG_PAIR_SHA256" not in env:
        return "no code (run: tg.py pair)"
    return "waiting for the code" if (now or time.time()) < float(env.get("TG_PAIR_EXPIRES", 0)) else "code expired (run: tg.py pair)"


def try_pair(env, m, text, now=None):
    """Pair only on a private message carrying the unexpired one-time code. True if this message paired."""
    if "TG_CHAT_ID" in env or m["chat"].get("type") != "private" or "TG_PAIR_SHA256" not in env:
        return False
    if (now or time.time()) >= float(env.get("TG_PAIR_EXPIRES", 0)):
        return False
    if not hmac.compare_digest(code_hash(text), env["TG_PAIR_SHA256"]):
        return False
    env["TG_CHAT_ID"] = str(m["chat"]["id"])
    env.pop("TG_PAIR_SHA256", None)        # one-time: a code cannot pair anyone else afterwards
    env.pop("TG_PAIR_EXPIRES", None)
    return True


def collect(env, updates, now=None):
    """Turn getUpdates results into printable lines. Returns (lines, new offset or None, env changed)."""
    offset, lines, changed = None, [], False
    for u in updates:
        offset = u["update_id"] + 1
        m = u.get("message") or u.get("edited_message")
        if not m:
            continue
        chat = m["chat"]["id"]
        text = m.get("text") or m.get("caption") or "[non-text message]"
        if try_pair(env, m, text, now):
            changed = True
            lines.append((m, f"[paired] this chat ({chat}) is now the user"))
            continue
        if m["chat"].get("type") in ("group", "supergroup"):
            sender = m.get("from") or {}
            # the user's own first message in a group decides which group
            if "TG_GROUP_ID" not in env and str(sender.get("id")) == env.get("TG_CHAT_ID"):
                env["TG_GROUP_ID"] = str(chat)
                changed = True
            if str(chat) != env.get("TG_GROUP_ID"):
                continue
            who = sender.get("username") or sender.get("first_name") or "?"
            lines.append((m, f"[group] {who}: {text}"))
            continue
        if str(chat) != env.get("TG_CHAT_ID"):  # strangers are ignored
            continue
        lines.append((m, text))
    return lines, offset, changed


def wait():
    env = load_env()
    tok = env["TG_BOT_TOKEN"]
    offset = read_offset()
    while True:
        try:
            d = api(tok, "getUpdates", {"offset": offset, "timeout": 50})
        except Exception:
            # slow or broken network: wait and retry; exiting would look like "a message arrived"
            time.sleep(10)
            continue
        lines, new_offset, changed = collect(env, d.get("result", []))
        if changed:
            save_env(env)
        if new_offset is not None:
            offset = new_offset
            with open(OFFSET, "w") as f:
                f.write(str(offset))
        if lines:
            for m, text in lines:
                saved = save_media(tok, m)
                if saved:
                    text += f" [attachment {saved}]"
                print(time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(m.get("date", 0))), "|", text, flush=True)
            return


def send(text, key="TG_CHAT_ID"):
    env = load_env()
    if key not in env:
        sys.exit(f"{key} is not set (private: the user must message the bot first; group: the user must post "
                 f"in the group first)")
    d = api(env["TG_BOT_TOKEN"], "sendMessage", {"chat_id": env[key], "text": text[:4000]})
    print("ok" if d.get("ok") else d, d.get("result", {}).get("message_id"))


def send_file(path, caption="", key="TG_CHAT_ID"):
    env = load_env()
    if key not in env:
        sys.exit(f"{key} is not set")
    ext = os.path.splitext(path)[1].lower()
    method, field = ("sendVideo", "video") if ext in (".mp4", ".mov") else \
                    ("sendPhoto", "photo") if ext in (".png", ".jpg", ".jpeg") else ("sendDocument", "document")
    boundary = "----claudetg"
    parts = []
    for k, v in (("chat_id", env[key]), ("caption", caption[:1000])):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    with open(path, "rb") as f:
        blob = f.read()
    ctype = mimetypes.guess_type(path)[0] or "application/octet-stream"
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{field}"; filename="{os.path.basename(path)}"\r\n'
                 f"Content-Type: {ctype}\r\n\r\n".encode() + blob + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(f"https://api.telegram.org/bot{env['TG_BOT_TOKEN']}/{method}", data=b"".join(parts),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.load(r)
    print("ok" if d.get("ok") else d, d.get("result", {}).get("message_id"))


def check():
    env = load_env()
    tok = env["TG_BOT_TOKEN"]
    me = api(tok, "getMe").get("result", {})
    hook = api(tok, "getWebhookInfo").get("result", {})
    raw = open(OFFSET, "rb").read().strip() if os.path.exists(OFFSET) else b"(none)"
    print("bot              :", "@" + str(me.get("username")))
    print("reads all group  :", me.get("can_read_all_group_messages"),
          "(False = privacy mode on: ordinary group messages are not delivered)")
    print("pairing          :", pairing_state(env))
    print("TG_CHAT_ID       :", env.get("TG_CHAT_ID", "not paired (the user sends the bot the code from `tg.py pair`)"))
    print("TG_GROUP_ID      :", env.get("TG_GROUP_ID", "not set"))
    print("tg.offset        :", raw[:20], "OK" if raw.isdigit() or raw == b"(none)" else "<- CORRUPTED")
    print("webhook          :", hook.get("url") or "(none)", "| pending updates", hook.get("pending_update_count"))
    if hook.get("url"):
        print("  ! getUpdates does not work while a webhook is set; call deleteWebhook first")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd in ("setup", "pair"):
        ttl = float(args[args.index("--ttl-min") + 1]) if "--ttl-min" in args else 15
        rest = [a for i, a in enumerate(args) if a != "--ttl-min" and (i == 0 or args[i - 1] != "--ttl-min")]
        if cmd == "setup":
            if not rest:
                sys.exit("usage: tg.py setup <BOT_TOKEN> [--ttl-min N]")
            env = {}
            if os.path.exists(ENV):
                with open(ENV, encoding="utf-8") as f:
                    env = dict(l.strip().split("=", 1) for l in f if "=" in l)
            env["TG_BOT_TOKEN"] = rest[0]
        else:
            env = load_env()
        code = new_pairing(env, ttl)   # a new token or a re-pair forgets the old user and group
        save_env(env)
        print("written to", ENV)
        print(f"PAIRING CODE: {code}   (valid {ttl:g} min, one use)")
        print("Send exactly this code to the bot in a private chat, from the account that should be the user.")
        print("Then run: python tg.py wait   (it prints '[paired] ...' when the code arrives)")
    elif cmd == "wait":
        wait()
    elif cmd == "send":
        send(args[0])
    elif cmd == "send-group":
        send(args[0], "TG_GROUP_ID")
    elif cmd == "send-file":
        group = "--group" in args
        rest = [a for a in args if a != "--group"]
        send_file(rest[0], rest[1] if len(rest) > 1 else "", "TG_GROUP_ID" if group else "TG_CHAT_ID")
    elif cmd == "check":
        check()
    else:
        sys.exit(__doc__)
