"""Additions for the replicate-forward results figure.

Everything in plot_style still applies -- this only adds the pieces that draw a
distribution instead of an aggregate: the strip of individual runs, the dashed
reference carrying a published value, the statistics block set inside the
panel, the bold lowercase panel keys, and the figure-level legend that keeps a
legend from eating a panel.

    import replicate_style as rs
    from replicate_style import WIDE, plt
"""
import numpy as np

from plot_style import (BLACK, BLUE, COL, CYCLE, GREEN, GREY, LEGEND, ORANGE,
                        PURPLE, SKY, VERM, WIDE, YELLOW, logticks, plt,
                        refline, report, save)

__all__ = ["BLACK", "BLUE", "COL", "CYCLE", "GREEN", "GREY", "LEGEND",
           "ORANGE", "PURPLE", "SKY", "VERM", "WIDE", "YELLOW", "bottom_legend",
           "logticks", "panel_key", "plt", "refline", "report", "save",
           "statblock", "strip", "vref"]

RED = "#cb181d"     # reserved for the summary line over the replicates


def panel_key(ax, letter, dx=-0.11, dy=1.10, size=10):
    """The bold lowercase key outside the axes, as Nature-style figures set it.

    The caption then reads "a, ... b, ...", which is what lets one numbered
    figure carry a whole argument instead of three.
    """
    return ax.text(dx, dy, letter, transform=ax.transAxes, fontsize=size,
                   fontweight="bold", va="top", ha="left")


def statblock(ax, lines, loc="upper right", size=5.8, pad=0.015):
    """The statistics, right-aligned inside the panel.

    Put here what the reader needs to judge the panel -- n, the spread, the
    step sizes, the significance count -- rather than making them find it in
    the body text three pages later.
    """
    ha = "right" if "right" in loc else "left"
    va = "top" if "upper" in loc else "bottom"
    x = 1 - pad if ha == "right" else pad
    y = 1 - pad if va == "top" else pad
    return ax.text(x, y, "\n".join(lines), transform=ax.transAxes, ha=ha,
                   va=va, fontsize=size, linespacing=1.35)


def strip(ax, rows, jitter=0.15, ms=2.4, mean_ms=10, seed=7):
    """One row per group, every replicate drawn, the mean as a tick.

    `rows` is a list of (label, values, colour) ordered top to bottom.  Returns
    the y positions so the caller can shade or bracket a subset of rows.  Hollow
    markers, because replicates overlap and filled ones turn into a blob.

    A group whose replicates are identical collapses to a single mark; that is
    information, so say it rather than letting it look like a plotting error.
    """
    ys = list(range(len(rows)))[::-1]
    for y, (_, v, col) in zip(ys, rows):
        v = np.asarray(v, dtype=float)
        j = np.random.default_rng(seed + y).uniform(-jitter, jitter, len(v))
        ax.plot(v, np.full(len(v), y) + j, "o", ms=ms, mfc="none", mew=0.6,
                color=col, zorder=3)
        ax.plot([v.mean()], [y], "|", color=col, ms=mean_ms, mew=1.4, zorder=4)
    ax.set_yticks(ys)
    ax.set_yticklabels([r[0] for r in rows], fontsize=6.4)
    ax.tick_params(axis="y", length=0, pad=2)
    ax.spines["left"].set_visible(False)
    ax.grid(axis="x")
    ax.set_axisbelow(True)
    return ys


def vref(ax, x, label, color=RED, y=None, ha="left", lw=1.0, size=6.2):
    """A dashed vertical reference with its value written in the line's colour.

    Colour-matching the number to the line is the whole trick: the reader never
    has to work out which dashed line the "0.849" belongs to.  Use it for the
    published value being beaten, and for the summary of the replicates.
    """
    ax.axvline(x, color=color, ls=(0, (4, 2)), lw=lw, zorder=2)
    top = ax.get_ylim()[1] - 0.42 if y is None else y
    off = 0.03 if ha == "left" else -0.03
    ax.text(x + off, top, label, color=color, fontsize=size, ha=ha,
            va="bottom")


def bottom_legend(fig, handles, ncol=None, y=0.005, size=6.0):
    """One legend for the whole figure, under it, instead of one per panel.

    With replicates drawn, panels have no free corner left; this is how the
    reference figures solve it.
    """
    labels = [h.get_label() for h in handles]
    return fig.legend(handles, labels, loc="lower center",
                      bbox_to_anchor=(0.52, y), ncol=ncol or len(handles),
                      fontsize=size, frameon=False, handlelength=1.6,
                      columnspacing=1.4, handletextpad=0.45)
