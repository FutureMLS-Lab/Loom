"""Drawing kit for the AAAI-27 overview ("teaser") figures.

These are schematic figures, not plots: tinted panels, rounded boxes, arrows.
The palette is Excalidraw's, which is what the target style is usually drawn in,
but everything is emitted as vector PDF with TrueType fonts so it drops straight
into the Author Kit (which forbids Type 3).

Coordinates are hundredths of an inch with the origin bottom-left, so a
full-width AAAI figure is 700 units across.
"""
import glob
import os

import matplotlib

matplotlib.use("Agg")
matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42

from matplotlib import font_manager
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Polygon
import matplotlib.pyplot as plt

for _root in (os.path.expanduser("~/.TinyTeX"), "/usr/share/texlive",
              "/usr/local/texlive", "/opt/texlive", "/usr/share/fonts"):
    for _pat in ("texgyreheros-*.otf", "texgyretermes-*.otf"):
        for _f in glob.glob(_root + "/**/" + _pat, recursive=True):
            font_manager.fontManager.addfont(_f)

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["TeX Gyre Heros", "DejaVu Sans"],
    "mathtext.fontset": "stixsans",
    "figure.dpi": 300,
    "savefig.dpi": 300,
})

WIDE = 7.0   # full two-column width, inches
COL = 3.3    # single column, inches


class Tone:
    """A stroke colour plus the tints used for panel and box fills."""

    def __init__(self, line, tint, fill, dark=None):
        self.line = line
        self.tint = tint    # panel background
        self.fill = fill    # box background
        self.dark = dark or line


BLUE = Tone("#1971c2", "#f2f8fd", "#d8ecfb")
RED = Tone("#e03131", "#fdf4f4", "#fbdada")
GREEN = Tone("#2f9e44", "#f3fbf4", "#d8f2dc")
AMBER = Tone("#e8890c", "#fef9f1", "#fbe7c6")
VIOLET = Tone("#6741d9", "#f7f5fd", "#e2daf8")
GREY = Tone("#7a8288", "#f7f8f9", "#e9ecef")
INK = "#1e1e1e"


def canvas(w_in, h_in):
    """A blank figure whose data coordinates are hundredths of an inch."""
    fig = plt.figure(figsize=(w_in, h_in))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, w_in * 100)
    ax.set_ylim(0, h_in * 100)
    ax.set_aspect("equal")
    ax.axis("off")
    return fig, ax


_RENDERERS = {}


def _renderer(fig):
    if fig not in _RENDERERS:
        fig.canvas.draw()
        _RENDERERS[fig] = fig.canvas.get_renderer()
    return _RENDERERS[fig]


def measure(ax, s, size, weight="normal", style="normal"):
    """Width and height of `s` in canvas units, as it would actually render."""
    t = ax.text(0, 0, s, fontsize=size, fontweight=weight, fontstyle=style)
    bb = t.get_window_extent(_renderer(ax.figure))
    t.remove()
    (x0, y0), (x1, y1) = ax.transData.inverted().transform(
        [[bb.x0, bb.y0], [bb.x1, bb.y1]])
    return abs(x1 - x0), abs(y1 - y0)


def fit(ax, s, maxw, size, weight="normal", style="normal", floor=4.8):
    """Shrink `size` until `s` fits in `maxw`, so no label can overrun a box.

    Warns when it bottoms out, because the failure is otherwise silent: the
    string is drawn too small to read *and* still overruns.  Shorten the text
    or widen the slot; do not lower the floor.
    """
    while size > floor and measure(ax, s, size, weight, style)[0] > maxw:
        size -= 0.1
    size = round(size, 2)
    if measure(ax, s, size, weight, style)[0] > maxw:
        print(f"  TOO LONG at {size}pt, needs {maxw:.0f}: {s[:52]!r}")
    return size


def _round(ax, x, y, w, h, r=6, fc="none", ec=INK, lw=0.8, z=1, ls="solid",
           alpha=1.0):
    p = FancyBboxPatch((x + r, y + r), w - 2 * r, h - 2 * r,
                       boxstyle=f"round,pad={r},rounding_size={r}",
                       linewidth=lw, edgecolor=ec, facecolor=fc, zorder=z,
                       linestyle=ls, alpha=alpha)
    ax.add_patch(p)
    return p


def text(ax, x, y, s, size=7, weight="normal", color=INK, ha="center",
         va="center", z=5, style="normal", maxw=None, **kw):
    if maxw:
        size = fit(ax, s, maxw, size, weight, style)
    return ax.text(x, y, s, fontsize=size, fontweight=weight, color=color,
                   ha=ha, va=va, zorder=z, fontstyle=style, **kw)


def caption(ax, cx, ytop, lines, maxw, size=6.8, gap=9, color="#4a5259"):
    """The italic lead-in under a panel title.

    Sizes every line together so a long second line cannot end up visibly
    smaller than the first.
    """
    for s in lines:
        size = fit(ax, s, maxw, size, "normal", "italic")
    for i, s in enumerate(lines):
        text(ax, cx, ytop - i * gap, s, size=size, color=color, style="italic")
    return size


def panel(ax, x, y, w, h, title, tone, size=8.0):
    """A tinted region with a coloured caption pill straddling its top edge."""
    _round(ax, x, y, w, h, r=8, fc=tone.tint, ec=tone.line, lw=0.9, z=0)
    pw = measure(ax, title, size, "bold")[0] + 22
    pill = _round(ax, x + (w - pw) / 2, y + h - 9, pw, 18, r=9,
                  fc=tone.line, ec=tone.line, lw=0.9, z=6)
    text(ax, x + w / 2, y + h, title, size=size, weight="bold", color="white",
         z=7)
    return pill


def box(ax, x, y, w, h, title, sub=None, tone=GREY, r=5, lw=0.9, size=7.2,
        subsize=6.3, ls="solid", fc=None, z=2, pad=9):
    """A rounded box with a bold title and optional smaller second line."""
    _round(ax, x, y, w, h, r=r, fc=tone.fill if fc is None else fc,
           ec=tone.line, lw=lw, z=z, ls=ls)
    cx, inner = x + w / 2, w - pad
    if sub:
        text(ax, cx, y + h / 2 + h * 0.17, title, size=size, weight="bold",
             color=tone.dark, z=z + 3, maxw=inner)
        text(ax, cx, y + h / 2 - h * 0.20, sub, size=subsize, color=INK,
             z=z + 3, maxw=inner, linespacing=1.15)
    else:
        text(ax, cx, y + h / 2, title, size=size, weight="bold",
             color=tone.dark, z=z + 3, maxw=inner)


def arrow(ax, a, b, tone=GREY, lw=1.0, rad=0.0, ls="solid", head=7, z=4,
          shrink=1.0):
    p = FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=head,
                        linewidth=lw, color=tone.line if isinstance(tone, Tone)
                        else tone, zorder=z,
                        connectionstyle=f"arc3,rad={rad}", linestyle=ls,
                        shrinkA=shrink, shrinkB=shrink,
                        joinstyle="round", capstyle="round")
    ax.add_patch(p)
    return p


def tag(ax, x, y, s, tone, size=6.0, pad=5.0, z=8, h=12):
    """A small pill used to label an arrow (`free`, `1 query`, ...)."""
    w = measure(ax, s, size, "bold")[0] + 2 * pad
    _round(ax, x - w / 2, y - h / 2, w, h, r=h / 2, fc="white", ec=tone.line,
           lw=0.7, z=z)
    text(ax, x, y, s, size=size, weight="bold", color=tone.dark, z=z + 1)
    return w


def wedge(ax, apex, a1, a2, length, tone, alpha=0.30, z=1):
    """A filled 2-D cone, for drawing 'the transcript pins it only this far'."""
    import math
    p1 = (apex[0] + length * math.cos(math.radians(a1)),
          apex[1] + length * math.sin(math.radians(a1)))
    p2 = (apex[0] + length * math.cos(math.radians(a2)),
          apex[1] + length * math.sin(math.radians(a2)))
    ax.add_patch(Polygon([apex, p1, p2], closed=True, facecolor=tone.fill,
                         edgecolor=tone.line, linewidth=0.8, alpha=alpha,
                         zorder=z))
    return p1, p2


def audit(ax, regions):
    """Report any text that escapes every region it could belong to.

    `regions` is a list of (name, x, y, w, h). Cheap insurance against labels
    silently running out of their panel, which is invisible in the source.
    """
    r = _renderer(ax.figure)
    inv = ax.transData.inverted()
    bad = []
    for t in ax.texts:
        bb = t.get_window_extent(r)
        (x0, y0), (x1, y1) = inv.transform([[bb.x0, bb.y0], [bb.x1, bb.y1]])
        if not any(x0 >= x - 1.5 and x1 <= x + w + 1.5 and y0 >= y - 1.5
                   and y1 <= y + h + 1.5 for _, x, y, w, h in regions):
            bad.append(f"{t.get_text()[:46]!r} at x {x0:.0f}..{x1:.0f}, "
                       f"y {y0:.0f}..{y1:.0f}")
    for b in bad:
        print("  OVERFLOW", b)
    return bad


def save(fig, name, outdir=None):
    """Write the PDF, plus a PNG preview to actually look at.

    Defaults to the directory of the script that called this, not of this
    module, so the kit can be copied anywhere without moving the output.

    CreationDate is dropped so an unchanged figure re-renders byte-identical;
    otherwise every run to check the output shows up as a diff.
    """
    if outdir is None:
        import inspect
        outdir = os.path.dirname(os.path.abspath(inspect.stack()[1].filename))
    out = os.path.join(outdir, name)
    fig.savefig(out, metadata={"CreationDate": None})
    fig.savefig(out.replace(".pdf", ".png"), dpi=220)
    print(f"wrote {out}")
    return out
