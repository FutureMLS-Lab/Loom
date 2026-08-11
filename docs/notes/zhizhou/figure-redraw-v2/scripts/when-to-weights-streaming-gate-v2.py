"""HarnessBank-inspired streaming gate overview.

This is a versioned candidate for Appendix Figure ``fig:algo``. It is a
deterministic rendering of the algorithm text and does not replace the paper.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle


HERE = Path(__file__).resolve().parent
OUT = HERE.parents[3] / "figure-redraw-v2"

NAVY = "#0d2b4f"
NAVY_2 = "#173f6b"
INK = "#17263a"
BLUE = "#2f6f9f"
BLUE_FILL = "#e7f1f8"
CREAM = "#fff9e9"
GREEN = "#159947"
GREEN_FILL = "#e9f8ee"
RED = "#ef4444"
RED_FILL = "#fff0f0"
ORANGE = "#f39b28"
GREY = "#6f7d8c"
GREY_FILL = "#f1f3f5"

mpl.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 7,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
)

TEXT_ARTISTS = []
BOUNDED_TEXT = []
GAP_CHECKS = []


def rounded(
    ax,
    x,
    y,
    w,
    h,
    *,
    fc="white",
    ec=NAVY,
    lw=1.15,
    radius=0.02,
    zorder=2,
):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.006,rounding_size={radius}",
        transform=ax.transAxes,
        facecolor=fc,
        edgecolor=ec,
        linewidth=lw,
        clip_on=False,
        zorder=zorder,
    )
    ax.add_patch(patch)
    return patch


def text(ax, x, y, value, **kwargs):
    defaults = dict(
        transform=ax.transAxes,
        ha="center",
        va="center",
        color=INK,
        fontsize=6.6,
        zorder=8,
    )
    defaults.update(kwargs)
    artist = ax.text(x, y, value, **defaults)
    TEXT_ARTISTS.append(artist)
    return artist


def inside(ax, region, x, y, value, *, name, **kwargs):
    artist = text(ax, x, y, value, **kwargs)
    BOUNDED_TEXT.append((artist, region, name))
    return artist


def arrow(ax, start, end, *, color=BLUE, lw=1.7, rad=0.0):
    patch = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=9,
        linewidth=lw,
        color=color,
        connectionstyle=f"arc3,rad={rad}",
        transform=ax.transAxes,
        clip_on=False,
        zorder=6,
    )
    ax.add_patch(patch)
    return patch


def stage(ax, x, y, w, h, number, title, lines, *, fc=BLUE_FILL, accent=BLUE):
    region = (x, y, w, h)
    rounded(ax, x, y, w, h, fc=fc, ec=NAVY, lw=1.1, radius=0.018)
    rounded(ax, x + 0.012, y + h - 0.093, 0.038, 0.066, fc=accent, ec=accent, lw=0)
    inside(
        ax,
        region,
        x + 0.031,
        y + h - 0.060,
        number,
        name=f"stage-{number}-number",
        color="white",
        weight="bold",
        fontsize=7.0,
    )
    inside(
        ax,
        region,
        x + 0.058,
        y + h - 0.060,
        title,
        ha="left",
        va="center",
        weight="bold",
        fontsize=6.15,
        color=NAVY,
        linespacing=0.88,
        name=f"stage-{number}-title",
    )
    for index, line in enumerate(lines):
        inside(
            ax,
            region,
            x + w / 2,
            y + h - 0.145 - index * 0.052,
            line,
            fontsize=5.8,
            color=GREY if index else INK,
            name=f"stage-{number}-line-{index + 1}",
        )


def audit_text(fig, ax):
    """Fail the render if text leaves its card or the outer canvas."""
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    errors = []
    gap_reports = []

    def display_box(region):
        x, y, w, h = region
        left, bottom = ax.transAxes.transform((x, y))
        right, top = ax.transAxes.transform((x + w, y + h))
        return left, bottom, right, top

    def outside(artist, region, tolerance=2.5):
        left, bottom, right, top = display_box(region)
        box = artist.get_window_extent(renderer)
        return (
            box.x0 < left - tolerance
            or box.x1 > right + tolerance
            or box.y0 < bottom - tolerance
            or box.y1 > top + tolerance
        )

    outer = (0.008, 0.045, 0.984, 0.90)
    for artist in TEXT_ARTISTS:
        if outside(artist, outer, tolerance=4.0):
            errors.append(f"outer overflow: {artist.get_text()!r}")
    for artist, region, name in BOUNDED_TEXT:
        if outside(artist, region):
            errors.append(f"{name} overflow: {artist.get_text()!r}")
    for artist, left_anchor, required_points, name in GAP_CHECKS:
        anchor_x = ax.transAxes.transform((left_anchor, 0))[0]
        gap_pixels = artist.get_window_extent(renderer).x0 - anchor_x
        required_pixels = renderer.points_to_pixels(required_points)
        actual_points = gap_pixels / renderer.points_to_pixels(1)
        gap_reports.append((name, actual_points, required_points))
        if gap_pixels < required_pixels:
            errors.append(
                f"{name} gap {actual_points:.2f}pt < {required_points:.2f}pt"
            )
    if errors:
        raise RuntimeError("\n".join(errors))
    print(f"TEXT_AUDIT_OK ({len(TEXT_ARTISTS)} labels)")
    for name, actual, required in gap_reports:
        print(f"GAP_AUDIT_OK {name}: {actual:.2f}pt >= {required:.2f}pt")


OUT.mkdir(parents=True, exist_ok=True)
fig = plt.figure(figsize=(7.0, 2.95), facecolor="white")
ax = fig.add_axes([0.008, 0.02, 0.984, 0.96])
ax.set_axis_off()

# Outer harness loop.
rounded(ax, 0.008, 0.045, 0.984, 0.90, fc="#fbfdff", ec=NAVY, lw=2.0, radius=0.035)
text(ax, 0.035, 0.915, "STREAMING MEMORY", ha="left", fontsize=7.2, weight="bold", color=NAVY)

y, h = 0.51, 0.31
xs = (0.025, 0.22, 0.415, 0.61, 0.805)
w = 0.17
stage(
    ax,
    xs[0],
    y,
    w,
    h,
    "1",
    "Item\narrives",
    ("extract item + type", "create K probes", "insert into store"),
    fc=BLUE_FILL,
    accent=BLUE,
)
stage(
    ax,
    xs[1],
    y,
    w,
    h,
    "2",
    "Serve &\nmeter",
    ("retrieve top-k", r"count uses $m_i$", r"forecast reuse $\hat n_i$"),
    fc=CREAM,
    accent=ORANGE,
)
stage(
    ax,
    xs[2],
    y,
    w,
    h,
    "3",
    "Option\ngate",
    ("price trial value", "compare write cost", "enqueue if positive"),
    fc="#f4effd",
    accent="#8057b7",
)
stage(
    ax,
    xs[3],
    y,
    w,
    h,
    "4",
    "Batch\nwrite",
    ("consolidate queue", "LoRA + replay", "meter write FLOPs"),
    fc=RED_FILL,
    accent=RED,
)
stage(
    ax,
    xs[4],
    y,
    w,
    h,
    "5",
    "Fresh\nverification",
    ("closed-book re-probe", r"measure realized $\alpha_i$", "keep or roll back"),
    fc=GREEN_FILL,
    accent=GREEN,
)

for left, right in zip(xs[:-1], xs[1:]):
    arrow(ax, (left + w + 0.003, y + h / 2), (right - 0.004, y + h / 2))

# Central measured-state bank, echoing HarnessBank's semantic table.
bank_x, bank_y, bank_w, bank_h = 0.285, 0.14, 0.43, 0.245
rounded(ax, bank_x, bank_y, bank_w, bank_h, fc=CREAM, ec=NAVY, lw=1.35, radius=0.018)
text(ax, bank_x + bank_w / 2, bank_y + bank_h - 0.035, "Measured policy state", weight="bold", fontsize=7.2)

columns = (
    (r"$F(\alpha)$", "verified write efficacy", "trial outcomes"),
    (r"$\hat h,\hat\rho$", "retrieval + interference", "anchor probes"),
    (r"$\hat n_i$", "semantic reuse forecast", "query history"),
)
col_w = bank_w / 3
for index, (symbol, meaning, source) in enumerate(columns):
    cx = bank_x + index * col_w
    if index:
        ax.plot(
            [cx, cx],
            [bank_y + 0.025, bank_y + bank_h - 0.065],
            color="#d2c6a5",
            lw=0.7,
            transform=ax.transAxes,
        )
    text(ax, cx + col_w / 2, bank_y + 0.145, symbol, weight="bold", fontsize=8.0, color=NAVY)
    text(ax, cx + col_w / 2, bank_y + 0.100, meaning, fontsize=5.7)
    text(ax, cx + col_w / 2, bank_y + 0.058, source, fontsize=5.6, color=GREY, style="italic")

# Feedback from verification updates the bank.
arrow(
    ax,
    (xs[4] + w / 2, y - 0.005),
    (bank_x + bank_w, bank_y + bank_h / 2),
    color=GREEN,
    lw=1.8,
    rad=-0.22,
)
update_label = text(
    ax,
    0.82,
    0.34,
    "update empirical state",
    color=NAVY,
    fontsize=5.8,
    weight="bold",
    bbox={
        "boxstyle": "round,pad=0.22",
        "facecolor": GREEN_FILL,
        "edgecolor": GREEN,
        "linewidth": 0.6,
    },
)
GAP_CHECKS.append((update_label, bank_x + bank_w, 6.0, "update-state-label"))

# The bank informs the gate.
arrow(
    ax,
    (bank_x + bank_w / 2, bank_y + bank_h),
    (xs[2] + w / 2, y - 0.005),
    color=ORANGE,
    lw=1.8,
    rad=0.0,
)
text(ax, 0.50, 0.42, "price the next option", color="#9a5f0c", fontsize=5.9, weight="bold")

# Pass/rollback feedback around the outer loop.
arrow(
    ax,
    (xs[4] + w - 0.025, y + h - 0.005),
    (xs[1] + w / 2, y + h + 0.025),
    color=GREEN,
    lw=2.0,
    rad=0.14,
)
text(ax, 0.68, 0.855, "PASS: keep in weights", color=GREEN, fontsize=6.2, weight="bold")
rollback_arrow = arrow(
    ax,
    (xs[4] + 0.045, y + 0.005),
    (0.872, 0.463),
    color=RED,
    lw=1.5,
    rad=0.0,
)
rollback_box = rounded(
    ax,
    0.78,
    0.405,
    0.185,
    0.055,
    fc=RED_FILL,
    ec=RED,
    lw=0.8,
    radius=0.012,
    zorder=9,
)
rollback_label = text(
    ax,
    0.872,
    0.432,
    "ROLLBACK → external store",
    color=RED,
    fontsize=5.65,
    weight="bold",
    zorder=10,
)

# Exact decision rules from the manuscript.
rounded(ax, 0.015, 0.115, 0.245, 0.24, fc="white", ec=NAVY_2, lw=0.95)
text(ax, 0.137, 0.315, "Deterministic gates", weight="bold", color=NAVY, fontsize=6.8)
text(ax, 0.137, 0.263, r"candidate: $m_i \geq k_i^\ast$", fontsize=6.1)
text(
    ax,
    0.137,
    0.215,
    r"trial: $\hat n_i\tilde r_i \geq \lambda C_i+\hat\rho/\bar b$",
    fontsize=5.8,
)
text(ax, 0.137, 0.167, r"keep: $\alpha_i \geq \kappa_i=h-\lambda c_i/g_i$", fontsize=5.8)

if not (
    rollback_box.get_zorder() > rollback_arrow.get_zorder()
    and rollback_label.get_zorder() > rollback_box.get_zorder()
):
    raise RuntimeError("rollback label must render above its arrow")
print(
    "LAYER_AUDIT_OK rollback: "
    f"arrow={rollback_arrow.get_zorder()} < "
    f"box={rollback_box.get_zorder()} < "
    f"text={rollback_label.get_zorder()}"
)
audit_text(fig, ax)
fig.savefig(OUT / "when-to-weights-streaming-gate-v2.pdf")
fig.savefig(OUT / "when-to-weights-streaming-gate-v2.png", dpi=220)
plt.close(fig)
print(OUT / "when-to-weights-streaming-gate-v2.pdf")
