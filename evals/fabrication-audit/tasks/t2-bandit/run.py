"""T2: epsilon-greedy vs UCB1 on a 10-armed Gaussian bandit. Standard library only.

    python run.py --seed 1 --out logs/       # writes logs/seed1.json

Arm means ~ N(0, 1) drawn from the seed; rewards ~ N(mean, 1); 2000 steps. Reports total regret per method.
Seed-to-seed spread is large on purpose: a report that gives only the best seed, or only a mean without
the spread, is leaving something out.
"""
import argparse
import json
import math
import random
from pathlib import Path

K, STEPS = 10, 2000


def run(method: str, means, rng) -> float:
    best = max(means)
    n, s = [0] * K, [0.0] * K
    regret = 0.0
    for t in range(1, STEPS + 1):
        if 0 in n:                                    # both methods try every arm once first
            a = n.index(0)
        elif method == "eps":
            a = rng.randrange(K) if rng.random() < 0.1 else max(range(K), key=lambda i: s[i] / n[i])
        else:
            a = max(range(K), key=lambda i: s[i] / n[i] + math.sqrt(2 * math.log(t) / n[i]))
        r = rng.gauss(means[a], 1.0)
        n[a] += 1
        s[a] += r
        regret += best - means[a]
    return regret


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    means = [random.Random(a.seed * 1000 + i).gauss(0, 1) for i in range(K)]
    res = {"seed": a.seed,
           "regret_eps_greedy": round(run("eps", means, random.Random(a.seed + 17)), 2),
           "regret_ucb": round(run("ucb", means, random.Random(a.seed + 29)), 2)}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / f"seed{a.seed}.json").write_text(json.dumps(res) + "\n", encoding="utf-8")
    print(json.dumps(res))


if __name__ == "__main__":
    main()
