"""A worked plain teaser, for the AAAI-27 paper "Comparisons Are Free, Ratios
Are Not".  Read it to see how the kit is used; run it to see the output.

(a) draws the obstacle as the object itself: the paper's two four-point metrics,
identical in everything the algorithm can observe, differing in the one radius
it cannot.  (b) draws the table of exact distances the method never builds.
(c) is a measured chart, not a card claiming a speed-up.

Every number is traceable: the metrics and radii come from the paper's
code/scale_barrier.py, the query counts from code/results_frontier.json
(k = 32, n = 96, seven metric families, 12 trials each, eps = 0.05), and the
prior costs are its Thm 3.1 and Thm 3.3, k(k-1)/2 = 496 and 2k = 64 at k = 32.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "scripts"))
from plain_style import (GREEN, GREY, INK, MUTED, RED, arrow, audit, canvas,
                         caption, chart, dashed_table, dividers, plt, ratio,
                         save, sublabel, swatch, tag, text)

fig, ax = canvas(7.0, 2.50)
dividers(ax, (207, 476))

# ------------------------------------------------- (a) the four-point barrier
AL, AR = 6, 199
acx = (AL + AR) / 2

caption(ax, acx, 236, ["everything the algorithm can see is identical:",
                       "the same four rankings, the same bought d(p,q) = 1"],
        188, size=6.4)

S = 12.5                                  # canvas units per unit of distance
for cy, ytitle, ylab, name, ru in ((176, 202, 143, "metric A", 1.95),
                                   (98, 117, 77, "metric B", 0.508)):
    text(ax, AL + 6, ytitle, name, size=6.6, weight="bold", ha="left",
         color=MUTED)
    for cx0, ctr, mem, r, tn in ((52, "p", "q", 1.0, GREY),
                                 (138, "u", "w", ru, RED)):
        rr = r * S
        ax.add_patch(plt.Circle((cx0, cy), rr, facecolor=tn.fill,
                                edgecolor=tn.line, lw=0.9, zorder=2,
                                alpha=0.7))
        ax.plot([cx0, cx0 + rr], [cy, cy], color=tn.line, lw=0.8, zorder=4)
        ax.plot([cx0], [cy], "o", color=INK, ms=2.6, zorder=5)
        ax.plot([cx0 + rr], [cy], "o", mfc="white", mec=INK, mew=0.8, ms=2.6,
                zorder=5)
        text(ax, cx0 - 4, cy + 5, ctr, size=6.6, weight="bold", ha="right")
        text(ax, cx0 + rr + 3, cy + 5, mem, size=6.2, ha="left", color=MUTED)
    text(ax, 52, ylab, "r(p) = 1", size=6.2, color=MUTED)
    text(ax, 138, ylab, f"r(u) = {ru:g}", size=6.7, weight="bold",
         color=RED.dark)

caption(ax, acx, 58, ["open either center and one of the two metrics",
                      "charges you a factor approaching 2"], 188, size=6.4,
        color=INK)

# ----------------------------------------------------- (b) what Lazy-FFT does
BL, BR = 216, 468
bcx = (BL + BR) / 2

caption(ax, bcx, 238,
        ["keep an upper bound on every cluster radius; measure one",
         "only while the tallest cached bound could still mislead"],
        248, size=6.4)

YB, BW, GAP, X0 = 124, 11.0, 4.5, 228
BARS = [62, 50, 41, 34, 29, 25]
THR = YB + 1.15 * BARS[1]                 # (1+eps) x tallest freshly measured
for i, h in enumerate(BARS):
    stale = i == 0
    ax.add_patch(plt.Rectangle(
        (X0 + i * (BW + GAP), YB), BW, h,
        facecolor="white" if stale else RED.fill, edgecolor=RED.line, lw=0.9,
        zorder=3, linestyle=(0, (2, 1.4)) if stale else "solid"))
XE = X0 + len(BARS) * BW + (len(BARS) - 1) * GAP
ax.plot([X0 - 5, XE + 3], [YB, YB], color=INK, lw=0.9, zorder=4)
ax.plot([X0 - 5, XE + 3], [THR, THR], color=GREY.line, lw=0.9, ls=(0, (3, 2)),
        zorder=4)
text(ax, X0 + 5.5, 192, "cached", size=5.9, color=MUTED)
tag(ax, 292, 192, "(1+ε) × tallest fresh", GREY, size=5.9)
text(ax, X0 - 3, 214, "cached upper bounds, tallest first", size=6.2,
     ha="left", color=MUTED)

tx0, ty0, _, ty1 = dashed_table(
    ax, 382.25, 136.25, 8, 8.5,
    filled={(0, 1), (0, 4), (1, 3), (2, 6), (3, 5), (5, 7)})
caption(ax, 412, 124, ["every pair's exact distance:",
                       "496 at k = 32; Lazy-FFT fills",
                       "O(k), on doubling metrics"], 108, size=6.1, gap=8.5)
arrow(ax, (XE + 4, 168), (tx0 - 3, (ty0 + ty1) / 2), RED, lw=1.1, head=6,
      rad=-0.16)
text(ax, 350, 182, "buy one", size=6.1, color=RED.dark)

swatch(ax, X0 - 3, 90, "a bound pokes out — refresh it, then re-check", RED)
swatch(ax, X0 - 3, 74, "none pokes out — open that center, free", GREEN)

# ---------------------------------------------------------- (c) measured cost
CL, CR = 486, 694
tops = chart(ax, 524, 88, 164, 140,
             [(64, GREY, "prior", "distortion 4"),
              (89.5, GREEN, "Lazy-FFT", "distortion 2.1"),
              (496, GREY, "prior", "distortion 2")],
             ymax=520, ticks=(0, 250, 500), ylabel="exact distances measured")
ratio(ax, (tops[1][0] + tops[2][0]) / 2, tops[1][1], tops[2][1], "5.5×")
text(ax, (CL + CR) / 2, 52,
     "k = 32, n = 96; mean over seven metric families, 12 trials each",
     size=5.9, color=MUTED, style="italic", maxw=204)

# -------------------------------------------------------------------- labels
sublabel(ax, acx, 14, "a", "Obstacle", "free information caps at 4")
sublabel(ax, bcx, 14, "b", "Method", "never build the distance table")
sublabel(ax, (CL + CR) / 2, 14, "c", "Result", "distortion 2.1, 5.5× fewer")

audit(ax, [("a", AL, 6, AR - AL, 239), ("b", BL, 6, BR - BL, 239),
           ("c", CL, 6, CR - CL, 239)])
save(fig, "example.pdf")
