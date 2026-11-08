"""Render transcript.json (real commands, real output) as a terminal GIF.

python render_gif.py transcript.json out.gif
Text is drawn verbatim from the transcript; only long lines are wrapped to the terminal width.
"""
import json, os, sys, textwrap
from PIL import Image, ImageDraw, ImageFont

W, ROWS, FS, LH, PADX, TOP = 900, 30, 14, 18, 14, 34
FONT = ImageFont.truetype(os.environ.get("RAK_DEMO_FONT", "consola.ttf"), FS)
FONTB = ImageFont.truetype(os.environ.get("RAK_DEMO_FONT_BOLD", os.environ.get("RAK_DEMO_FONT", "consolab.ttf")), FS)
CW = FONT.getlength("M")
COLS = int((W - 2 * PADX) // CW)
H = TOP + ROWS * LH + 12
BG, FG, DIM, GRN, RED, YEL, BAR = (22, 24, 29), (215, 218, 224), (120, 128, 140), (110, 200, 120), (240, 95, 90), (230, 190, 90), (40, 43, 50)
TITLE = "research-agent-kit  ·  the rules run in code, not in the prompt"


def color(line, kind):
    if kind == "cmd":
        return DIM if line.startswith("#") else FG
    if "blocked this call" in line or line.startswith(("FAIL", "GATE FAIL")) or "changed after freezing" in line:
        return RED
    if line.startswith("PASS") or line == "allowed" or line.startswith("frozen."):
        return GRN
    return FG


def wrap(text):
    return textwrap.wrap(text, COLS, break_long_words=True, replace_whitespace=False, drop_whitespace=False) or [""]


def draw(lines, cursor=False):
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, TOP - 10], fill=BAR)
    for i, c in enumerate([(240, 95, 90), (230, 190, 90), (110, 200, 120)]):
        d.ellipse([12 + i * 18, 8, 24 + i * 18, 20], fill=c)
    d.text((80, 7), TITLE, font=FONT, fill=DIM)
    view = lines[-ROWS:]
    for r, (txt, col, bold) in enumerate(view):
        y = TOP + r * LH
        if txt.startswith("$ ") and col != DIM:
            d.text((PADX, y), "$", font=FONTB, fill=GRN)
            d.text((PADX + 2 * CW, y), txt[2:], font=FONTB if bold else FONT, fill=col)
        else:
            d.text((PADX, y), txt, font=FONTB if bold else FONT, fill=col)
    if cursor and view:
        txt = view[-1][0]
        x = PADX + len(txt) * CW
        y = TOP + (len(view) - 1) * LH
        d.rectangle([x, y + 2, x + CW - 1, y + LH - 2], fill=FG)
    return im


def main():
    tr = json.load(open(sys.argv[1], encoding="utf-8"))
    frames, durs, lines = [], [], []

    def snap(ms, cursor=False):
        frames.append(draw(lines, cursor)); durs.append(ms)

    snap(600, True)
    for st in tr["steps"]:
        cmd_lines = st["cmd"].split("\n")
        is_comment = cmd_lines[0].startswith("#")
        for k, cl in enumerate(cmd_lines):
            full = cl if is_comment else ("$ " if k == 0 else "> ") + cl
            col = color(full, "cmd")
            for part in wrap(full):
                lines.append(["", col, False])
                step = 14 if is_comment else 9
                for n in range(step, len(part) + step, step):
                    lines[-1][0] = part[:n]
                    snap(28, True)
        snap(250 if is_comment else 350)
        out = [ln for ln in st["output"]]
        for ln in out:
            for part in wrap(ln):
                lines.append([part, color(ln, "out"), color(ln, "out") in (RED, GRN) and not ln.startswith("PASS")])
        if out:
            red = any(color(l, "out") == RED for l in out)
            snap(2600 if red else 1100)
    lines.append(["", FG, False])
    for t, c in [("# Every line above is real output: fresh clone of 1f6f391, no model, no API key, cost 0.", YEL),
                 ("# Only the gate values in step 3 are toy numbers typed for this demo.", YEL)]:
        lines.append([t, c, True])
    snap(5000)
    # small palette keeps the file small
    pal = [f.convert("P", palette=Image.ADAPTIVE, colors=16) for f in frames]
    pal[0].save(sys.argv[2], save_all=True, append_images=pal[1:], duration=durs, loop=0, optimize=True, disposal=1)
    print(len(frames), "frames", sum(durs) / 1000, "s", COLS, "cols", W, "x", H)


if __name__ == "__main__":
    main()
