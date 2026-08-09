"""DASH-inspired three-stage teaser for the regret-optimal write gate.

Every plotted measurement is loaded from the existing experiment artifacts.
This writes versioned candidates only; it never overwrites the paper figure.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle


HERE = Path(__file__).resolve().parent
CODE = HERE.parent
RESULTS = CODE / "results" / "results.json"
OUT = HERE.parents[3] / "figure-redraw-v2"

INK = "#14213d"
MUTED = "#697386"
GRID = "#d6dbe3"
CREAM = "#fff8e8"
BLUE = "#2878b5"
BLUE_FILL = "#e8f2fb"
RED = "#ef4444"
RED_FILL = "#fff0ef"
GREEN = "#22a447"
GREEN_FILL = "#edf9ef"
GREY = "#7d8793"
GREY_FILL = "#f1f3f5"

mpl.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 7.2,
        "axes.unicode_minus": False,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
)


def load_measurements() -> tuple[dict[str, tuple[float, float]], np.ndarray]:
    rows = json.loads(RESULTS.read_text(encoding="utf-8"))

    def metric(arm: str, version: str | None = None) -> tuple[float, float]:
        found = [
            row
            for row in rows
            if row["schedule"] == "zipf"
            and row["arm"] == arm
            and row.get("tag", "") in ("cg", "cgv3")
            and row["stream"].endswith("g")
            and (version is None or row.get("version") == version)
            and (
                arm != "gate"
                or (
                    row.get("variant") == "full"
                    and abs(row["lam"] - 2e-15) < 1e-18
                )
            )
        ]
        assert len(found) == 3, (arm, version, len(found))
        accuracy = 100 * float(np.mean([row["acc"] for row in found]))
        write_pflops = float(np.mean([row["flops_update"] for row in found])) / 1e15
        return accuracy, write_pflops

    measured = {
        "never": metric("never"),
        "gate": metric("gate", "v3"),
        "always": metric("always"),
    }
    efficacy: list[float] = []
    for path in glob.glob(str(CODE / "logs" / "summary_lme_s?g_zipf_always_cg.json")):
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        efficacy.extend(
            item["alpha"]
            for item in payload["consolidations"]
            if item["alpha"] is not None
        )
    assert len(efficacy) > 3000
    return measured, np.asarray(efficacy, dtype=float)


def rounded(ax, x, y, w, h, *, fc="white", ec=INK, lw=1.25, radius=0.025):
    patch = FancyBboxPatch(
        (x, y),
        w,
        h,
        boxstyle=f"round,pad=0.008,rounding_size={radius}",
        transform=ax.transAxes,
        facecolor=fc,
        edgecolor=ec,
        linewidth=lw,
        clip_on=False,
    )
    ax.add_patch(patch)
    return patch


def label(ax, x, y, text, **kwargs):
    defaults = dict(
        transform=ax.transAxes,
        ha="center",
        va="center",
        color=INK,
        fontsize=7,
        zorder=8,
    )
    defaults.update(kwargs)
    return ax.text(x, y, text, **defaults)


def arrow(ax, start, end, *, color=INK, lw=1.2, rad=0.0):
    patch = FancyArrowPatch(
        start,
        end,
        arrowstyle="-|>",
        mutation_scale=8,
        linewidth=lw,
        color=color,
        connectionstyle=f"arc3,rad={rad}",
        transform=ax.transAxes,
        zorder=7,
    )
    ax.add_patch(patch)
    return patch


def panel(ax, x, w, title, subtitle):
    rounded(ax, x, 0.10, w, 0.82, fc="white", ec=INK, lw=1.45, radius=0.035)
    label(ax, x + w / 2, 0.875, title, fontsize=8.4, weight="bold")
    label(
        ax,
        x + w / 2,
        0.815,
        subtitle,
        fontsize=5.95,
        color=MUTED,
        style="italic",
        linespacing=0.95,
    )


measured, efficacy = load_measurements()
OUT.mkdir(parents=True, exist_ok=True)

fig = plt.figure(figsize=(7.0, 2.62), facecolor="white")
ax = fig.add_axes([0.012, 0.02, 0.976, 0.96])
ax.set_axis_off()

# ------------------------------------------------------------------ panel 1
x1, w1 = 0.01, 0.305
panel(ax, x1, w1, "1. Context carries rent", "each read pays; writes are irreversible")

# External store: a row of item cells.
rounded(ax, x1 + 0.045, 0.63, 0.21, 0.085, fc=BLUE_FILL, ec=BLUE, lw=1.0)
for index in range(7):
    ax.add_patch(
        Rectangle(
            (x1 + 0.061 + index * 0.026, 0.653),
            0.018,
            0.034,
            transform=ax.transAxes,
            facecolor="white",
            edgecolor=BLUE,
            linewidth=0.65,
        )
    )
label(ax, x1 + 0.15, 0.735, "external memory", color=BLUE, weight="bold")
label(ax, x1 + 0.15, 0.59, r"read rent: $\lambda c_i + (1-h)g_i$", fontsize=6.3)

# Costly weights.
for index in range(3):
    ax.add_patch(
        Rectangle(
            (x1 + 0.085 + index * 0.035, 0.305),
            0.028,
            0.068,
            transform=ax.transAxes,
            facecolor=RED_FILL,
            edgecolor=RED,
            linewidth=1.0,
        )
    )
label(ax, x1 + 0.15, 0.395, "model weights", color=RED, weight="bold")
label(ax, x1 + 0.15, 0.262, r"write price: $\lambda C_i+\rho$", fontsize=6.3)
arrow(ax, (x1 + 0.12, 0.57), (x1 + 0.13, 0.42), color=RED, rad=-0.08)
rounded(ax, x1 + 0.045, 0.145, 0.21, 0.08, fc=CREAM, ec="#c48a18", lw=0.8)
label(
    ax,
    x1 + 0.15,
    0.185,
    "unknown reuse + unknown efficacy\nmake every write a risky purchase",
    fontsize=5.35,
    color="#7a5510",
    linespacing=1.1,
)

# ------------------------------------------------------------------ panel 2
x2, w2 = 0.35, 0.30
panel(
    ax,
    x2,
    w2,
    "2. Verify before commit",
    "price an option using\nmeasured efficacy",
)

# Draw an efficacy histogram in axes coordinates.
hist, edges = np.histogram(np.clip(efficacy, 0, 1), bins=12, range=(0, 1))
hist = hist / max(hist.max(), 1)
hx, hy, hw, hh = x2 + 0.035, 0.49, 0.17, 0.23
for index, value in enumerate(hist):
    ax.add_patch(
        Rectangle(
            (hx + index * hw / len(hist), hy),
            hw / len(hist) - 0.002,
            hh * value,
            transform=ax.transAxes,
            facecolor="#a9cdec",
            edgecolor="none",
        )
    )
threshold_x = hx + 0.64 * hw
ax.plot(
    [threshold_x, threshold_x],
    [hy - 0.015, hy + hh + 0.02],
    "--",
    color=RED,
    lw=1.2,
    transform=ax.transAxes,
)
label(ax, hx + hw / 2, hy - 0.035, r"measured $F(\alpha)$, 3,820 writes", fontsize=5.8)
label(ax, threshold_x + 0.005, hy + hh + 0.035, r"$\kappa_i$", color=RED, fontsize=6.2)

rounded(ax, x2 + 0.215, 0.58, 0.058, 0.085, fc=CREAM, ec="#c48a18", lw=0.9)
label(ax, x2 + 0.244, 0.622, "trial", weight="bold", color="#7a5510")
arrow(ax, (x2 + 0.205, 0.62), (x2 + 0.215, 0.62), color="#c48a18")

rounded(ax, x2 + 0.075, 0.31, 0.15, 0.075, fc=GREEN_FILL, ec=GREEN, lw=0.9)
label(ax, x2 + 0.15, 0.348, r"keep if $\alpha_i\geq\kappa_i$", color=GREEN)
rounded(ax, x2 + 0.075, 0.19, 0.15, 0.075, fc=GREY_FILL, ec=GREY, lw=0.9)
label(ax, x2 + 0.15, 0.228, "otherwise roll back", color=GREY)
arrow(ax, (x2 + 0.244, 0.57), (x2 + 0.19, 0.39), color=GREEN, rad=0.08)
arrow(ax, (x2 + 0.244, 0.57), (x2 + 0.19, 0.27), color=GREY, rad=-0.08)
label(
    ax,
    x2 + 0.15,
    0.14,
    "fire only when expected reuse\nclears the option price",
    fontsize=5.35,
    color=MUTED,
    linespacing=1.05,
)

# ------------------------------------------------------------------ panel 3
x3, w3 = 0.685, 0.305
panel(
    ax,
    x3,
    w3,
    "3. Metered outcome",
    "three streams, congested retrieval\nall FLOPs counted",
)

names = ("never", "verify\ngate", "always")
keys = ("never", "gate", "always")
colors = (GREY, BLUE, RED)
fills = (GREY_FILL, BLUE_FILL, RED_FILL)
values = [measured[key][0] for key in keys]
base_x, base_y, chart_w, chart_h = x3 + 0.055, 0.32, 0.205, 0.35
ax.plot(
    [base_x, base_x + chart_w],
    [base_y, base_y],
    color=INK,
    lw=0.9,
    transform=ax.transAxes,
)
for index, (name, value, color, fill) in enumerate(
    zip(names, values, colors, fills)
):
    cx = base_x + 0.035 + index * 0.068
    height = chart_h * value / 25.0
    ax.add_patch(
        Rectangle(
            (cx - 0.018, base_y),
            0.036,
            height,
            transform=ax.transAxes,
            facecolor=fill,
            edgecolor=color,
            linewidth=1.1,
        )
    )
    label(ax, cx, base_y + height + 0.035, f"{value:.1f}", color=color, weight="bold")
    label(ax, cx, base_y - 0.045, name, fontsize=5.7, weight="bold")
    label(
        ax,
        cx,
        base_y - 0.083,
        f"{measured[keys[index]][1]:.1f} PF",
        fontsize=5.5,
        color=MUTED,
    )
label(ax, base_x - 0.015, base_y + chart_h / 2, "judged\naccuracy", fontsize=5.6, rotation=90)
ratio = measured["always"][1] / max(measured["gate"][1], 1e-12)
rounded(ax, x3 + 0.055, 0.13, 0.195, 0.085, fc=GREEN_FILL, ec=GREEN, lw=0.9)
label(
    ax,
    x3 + 0.152,
    0.172,
    f"same accuracy gain\n{ratio:.0f}× fewer write-FLOPs",
    fontsize=5.65,
    color=GREEN,
    weight="bold",
    linespacing=1.05,
)

fig.savefig(OUT / "when-to-weights-teaser-v2.pdf")
fig.savefig(OUT / "when-to-weights-teaser-v2.png", dpi=220)
plt.close(fig)

print(
    json.dumps(
        {
            "accuracy_percent": {key: round(value[0], 3) for key, value in measured.items()},
            "write_pflops": {key: round(value[1], 3) for key, value in measured.items()},
            "efficacy_n": int(len(efficacy)),
            "output": str(OUT / "when-to-weights-teaser-v2.pdf"),
        },
        indent=2,
    )
)
