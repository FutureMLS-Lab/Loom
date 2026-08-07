"""A worked replicate figure, for AAAI-27 paper 45776. Run it to see the output.

The claim is that Lazy-FFT's cost per centre stays bounded as k grows. The
paper's own figure plots the mean of each cell, and two things live only in the
spread: the HST families are deterministic, all twelve of their runs identical,
and the cost does not sit flat but climbs and saturates.

a is the aggregate with every run behind it; b is the same quantity at the
largest k with each replicate drawn, a dashed line at the published 2k, and
another at the mean over the families the theorem actually covers. The two
families with unbounded doubling dimension are marked, because nothing is
proved for them and the mean-only figure gave all seven equal standing.

Data: the paper's own doubling sweep, re-run with the same seed and generator
order so the stream is identical, keeping the individual query counts. See the
SKILL.md section on getting the replicates out of an experiment.
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "scripts"))
import numpy as np                                            # noqa: E402
import replicate_style as rs                                  # noqa: E402
from replicate_style import GREY, WIDE, plt                   # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
D = json.load(open(os.path.join(HERE, "example_data.json")))

EPS = 0.1
DOUBLING = ["euclid2", "euclid8", "clustered", "hst2", "hst4"]
OTHER = ["uniform", "tree"]
NICE = {"euclid2": r"Euclidean $\mathbb{R}^2$",
        "euclid8": r"Euclidean $\mathbb{R}^8$", "clustered": "clustered",
        "hst2": "HST ($b=2$)", "hst4": "HST ($b=4$)", "uniform": "uniform",
        "tree": "tree metric"}
SHORT = {"euclid2": r"$\mathbb{R}^2$", "euclid8": r"$\mathbb{R}^8$",
         "clustered": "clustered", "hst2": "HST $b{=}2$", "hst4": "HST $b{=}4$",
         "uniform": "uniform *", "tree": "tree *"}
KS = [8, 16, 32, 64, 96, 128]
BLUES = ["#08519c", "#2171b5", "#4292c6", "#6baed6", "#9ecae1"]
AMBER, BROWN = "#d95f02", "#8c510a"
COLOUR = dict(zip(DOUBLING, BLUES), uniform=AMBER, tree=BROWN)


def qk(fam, k):
    for r in D[f"{fam}_{EPS}"]:
        if r["k"] == k:
            return np.array(r["qs"]) / k
    raise KeyError(k)


fig, ax = plt.subplots(1, 2, figsize=(WIDE, 2.85),
                       gridspec_kw=dict(width_ratios=[1.0, 1.05]))
fig.subplots_adjust(left=0.073, right=0.995, top=0.895, bottom=0.265,
                    wspace=0.26)

# ------------------------------------------- a: every run, and the family mean
A, xs, handles = ax[0], np.arange(len(KS)), []
for fam in DOUBLING + OTHER:
    col, solid = COLOUR[fam], fam in DOUBLING
    for i, k in enumerate(KS):
        v = qk(fam, k)
        jit = np.random.default_rng(i).uniform(-0.12, 0.12, len(v))
        A.plot(np.full(len(v), i) + jit, v, ".", color=col, ms=1.7, alpha=0.45,
               zorder=2)
    handles += A.plot(xs, [qk(fam, k).mean() for k in KS],
                      "-o" if solid else "--s", color=col, ms=2.6, lw=1.1,
                      zorder=3, label=SHORT[fam])

dm = [np.concatenate([qk(f, k) for f in DOUBLING]).mean() for k in KS]
rs.refline(A, 2.0, "$2k$ — Thm 3.3, distortion 4", va="top", at=0.985)
A.set_xticks(xs)
A.set_xticklabels([str(k) for k in KS])
A.set_xlabel(r"$k$   ($n=4k$, $\epsilon=0.1$)")
A.set_ylabel(r"exact distances per centre  $q/k$")
A.set_xlim(-0.45, len(KS) - 0.35)
A.set_ylim(1.4, 4.35)
A.grid(axis="y")
A.set_axisbelow(True)
rs.statblock(A, ["doubling families",
                 fr"$\bar q/k$: {dm[0]:.2f} $\to$ {dm[-1]:.2f}",
                 fr"per doubling of $k$: $+${dm[1]-dm[0]:.2f}, "
                 fr"$+${dm[2]-dm[1]:.2f}, $+${dm[3]-dm[2]:.2f}, "
                 fr"$+${dm[5]-dm[3]:.2f}"])

# --------------------------------------------- b: the replicates at the top k
B, K = ax[1], 128
order = DOUBLING + OTHER
B.axhspan(-0.5, 1.5, color="#fdf3e7", zorder=0)
ys = rs.strip(B, [(NICE[f] + (" *" if f in OTHER else ""), qk(f, K), COLOUR[f])
                  for f in order])
for y, fam in zip(ys, order):
    if qk(fam, K).std() < 1e-9:
        B.annotate("all 12 runs identical", (qk(fam, K).mean() - 0.07, y),
                   fontsize=5.6, color=COLOUR[fam], ha="right", va="center")

mu = np.concatenate([qk(f, K) for f in DOUBLING]).mean()
B.set_ylim(-0.65, len(order) - 0.05)
B.set_xlim(1.5, 3.6)
rs.vref(B, mu, fr"$\bar q/k = {mu:.2f}$")
rs.vref(B, 2.0, r"$2k$, distortion 4", color=GREY, ha="right")
B.text(3.55, 1.34, "* unbounded doubling dimension: nothing proved",
       fontsize=5.7, color=BROWN, ha="right", va="top")
B.set_xlabel(r"exact distances per centre  $q/k$    ($k=128$, 12 runs each)")

rs.panel_key(ax[0], "a", dx=-0.105)
rs.panel_key(ax[1], "b", dx=-0.205)
rs.bottom_legend(fig, handles)

rs.save(fig, os.path.join(HERE, "example.pdf"))
rs.report(families=f"{len(DOUBLING)} doubling + {len(OTHER)} not",
          mean_qk_by_k=", ".join(f"{v:.2f}" for v in dm),
          doubling_mean_at_128=f"{mu:.3f}",
          deterministic=[f for f in order if qk(f, K).std() < 1e-9])
