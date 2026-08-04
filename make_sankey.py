"""Sankey figure: every run flows mechanism -> outcome -> verdict.

Reads results_mbta.jsonl, writes figures/fig7_sankey.png + .pdf.
Hand-drawn with bezier ribbons so it needs no extra deps and matches the palette.

Usage:  python make_sankey.py [--in results_mbta.jsonl] [--dpi 200]
"""
import argparse
import json
import os
from collections import Counter

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.path import Path
from matplotlib.patches import PathPatch, Rectangle

FC, CG = "#2D6BF0", "#D97A1E"
OUT_COLORS = {"pass": "#008300", "refrained": "#2a78d6", "no_change": "#1baf7a",
              "invalid": "#eda100", "incomplete": "#e87ba4", "error": "#4a3aa7", "acted": "#e34948"}
ORDER = ["pass", "refrained", "no_change", "invalid", "incomplete", "error", "acted"]
INK, INK2 = "#10192B", "#4A566B"


def ribbon(ax, x0, x1, sy, ty, th, color):
    mx = (x0 + x1) / 2
    verts = [(x0, sy), (mx, sy), (mx, ty), (x1, ty), (x1, ty + th),
             (mx, ty + th), (mx, sy + th), (x0, sy + th), (x0, sy)]
    codes = [Path.MOVETO, Path.CURVE4, Path.CURVE4, Path.CURVE4, Path.LINETO,
             Path.CURVE4, Path.CURVE4, Path.CURVE4, Path.CLOSEPOLY]
    ax.add_patch(PathPatch(Path(verts, codes), facecolor=color, edgecolor="none", alpha=0.45))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", default="results_mbta.jsonl")
    ap.add_argument("--dpi", type=int, default=200)
    args = ap.parse_args()
    rows = [json.loads(l) for l in open(args.inp, encoding="utf-8") if l.strip()]
    fc = Counter(r["outcome"] for r in rows if r["mechanism"] == "fc")
    cg = Counter(r["outcome"] for r in rows if r["mechanism"] == "codegen")
    V = len(rows)

    W, H, nw, padT, padB, g = 920, 470, 15.0, 30, 16, 12
    Hplot = H - padT - padB
    s = (Hplot - (len(ORDER) - 1) * g) / V   # tallest column = the outcomes
    xM, xO, xV = 70.0, (W - nw) / 2, W - 70.0 - nw

    passTot = fc["pass"] + cg["pass"] + fc["refrained"] + cg["refrained"]
    mech = [{"id": "FC", "val": sum(fc.values()), "c": FC},
            {"id": "CG", "val": sum(cg.values()), "c": CG}]
    out = [{"id": o, "val": fc[o] + cg[o], "c": OUT_COLORS[o]} for o in ORDER]
    ver = [{"id": "Pass", "val": passTot, "c": OUT_COLORS["pass"]},
           {"id": "Fail", "val": V - passTot, "c": OUT_COLORS["acted"]}]

    def lay(ns, x):
        ch = sum(n["val"] * s for n in ns) + (len(ns) - 1) * g
        y = padT + (Hplot - ch) / 2
        for n in ns:
            n.update(x=x, h=n["val"] * s, y=y, inO=0.0, outO=0.0); y += n["h"] + g
    lay(mech, xM); lay(out, xO); lay(ver, xV)
    byid = {n["id"]: n for n in out}

    fig, ax = plt.subplots(figsize=(11, 5.3))
    fig.patch.set_facecolor("white"); ax.set_facecolor("white")

    def flow(src, tgt, val, color):
        th = val * s
        ribbon(ax, src["x"] + nw, tgt["x"], src["y"] + src["outO"], tgt["y"] + tgt["inO"], th, color)
        src["outO"] += th; tgt["inO"] += th

    for m in mech:
        src = fc if m["id"] == "FC" else cg
        for o in ORDER:
            if src[o] > 0:
                flow(m, byid[o], src[o], OUT_COLORS[o])
    for o in out:
        tgt = ver[0] if o["id"] in ("pass", "refrained") else ver[1]
        flow(o, tgt, o["val"], o["c"])

    for n in mech + out + ver:
        ax.add_patch(Rectangle((n["x"], n["y"]), nw, max(n["h"], 1), facecolor=n["c"],
                               edgecolor="none", zorder=5))
    for n in mech:
        ax.text(n["x"] - 8, n["y"] + n["h"] / 2, f'{n["id"]}  {n["val"]}', ha="right",
                va="center", fontsize=11, fontweight="700", color=INK)
    for n in ver:
        ax.text(n["x"] + nw + 8, n["y"] + n["h"] / 2, f'{n["id"]}  {n["val"]}', ha="left",
                va="center", fontsize=11, fontweight="700", color=INK)
    for n in out:
        if n["h"] > 26:
            ax.text(n["x"] + nw / 2, n["y"] + n["h"] / 2, str(n["val"]), ha="center",
                    va="center", color="white", fontsize=9, fontweight="700", zorder=6)
        # name to the side of the middle column, alternating to avoid overlap
        ax.text(n["x"] + nw + 6, n["y"] + n["h"] / 2, n["id"], ha="left", va="center",
                fontsize=8.5, color=INK2) if n["h"] <= 26 else None
    for t, x in (("MECHANISM", xM), ("OUTCOME", xO), ("VERDICT", xV)):
        ax.text(x + nw / 2, padT - 12, t, ha="center", fontsize=9, color=INK2,
                fontweight="700", family="monospace")
    ax.text(0, 6, "Every run flows: mechanism → outcome → verdict  (702 runs, ribbon width = runs)",
            fontsize=12, fontweight="700", color=INK)

    ax.set_xlim(0, W); ax.set_ylim(H, 0); ax.axis("off")
    os.makedirs("figures", exist_ok=True)
    fig.tight_layout()
    fig.savefig("figures/fig7_sankey.png", dpi=args.dpi, bbox_inches="tight")
    fig.savefig("figures/fig7_sankey.pdf", bbox_inches="tight")
    plt.close(fig)
    print("wrote figures/fig7_sankey.png + .pdf")


if __name__ == "__main__":
    main()
