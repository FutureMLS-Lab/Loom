"""Plot kit for the results figures in this repo's papers.

This is the evidence half of figure-making: charts that carry measurements,
as opposed to the teaser skills, which draw schematics.  The settings here are
the ones the AAAI author kit requires plus the ones the existing figures in
aaai2027/paper-*/code/make_figure*.py already converged on, so a new figure
matches the ones beside it.

Import it before touching pyplot; it applies the rcParams at import time.

    import plot_style as ps
    fig, ax = plt.subplots(1, 2, figsize=(ps.WIDE, 2.45))
    ...
    ps.save(fig, "../latex/figs/name.pdf")
"""
import glob
import os

import matplotlib

matplotlib.use("Agg")
# The AAAI kit requires Type 1 or TrueType. matplotlib's PDF default is Type 3,
# which fails the check silently at submission time.
matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42

from matplotlib import font_manager
import matplotlib.pyplot as plt

WIDE = 7.0        # a figure* spanning both columns
COL = 3.3         # a single column

# Okabe-Ito: distinguishable under all common colour-vision deficiencies.
BLUE = "#0072B2"
ORANGE = "#E69F00"
GREEN = "#009E73"
VERM = "#D55E00"
SKY = "#56B4E9"
PURPLE = "#CC79A7"
YELLOW = "#F0E442"
BLACK = "#000000"
GREY = "#666666"
CYCLE = [BLUE, ORANGE, GREEN, VERM, PURPLE, SKY, YELLOW]

# Match the paper's body face when TeX Gyre Termes can be found; otherwise
# matplotlib falls back to DejaVu Serif, which changes the look but not a
# single plotted number.
for _root in (os.path.expanduser("~/.TinyTeX"), "/usr/share/texlive",
              "/usr/local/texlive", "/opt/texlive", "/usr/share/fonts"):
    for _f in glob.glob(_root + "/**/texgyretermes-*.otf", recursive=True):
        font_manager.fontManager.addfont(_f)

plt.rcParams.update({
    "font.family": "serif",
    "font.serif": ["TeX Gyre Termes", "DejaVu Serif"],
    "mathtext.fontset": "stix",
    "font.size": 8,
    "axes.labelsize": 8,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
    "legend.fontsize": 6.6,
    "axes.linewidth": 0.5,
    "lines.linewidth": 1.2,
    "lines.markersize": 3.2,
    "axes.spines.top": False,
    "axes.spines.right": False,
    "axes.grid": True,
    "grid.linestyle": ":",
    "grid.linewidth": 0.5,
    "grid.alpha": 0.6,
    "grid.color": "#bbbbbb",
    "figure.dpi": 300,
    "savefig.dpi": 300,
})

LEGEND = dict(framealpha=0.95, borderpad=0.3, handlelength=1.8,
              labelspacing=0.24, columnspacing=1.0)


def logticks(ax, values, axis="y", fmt="{:g}"):
    """Explicit ticks on a log axis, written plainly rather than as 10^n.

    matplotlib's default log formatter also litters the axis with unlabelled
    minor ticks, which at 7 pt reads as noise.
    """
    getattr(ax, f"set_{axis}scale")("log")
    getattr(ax, f"set_{axis}ticks")(list(values))
    getattr(ax, f"set_{axis}ticklabels")([fmt.format(v) for v in values])
    ax.minorticks_off()


def refline(ax, value, label=None, axis="y", color=GREY, ls=(0, (4, 2)),
            lw=0.9, at=None, va="bottom", ha="right", pad=0.004, fontsize=6.4):
    """A baseline the reader is meant to compare against, named in place.

    Prior work, a theoretical bound, a chance level: draw it dashed and label
    it on the line rather than in the legend, so the comparison needs no
    lookup.  `at` is the position along the line in axes fraction.
    """
    line = (ax.axhline if axis == "y" else ax.axvline)(value, color=color,
                                                       ls=ls, lw=lw, zorder=1)
    if label:
        # get_yaxis_transform: x in axes fraction, y in data -- which is what
        # labelling a horizontal line needs. The other way round for a vertical.
        t = ax.get_yaxis_transform() if axis == "y" else ax.get_xaxis_transform()
        pos = 0.98 if at is None else at
        if axis == "y":
            ax.text(pos, value, label, transform=t, ha=ha, va=va, color=color,
                    fontsize=fontsize)
        else:
            ax.text(value, pos, label, transform=t, ha=ha, va=va, color=color,
                    fontsize=fontsize, rotation=0)
    return line


def save(fig, path, tight=False):
    """Write the PDF, and check it came out the size that was asked for.

    `tight` is off by default on purpose.  bbox_inches="tight" crops to the
    ink, so a figure declared 7.0 in can land at 5.9; \\includegraphics
    [width=\\textwidth] then scales it back up and every font size chosen here
    renders ~19% larger than in the figure beside it.  Set the margins with
    subplots_adjust instead.  CreationDate is dropped so an unchanged figure
    re-renders byte-identical.
    """
    kw = dict(metadata={"CreationDate": None})
    if tight:
        kw.update(bbox_inches="tight", pad_inches=0.01)
    fig.savefig(path, **kw)
    want = fig.get_size_inches()
    try:
        import fitz
        r = fitz.open(path)[0].rect
        got = (r.width / 72, r.height / 72)
        if abs(got[0] - want[0]) > 0.05:
            print(f"  SIZE asked {want[0]:.2f} x {want[1]:.2f} in, "
                  f"got {got[0]:.2f} x {got[1]:.2f}")
    except ImportError:
        pass
    print(f"wrote {path}")
    return path


def report(**kw):
    """Print the numbers the figure asserts, so the caption can be checked.

    Every figure script here ends with one of these.  The caption and the body
    text quote figures; this is what they get checked against without anyone
    having to reopen the PDF.
    """
    for k, v in kw.items():
        print(f"  {k.replace('_', ' ')}: {v}")
