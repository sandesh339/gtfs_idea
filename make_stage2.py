"""Stage-2 (correctness) figures from results_mbta.jsonl.

  fig8_stage_gap   valid (Stage-1) vs correct (Stage-2) pass-rate, per mechanism
  fig9_valid_wrong valid-but-WRONG rate by group x mechanism
                   (passed Stage-1 but failed the correctness oracle)

Usage:  python make_stage2.py [--in results_mbta.jsonl] [--dpi 200]
"""
import argparse
import json
import numpy as np

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter

FC, CG = "#2D6BF0", "#D97A1E"
INK, INK2, GRID = "#10192B", "#4A566B", "#E6E9EF"
plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11,
    "axes.edgecolor": INK2, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.axisbelow": True, "grid.color": GRID, "grid.linewidth": 1,
    "figure.facecolor": "white", "axes.facecolor": "white", "savefig.facecolor": "white",
})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="results_mbta.jsonl")
    ap.add_argument("--dpi", type=int, default=200)
    args = ap.parse_args()
    rows = [json.loads(l) for l in open(args.inp, encoding="utf-8") if l.strip()]

    def pct(sub, key):
        return 100 * sum(bool(r.get(key)) for r in sub) / len(sub) if sub else 0

    def sub(**f):
        return [r for r in rows if all(r.get(k) == v for k, v in f.items())]

    # ---- fig8: valid vs correct per mechanism ----
    mechs = [("Function calling", "fc", FC), ("Code generation", "codegen", CG)]
    fig, ax = plt.subplots(figsize=(6.6, 4.2))
    x = np.arange(len(mechs)); w = 0.38
    for i, (name, m, c) in enumerate(mechs):
        s = sub(mechanism=m)
        v1, v2 = pct(s, "passed"), pct(s, "passed2")
        b1 = ax.bar(x[i] - w/2, v1, w, color=c, alpha=0.42, zorder=3)
        b2 = ax.bar(x[i] + w/2, v2, w, color=c, zorder=3)
        for rect, v in ((b1[0], v1), (b2[0], v2)):
            ax.text(rect.get_x()+rect.get_width()/2, v + 1.5, f"{v:.0f}%", ha="center",
                    va="bottom", fontsize=10, fontweight="700", color=INK)
    ax.set_xticks(x); ax.set_xticklabels([m[0] for m in mechs])
    ax.set_ylim(0, 100); ax.yaxis.set_major_formatter(PercentFormatter(xmax=100))
    ax.set_ylabel("pass-rate"); ax.grid(axis="x", visible=False)
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(facecolor="#888", alpha=0.42, label="valid (Stage 1)"),
                       Patch(facecolor="#888", label="correct (Stage 2)")],
              frameon=False, fontsize=10, loc="upper right")
    ax.set_title("Valid change vs. CORRECT change", fontweight="700", color=INK, loc="left")
    fig.tight_layout()
    fig.savefig("figures/fig8_stage_gap.png", dpi=args.dpi, bbox_inches="tight")
    fig.savefig("figures/fig8_stage_gap.pdf", bbox_inches="tight")
    plt.close(fig)

    # ---- fig9: valid-but-wrong rate by group x mechanism ----
    groups = list("ABCDEF")
    def vw(g, m):
        s = sub(group=g, mechanism=m)
        return 100 * sum(1 for r in s if r.get("passed") and not r.get("correct")) / len(s) if s else 0
    fig, ax = plt.subplots(figsize=(7.4, 4.2))
    x = np.arange(len(groups)); w = 0.38
    fcv = [vw(g, "fc") for g in groups]; cgv = [vw(g, "codegen") for g in groups]
    ax.bar(x - w/2, fcv, w, color=FC, zorder=3, label="Function calling")
    ax.bar(x + w/2, cgv, w, color=CG, zorder=3, label="Code generation")
    for xi, v in zip(x - w/2, fcv):
        if v > 0: ax.text(xi, v + 0.6, f"{v:.0f}", ha="center", va="bottom", fontsize=9, color=INK)
    for xi, v in zip(x + w/2, cgv):
        if v > 0: ax.text(xi, v + 0.6, f"{v:.0f}", ha="center", va="bottom", fontsize=9, color=INK)
    ax.set_xticks(x); ax.set_xticklabels(groups)
    ax.set_ylabel("valid-but-wrong  (% of runs)"); ax.grid(axis="x", visible=False)
    ax.set_ylim(0, max(fcv + cgv + [5]) * 1.2)
    ax.legend(frameon=False, fontsize=10, loc="upper left")
    ax.set_title("Where a mechanism produced a VALID but WRONG feed", fontweight="700", color=INK, loc="left")
    fig.tight_layout()
    fig.savefig("figures/fig9_valid_wrong.png", dpi=args.dpi, bbox_inches="tight")
    fig.savefig("figures/fig9_valid_wrong.pdf", bbox_inches="tight")
    plt.close(fig)

    print("wrote figures/fig8_stage_gap + fig9_valid_wrong  (png + pdf)")


if __name__ == "__main__":
    main()
