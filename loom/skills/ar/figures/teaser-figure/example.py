"""A worked three-panel teaser, for the AAAI-27 paper "Comparisons Are Free,
Ratios Are Not". Read this to see how the kit is used; run it to see the output.

Left: why the published bounds fail to meet -- a comparison transcript pins the
instance only up to a cone, and every guarantee in these fields is a ratio.
Centre: how Lazy-FFT spends a query only when the tallest cached radius could
still change the answer. Right: what that buys.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "scripts"))
from overview_style import (AMBER, BLUE, GREEN, GREY, INK, RED, VIOLET, _round,
                            arrow, audit, box, canvas, caption, panel, plt, save, tag,
                            text, wedge)

fig, ax = canvas(7.0, 2.50)
PY, PH = 8, 222
MUTED = "#4a5259"

# ----------------------------------------------------------------- left panel
AX, AW = 4, 190
panel(ax, AX, PY, AW, PH, "Why the Bounds Don't Meet", BLUE)
acx = AX + AW / 2

caption(ax, acx, 212, ["A comparison reports an order, so rescaling",
                       "every latent distance changes no answer:"], 172)

_round(ax, 22, 174, 154, 22, r=4, fc=BLUE.fill, ec=BLUE.line, lw=0.9, z=2)
text(ax, 99, 185, r"d(a,b) < d(a,c)   $\Leftrightarrow$   λd(a,b) < λd(a,c)",
     size=6.9, color=BLUE.dark, z=5, maxw=145)

text(ax, acx, 163, "so they pin the instance down only to a cone", size=6.3,
     maxw=172)

apex = (26, 106)
p1, p2 = wedge(ax, apex, -19, 19, 136, BLUE, alpha=0.55)
for p in (p1, p2):
    ax.plot([apex[0], p[0]], [apex[1], p[1]], color=BLUE.line, lw=1.0, zorder=3)
text(ax, 92, 111, "every instance the", size=6.0, color=MUTED)
text(ax, 92, 103, "comparisons allow", size=6.0, color=MUTED)
text(ax, p2[0] + 4, p2[1], "2ρ", size=7.4, ha="left", color=BLUE.dark,
     weight="bold")
text(ax, p1[0] + 4, p1[1], "ρ", size=7.4, ha="left", color=BLUE.dark,
     weight="bold")
ax.annotate("", xy=(176, p2[1] - 1), xytext=(176, p1[1] + 1),
            arrowprops=dict(arrowstyle="<->", color=GREY.line, lw=0.8,
                            shrinkA=0, shrinkB=0))
text(ax, 184, 106, "cone width", size=6.0, color=GREY.line, rotation=90)

box(ax, 16, 16, 166, 36, "The price of scale",
    "a ratio finer than the width must be bought", tone=BLUE, size=7.8,
    subsize=6.3)

# --------------------------------------------------------------- centre panel
BX, BW = 202, 272
panel(ax, BX, PY, BW, PH, "Method: Lazy-FFT", RED)
bcx = BX + BW / 2

caption(ax, bcx, 212,
        ["Keep an upper bound û(v) on every cluster radius; buy a real",
         "distance only while one of them can still mislead you."], 254)

YB, BARW, GAP, X0 = 92, 13.0, 5.0, 216
HEIGHTS = [78, 67, 54, 46, 39, 33, 28]
STALE = {0, 1}
for i, h in enumerate(HEIGHTS):
    x = X0 + i * (BARW + GAP)
    fresh = i not in STALE
    ax.add_patch(plt.Rectangle(
        (x, YB), BARW, h, facecolor=RED.fill if fresh else "white",
        edgecolor=RED.line, lw=0.9, zorder=3,
        linestyle="solid" if fresh else (0, (2, 1.4))))
XEND = X0 + len(HEIGHTS) * BARW + (len(HEIGHTS) - 1) * GAP
ax.plot([X0 - 6, XEND + 4], [YB, YB], color=INK, lw=0.9, zorder=4)

THR = YB + 64
ax.plot([X0 - 6, 342], [THR, THR], color=GREY.line, lw=0.9, ls=(0, (3, 2)),
        zorder=4)
tag(ax, 296, THR, "(1+ε) × tallest fresh", GREY, size=6.0)

arrow(ax, (248, 186), (223, 173), RED, lw=1.1, head=6)
tag(ax, 292, 189, "pay: 1 exact distance", RED, size=6.0)

text(ax, 276, 84, "cluster radii, tallest first", size=6.0, color=MUTED)
ax.add_patch(plt.Rectangle((216, 64), 8, 8, facecolor="white",
                           edgecolor=RED.line, lw=0.9, ls=(0, (2, 1.4)),
                           zorder=3))
text(ax, 228, 68, "stale cache", size=6.0, ha="left")
ax.add_patch(plt.Rectangle((286, 64), 8, 8, facecolor=RED.fill,
                           edgecolor=RED.line, lw=0.9, zorder=3))
text(ax, 298, 68, "freshly measured", size=6.0, ha="left")

box(ax, 348, 140, 116, 34, "a bar pokes out", "refresh it, then re-check",
    tone=RED, size=6.9, subsize=6.2)
box(ax, 348, 96, 116, 34, "none pokes out", "open a center — free",
    tone=GREEN, size=6.9, subsize=6.2)
arrow(ax, (336, 168), (346, 160), RED, lw=1.0, head=6)
arrow(ax, (336, 112), (346, 116), GREEN, lw=1.0, head=6)

box(ax, 210, 18, 254, 40, "k−1 centers, and the bill stays linear in k",
    "the caches turn a quadratic count of exact distances into a linear one",
    tone=AMBER, size=7.6, subsize=6.4)

# ---------------------------------------------------------------- right panel
CX, CW = 482, 214
panel(ax, CX, PY, CW, PH, "What It Buys", GREEN)
ccx = CX + CW / 2

text(ax, ccx, 209, "distortion you can certify", size=6.8, color=MUTED,
     style="italic")
L, R = 526, 666
text(ax, L, 196, "distortion 2", size=6.2, color=GREY.line)
text(ax, R, 196, "4", size=6.2, color=GREY.line)

text(ax, 490, 182, "before", size=6.8, weight="bold", ha="left",
     color=GREY.line)
ax.plot([L, R], [182, 182], "-o", color=GREY.line, lw=0.9, ms=3.8, zorder=3)
text(ax, (L + R) / 2, 182, "nothing in between", size=6.0, color=GREY.line,
     style="italic", z=6,
     bbox=dict(boxstyle="round,pad=0.20", fc=GREEN.tint, ec="none"))
text(ax, L, 171, r"$\binom{k}{2}$ queries", size=6.1)
text(ax, R, 171, "2k queries", size=6.1)

text(ax, 490, 150, "ours", size=6.8, weight="bold", ha="left", color=GREEN.dark)
ax.plot([L, R], [150, 150], color=GREEN.line, lw=3.6, zorder=3,
        solid_capstyle="butt")
ax.plot([L], [150], "o", mfc="white", mec=GREEN.line, mew=1.1, ms=4.4, zorder=4)
text(ax, (L + R) / 2, 139, "every ε > 0, at O(k) queries on doubling metrics",
     size=6.3, maxw=190)

box(ax, 490, 96, 198, 34, "and 4 is the ceiling",
    "two 4-point metrics agree on order and on a bought\n"
    "distance, yet their radius ratios sit a factor →2 apart",
    tone=GREY, size=7.0, subsize=5.7)

text(ax, ccx, 84, "the same cone, twice more", size=6.8, color=MUTED,
     style="italic")
box(ax, 490, 46, 198, 30,
    "Borda: one query caps success at 0.417 (m=3), 0.333 (m=4)",
    tone=VIOLET, size=6.5, r=4)
box(ax, 490, 12, 198, 30,
    r"fair division: the share costs $\mathbf{\lceil \log_2 n \rceil}$ comparisons",
    tone=VIOLET, size=6.5, r=4)

audit(ax, [("left", AX, PY, AW, PH + 12), ("centre", BX, PY, BW, PH + 12),
           ("right", CX, PY, CW, PH + 12)])
save(fig, "example.pdf")
