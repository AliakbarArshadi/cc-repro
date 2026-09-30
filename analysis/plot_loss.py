"""Plot goodput vs. loss rate from results/loss_sweep and write a summary CSV.

    python3 analysis/plot_loss.py
"""

import csv
import glob
import json
import os
import re
from collections import defaultdict
from statistics import median

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RES = os.path.join(ROOT, "results", "loss_sweep")
FIG = os.path.join(ROOT, "figures")
COLORS = {"bbr": "#1f77b4", "cubic": "#d62728", "reno": "#7f7f7f"}


def load():
    data = defaultdict(lambda: defaultdict(list))   # cc -> loss -> [goodput]
    for d in glob.glob(os.path.join(RES, "*_loss*_run*")):
        m = re.match(r"(\w+)_loss([\d.]+)_run\d+$", os.path.basename(d))
        rx = os.path.join(d, "rx.json")
        if m and os.path.exists(rx):
            data[m[1]][float(m[2])].append(json.load(open(rx))["goodput_mbit"])
    return data


def main() -> None:
    data = load()
    os.makedirs(FIG, exist_ok=True)
    rows = []
    fig, ax = plt.subplots(figsize=(6.4, 4))
    for cc in sorted(data):
        xs = sorted(data[cc])
        med = [median(data[cc][x]) for x in xs]
        lo = [m - min(data[cc][x]) for x, m in zip(xs, med)]
        hi = [max(data[cc][x]) - m for x, m in zip(xs, med)]
        ax.errorbar(xs, med, yerr=[lo, hi], marker="o", ms=4, capsize=3,
                    label=cc.upper() if cc == "bbr" else cc.capitalize(), color=COLORS.get(cc))
        rows += [(cc, x, len(data[cc][x]), round(m, 2), round(min(data[cc][x]), 2), round(max(data[cc][x]), 2))
                 for x, m in zip(xs, med)]
    # Mathis et al. (1997) steady-state model for Reno: MSS/RTT * C/sqrt(p), C = sqrt(3/2).
    # Capped at the link rate; it is only meant to hold for small p.
    ps = [10 ** (e / 10) for e in range(-30, 18)]   # percent, 0.001 .. 50
    mathis = [min(96.5, 1448 * 8 / 0.1 * (1.5 ** 0.5) / (p / 100) ** 0.5 / 1e6) for p in ps]
    ax.plot(ps, mathis, "k--", lw=1, label="Mathis model (Reno)")
    ax.set_xscale("log")
    ax.set_xlabel("Random loss rate (%)")
    ax.set_ylabel("Goodput (Mbit/s)")
    ax.set_title("One flow, 100 Mbit/s bottleneck, 100 ms RTT, 1 BDP buffer")
    ax.set_ylim(bottom=0)
    ax.grid(True, which="both", alpha=0.3)
    ax.legend()
    fig.tight_layout()
    fig.savefig(os.path.join(FIG, "loss_sweep.png"), dpi=150)
    fig.savefig(os.path.join(FIG, "loss_sweep.pdf"))
    with open(os.path.join(RES, "summary.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cc", "loss_pct", "runs", "median_mbit", "min_mbit", "max_mbit"])
        w.writerows(rows)
    print(f"wrote {FIG}/loss_sweep.png and {RES}/summary.csv")


if __name__ == "__main__":
    main()
