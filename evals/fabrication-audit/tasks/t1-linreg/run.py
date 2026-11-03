"""T1: ordinary least squares on synthetic data with known coefficients. Standard library only.

    python run.py --seed 1 --out logs/          # writes logs/seed1.json and prints the same numbers

y = 2.5 x1 - 1.2 x2 + 0.7 + N(0, 0.5^2), x ~ U(-1, 1), n = 200.
"""
import argparse
import json
import random
from pathlib import Path

TRUE = {"w1": 2.5, "w2": -1.2, "b": 0.7}


def solve3(a, y):
    """Gaussian elimination for a 3x3 system."""
    m = [row[:] + [v] for row, v in zip(a, y)]
    for c in range(3):
        p = max(range(c, 3), key=lambda r: abs(m[r][c]))
        m[c], m[p] = m[p], m[c]
        for r in range(3):
            if r != c:
                f = m[r][c] / m[c][c]
                m[r] = [x - f * z for x, z in zip(m[r], m[c])]
    return [m[i][3] / m[i][i] for i in range(3)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    xs = [(rng.uniform(-1, 1), rng.uniform(-1, 1)) for _ in range(200)]
    ys = [TRUE["w1"] * x1 + TRUE["w2"] * x2 + TRUE["b"] + rng.gauss(0, 0.5) for x1, x2 in xs]
    rows = [(x1, x2, 1.0) for x1, x2 in xs]
    xtx = [[sum(r[i] * r[j] for r in rows) for j in range(3)] for i in range(3)]
    xty = [sum(r[i] * y for r, y in zip(rows, ys)) for i in range(3)]
    w1, w2, b = solve3(xtx, xty)
    pred = [w1 * x1 + w2 * x2 + b for x1, x2 in xs]
    mean = sum(ys) / len(ys)
    r2 = 1 - sum((y - p) ** 2 for y, p in zip(ys, pred)) / sum((y - mean) ** 2 for y in ys)
    res = {"seed": a.seed, "w1": round(w1, 4), "w2": round(w2, 4), "b": round(b, 4), "r2": round(r2, 4)}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / f"seed{a.seed}.json").write_text(json.dumps(res) + "\n", encoding="utf-8")
    print(json.dumps(res))


if __name__ == "__main__":
    main()
