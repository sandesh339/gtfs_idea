"""Generate publication-quality result figures from results_mbta.jsonl.

Six figures (PNG + PDF) into figures/, matching the deck/dashboard palette:
  fig1  pass-rate by model tier x mechanism
  fig2  pass-rate by scenario group x mechanism
  fig3  outcome composition by mechanism (stacked)
  fig4  Group F clarify behaviour (refrained vs acted)
  fig5  mean tool calls by group x mechanism
  fig6  trial stability (cells by passes-of-3)
plus fig0_grid, a 2x3 panel of all six.

Usage:  python make_figures.py [--in results_mbta.jsonl] [--dpi 200]
"""
import argparse
import json
import os
from collections import Counter, defaultdict

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

# --- validated palette (light) ---------------------------------------------
FC, CG = "#2D6BF0", "#D97A1E"
OUT_COLORS = {"pass": "#008300", "refrained": "#2a78d6", "no_change": "#1baf7a",
              "invalid": "#eda100", "incomplete": "#e87ba4", "error": "#4a3aa7", "acted": "#e34948"}
OUT_ORDER = ["pass", "refrained", "no_change", "invalid", "incomplete", "error", "acted"]
INK, INK2, GRID = "#10192B", "#4A566B", "#E6E9EF"

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 11,
    "axes.edgecolor": INK2, "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": INK2, "ytick.color": INK2,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "axes.axisbelow": True,
    "grid.color": GRID, "grid.linewidth": 1,
    "figure.facecolor": "white", "axes.facecolor": "white",
    "savefig.facecolor": "white",
})


def load(path):
    rows = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
    for r in rows:
        r["passed"] = bool(r.get("passed"))
    return rows


def prate(rows, **f):
    sub = [r for r in rows if all(r.get(k) == v for k, v in f.items())]
    return 100 * sum(x["passed"] for x in sub) / len(sub) if sub else 0.0


def _mech(m):
    return "codegen" if m == "CG" else "fc"


def _grouped(ax, cats, fc_vals, cg_vals, ylabel, ymax, fmt="{:.0f}", pct=False):
    import numpy as np
    x = np.arange(len(cats)); w = 0.38
    b1 = ax.bar(x - w/2, fc_vals, w, color=FC, label="Function calling", zorder=3)
    b2 = ax.bar(x + w/2, cg_vals, w, color=CG, label="Code generation", zorder=3)
    for bars, vals in ((b1, fc_vals), (b2, cg_vals)):
        for rect, v in zip(bars, vals):
            ax.text(rect.get_x()+rect.get_width()/2, v + ymax*0.015, fmt.format(v),
                    ha="center", va="bottom", fontsize=9, color=INK, fontweight="600")
    ax.set_xticks(x); ax.set_xticklabels(cats)
    ax.set_ylabel(ylabel); ax.set_ylim(0, ymax)
    ax.grid(axis="x", visible=False)
    if pct:
        from matplotlib.ticker import PercentFormatter
        ax.yaxis.set_major_formatter(PercentFormatter(xmax=100))
    ax.legend(frameon=False, fontsize=9, loc="upper left", ncol=2)


def _stacked(ax, rows_labels, data_by_row, segs, seg_colors, total, seg_names=None):
    """Horizontal stacked bars, one per row label."""
    y = range(len(rows_labels))
    for i, lab in enumerate(rows_labels):
        left = 0
        for s in segs:
            v = data_by_row[lab].get(s, 0)
            if v <= 0:
                left += 0; continue
            ax.barh(i, v, left=left, color=seg_colors[s], height=0.6, zorder=3,
                    edgecolor="white", linewidth=1.2)
            if v / total > 0.05:
                ax.text(left + v/2, i, str(v), ha="center", va="center",
                        color="white", fontsize=9, fontweight="700")
            left += v
    ax.set_yticks(list(y)); ax.set_yticklabels(rows_labels)
    ax.set_xlim(0, total); ax.invert_yaxis()
    ax.grid(axis="y", visible=False)
    ax.set_xlabel(f"runs (of {total})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="results_mbta.jsonl")
    ap.add_argument("--dpi", type=int, default=200)
    args = ap.parse_args()
    rows = load(args.inp)
    os.makedirs("figures", exist_ok=True)

    tiers = ["nano", "mini", "gpt5"]
    groups = list("ABCDEF")
    eg = list("ABCDE")

    def save(fig, name):
        fig.tight_layout()
        fig.savefig(f"figures/{name}.png", dpi=args.dpi, bbox_inches="tight")
        fig.savefig(f"figures/{name}.pdf", bbox_inches="tight")
        plt.close(fig)

    # fig1 - tier x mechanism
    fig, ax = plt.subplots(figsize=(6.2, 4))
    _grouped(ax, tiers, [prate(rows, tier=t, mechanism="fc") for t in tiers],
             [prate(rows, tier=t, mechanism="codegen") for t in tiers],
             "pass-rate", 100, pct=True)
    ax.set_title("Pass-rate by model size and mechanism", fontweight="700", color=INK, loc="left")
    save(fig, "fig1_tier")

    # fig2 - group x mechanism
    fig, ax = plt.subplots(figsize=(7.2, 4))
    _grouped(ax, groups, [prate(rows, group=g, mechanism="fc") for g in groups],
             [prate(rows, group=g, mechanism="codegen") for g in groups],
             "pass-rate", 100, pct=True)
    ax.set_title("Pass-rate by scenario group  (F: 'pass' = correctly refrained)",
                 fontweight="700", color=INK, loc="left")
    save(fig, "fig2_group")

    # fig3 - outcome composition
    obm = {m: Counter(r.get("outcome") for r in rows if r["mechanism"] == _mech(m)) for m in ["FC", "CG"]}
    fig, ax = plt.subplots(figsize=(8.4, 3.1))
    _stacked(ax, ["FC", "CG"], {"FC": obm["FC"], "CG": obm["CG"]}, OUT_ORDER, OUT_COLORS, 351)
    ax.legend(handles=[Patch(color=OUT_COLORS[o], label=o) for o in OUT_ORDER],
              frameon=False, fontsize=9, ncol=7, loc="upper center", bbox_to_anchor=(0.5, -0.22))
    ax.set_title("How the two mechanisms fail differently  (351 runs each)",
                 fontweight="700", color=INK, loc="left")
    save(fig, "fig3_outcomes")

    # fig4 - Group F
    fdata = {m: Counter(r.get("outcome") for r in rows if r["group"] == "F" and r["mechanism"] == _mech(m))
             for m in ["FC", "CG"]}
    fig, ax = plt.subplots(figsize=(7.2, 2.5))
    _stacked(ax, ["FC", "CG"], fdata, ["refrained", "acted"],
             {"refrained": OUT_COLORS["refrained"], "acted": OUT_COLORS["acted"]}, 54)
    ax.legend(handles=[Patch(color=OUT_COLORS["refrained"], label="refrained (correct)"),
                       Patch(color=OUT_COLORS["acted"], label="acted (wrong)")],
              frameon=False, fontsize=9, ncol=2, loc="upper center", bbox_to_anchor=(0.5, -0.28))
    ax.set_title("Behaviour on under-specified requests (Group F)",
                 fontweight="700", color=INK, loc="left")
    save(fig, "fig4_clarify")

    # fig5 - mean calls
    import statistics
    def mc(g, m):
        v = [r["calls"] for r in rows if r["group"] == g and r["mechanism"] == m and r.get("calls") is not None]
        return statistics.mean(v) if v else 0
    fig, ax = plt.subplots(figsize=(6.8, 4))
    _grouped(ax, eg, [mc(g, "fc") for g in eg], [mc(g, "codegen") for g in eg],
             "mean tool calls", 20, fmt="{:.1f}")
    ax.set_title("Cost — mean tool calls per edit", fontweight="700", color=INK, loc="left")
    save(fig, "fig5_cost")

    # fig6 - stability
    cells = defaultdict(list)
    for r in rows:
        cells[(r["tier"], r["mechanism"], r["scenario"])].append(r["passed"])
    dist = Counter(sum(v) for v in cells.values() if len(v) == 3)
    labs = ["0 / 3", "1 / 3", "2 / 3", "3 / 3"]
    vals = [dist.get(k, 0) for k in range(4)]
    cols = [OUT_COLORS["acted"], OUT_COLORS["invalid"], OUT_COLORS["invalid"], OUT_COLORS["pass"]]
    fig, ax = plt.subplots(figsize=(6.2, 4))
    bars = ax.bar(labs, vals, color=cols, width=0.6, zorder=3)
    for rect, v in zip(bars, vals):
        ax.text(rect.get_x()+rect.get_width()/2, v+2, str(v), ha="center", va="bottom",
                fontsize=10, fontweight="700", color=INK)
    ax.set_ylabel("cells"); ax.set_ylim(0, max(vals)*1.15); ax.grid(axis="x", visible=False)
    ax.set_title("Trial stability — of 234 cells, passes across 3 trials",
                 fontweight="700", color=INK, loc="left")
    ax.legend(handles=[Patch(color=OUT_COLORS["acted"], label="always fails"),
                       Patch(color=OUT_COLORS["invalid"], label="flaky (1-2/3)"),
                       Patch(color=OUT_COLORS["pass"], label="always passes")],
              frameon=False, fontsize=9, loc="upper center")
    save(fig, "fig6_stability")

    print("wrote figures/: fig1_tier, fig2_group, fig3_outcomes, fig4_clarify, fig5_cost, fig6_stability  (png + pdf)")


if __name__ == "__main__":
    main()
