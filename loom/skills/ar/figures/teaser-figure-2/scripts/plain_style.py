"""Drawing kit for the unadorned teaser figure.

The other teaser style tints each panel and gives it a coloured title pill.
This one does neither: white ground, thin rules between panels, panel names
underneath as "(a) Obstacle: ...", and a real measured chart where the other
style puts a text card.  It is the idiom of SAM (arXiv 2304.02643) and
FlashAttention (arXiv 2205.14135).

Everything shared with the other style -- canvas, text, caption, arrow, tag,
measure, audit, save, the tones -- is re-exported from overview_style, so a
figure script imports from here alone.  Coordinates are still hundredths of an
inch with the origin bottom-left, so a full-width figure is 700 x 250.
"""
from matplotlib.patches import Rectangle

from overview_style import (AMBER, BLUE, COL, GREEN, GREY, INK, RED, VIOLET,
                            WIDE, Tone, arrow, audit, canvas, caption, fit,
                            measure, plt, save, tag, text, wedge)

__all__ = ["AMBER", "BLUE", "COL", "GREEN", "GREY", "INK", "MUTED", "RED",
           "VIOLET", "WIDE", "Tone", "arrow", "audit", "canvas", "caption",
           "chart", "dashed_table", "dividers", "fit", "measure", "plt",
           "ratio", "save", "sublabel", "swatch", "tag", "text", "wedge"]

MUTED = "#4a5259"
HAIR = "#ced4da"


def dividers(ax, xs, y0=40, y1=240):
    """The thin vertical rules that separate panels instead of tinted boxes."""
    for x in xs:
        ax.plot([x, x], [y0, y1], color=HAIR, lw=0.7, zorder=1)


def sublabel(ax, cx, y, letter, bold, rest, size=7.0):
    """The under-panel name: "(a) Obstacle: free information caps at 4".

    Centred as a whole, with only the one word bold, so the three labels read
    as a sentence across the bottom of the figure.  Keep `rest` short; it has
    to fit the panel, and the caption in the paper is where detail belongs.
    """
    head, tail = f"({letter}) ", f": {rest}"
    wh = measure(ax, head, size)[0]
    wb = measure(ax, bold, size, weight="bold")[0]
    wt = measure(ax, tail, size)[0]
    x = cx - (wh + wb + wt) / 2
    text(ax, x, y, head, size=size, ha="left", color=MUTED)
    text(ax, x + wh, y, bold, size=size, ha="left", weight="bold", color=INK)
    text(ax, x + wh + wb, y, tail, size=size, ha="left", color=MUTED)
    return wh + wb + wt


def chart(ax, x, y, w, h, series, ymax, ticks=(), ylabel=None, bar_w=30,
          fmt="{:g}"):
    """A measured bar chart with a real axis -- this style's result panel.

    `series` is a list of (value, tone, name, note); `name` goes bold under the
    bar and `note` under that, which is where the condition attached to the
    measurement belongs ("distortion 2", "fused kernel").  Returns the (x, top)
    of every bar so the caller can hang a ratio arrow between two of them.

    A text card saying "5.5x fewer" is not a substitute for this: the point of
    the panel is that the reader sees the quantity, its units and its baseline.
    """
    f = h / float(ymax)
    ax.plot([x, x], [y, y + h], color=INK, lw=0.9, zorder=4)
    ax.plot([x, x + w], [y, y], color=INK, lw=0.9, zorder=4)
    for v in ticks:
        ty = y + v * f
        ax.plot([x - 3, x], [ty, ty], color=INK, lw=0.8, zorder=4)
        text(ax, x - 6, ty, fmt.format(v), size=5.8, ha="right", color=MUTED)
    if ylabel:
        text(ax, x - 24, y + h / 2, ylabel, size=6.2, rotation=90, color=MUTED)

    step = w / float(len(series))
    tops = []
    for i, (v, tone, name, note) in enumerate(series):
        bx = x + step * (i + 0.5) - bar_w / 2
        bh = v * f
        ax.add_patch(Rectangle((bx, y), bar_w, bh, facecolor=tone.fill,
                               edgecolor=tone.line, lw=1.0, zorder=3))
        text(ax, bx + bar_w / 2, y + bh + 7, fmt.format(v), size=6.7,
             weight="bold", color=tone.dark)
        text(ax, bx + bar_w / 2, y - 9, name, size=6.5, weight="bold")
        if note:
            text(ax, bx + bar_w / 2, y - 18, note, size=6.1, color=MUTED)
        tops.append((bx + bar_w / 2, y + bh))
    return tops


def ratio(ax, x, y0, y1, label, tone=RED, size=7.2):
    """The double arrow between two bar tops, carrying the headline factor."""
    ax.annotate("", xy=(x, y1), xytext=(x, y0),
                arrowprops=dict(arrowstyle="<->", color=tone.line, lw=0.9,
                                shrinkA=0, shrinkB=0))
    text(ax, x - 4, (y0 + y1) / 2, label, size=size, weight="bold", ha="right",
         color=tone.dark)


def dashed_table(ax, x, y, n, cell, filled=(), tone=RED):
    """The upper triangle of an n x n table, dashed and empty but for `filled`.

    FlashAttention's best device: the object the method never materialises is
    drawn as an outline, and the few entries it does touch are solid, so the
    saving is something the reader sees rather than reads.  Use it whenever the
    contribution is "we never build X".

    `filled` holds (i, j) pairs with j > i.  (x, y) is the bottom-left of the
    drawn staircase, and the drawn extent is (n-1) * cell square; the bounding
    box comes back so an arrow from the rest of the panel can aim at an edge.
    """
    for i in range(n - 1):
        for j in range(i + 1, n):
            got = (i, j) in filled
            ax.add_patch(Rectangle(
                (x + (j - 1) * cell, y + (n - 2 - i) * cell), cell, cell,
                facecolor=tone.fill if got else "white",
                edgecolor=tone.line if got else "#adb5bd", lw=0.7, zorder=3,
                linestyle="solid" if got else (0, (1.5, 1.2))))
    side = (n - 1) * cell
    return x, y, x + side, y + side


def swatch(ax, x, y, label, tone, size=6.1, s=6.5, dashed=False):
    """A small filled square plus text, for naming a mark used in the panel."""
    ax.add_patch(Rectangle((x, y), s, s, facecolor="white" if dashed
                           else tone.fill, edgecolor=tone.line, lw=0.8,
                           zorder=3,
                           linestyle=(0, (2, 1.4)) if dashed else "solid"))
    text(ax, x + s + 3, y + s / 2, label, size=size, ha="left")
