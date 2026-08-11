"""SkillCorpus-inspired two-lane framework teaser.

The top lane shows how interaction-derived updates are built. The bottom lane
shows matched-recall selection and association-quality evaluation. All names
and measurements come from committed paper artifacts.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib as mpl
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT.parent.parent / "figure-redraw-v2"
MANIFEST = ROOT / "experiments" / "sia" / "data" / "round2_report_manifest.json"
AGG05 = ROOT / "experiments" / "sia" / "results" / "round2_report" / "aggregate.json"
AGG15 = ROOT / "experiments" / "sia" / "results" / "round3_15b" / "aggregate_high.json"

NAVY = "#12365a"
INK = "#21344b"
MUTED = "#6c7888"
CREAM = "#fff8e8"
CREAM_EDGE = "#e4bd68"
BLUE_BG = "#edf8ff"
BLUE_EDGE = "#83bee1"
TEAL = "#0f8f95"
TEAL_FILL = "#e8f7f7"
PURPLE = "#7656ad"
PURPLE_FILL = "#f2edfb"
GREEN = "#178c43"
GREEN_FILL = "#e8f6ed"
RED = "#d94841"
RED_FILL = "#fff0ef"
ORANGE = "#db791d"
ORANGE_FILL = "#fff2e4"
GREY = "#7d8793"
GREY_FILL = "#f1f3f5"

mpl.rcParams.update(
    {
        "font.family": "DejaVu Sans",
        "font.size": 7,
        "pdf.fonttype": 42,
        "ps.fonttype": 42,
    }
)


def rounded(ax, x, y, w, h, *, fc="white", ec=NAVY, lw=1.0, radius=0.018):
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
        zorder=2,
    )
    ax.add_patch(patch)
    return patch


def text(ax, x, y, value, **kwargs):
    defaults = dict(
        transform=ax.transAxes,
        ha="center",
        va="center",
        color=INK,
        fontsize=6.4,
        zorder=8,
    )
    defaults.update(kwargs)
    return ax.text(x, y, value, **defaults)


def arrow(ax, start, end, *, color=NAVY, lw=1.25, rad=0.0):
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


def section_title(ax, x, y, title, width, fontsize=7.1):
    text(
        ax,
        x,
        y,
        title.upper(),
        family="DejaVu Serif",
        weight="bold",
        fontsize=fontsize,
        color=NAVY,
        linespacing=0.9,
    )
    ax.plot(
        [x - width / 2, x + width / 2],
        [y - 0.03, y - 0.03],
        color=NAVY,
        lw=0.6,
        transform=ax.transAxes,
    )
    ax.plot([x, x], [y - 0.03, y - 0.038], color=NAVY, lw=1.2, transform=ax.transAxes)


def rev(payload, method):
    return 100 * payload["methods"][method]["test_mean"]["reverse_accuracy"]


manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
agg05 = json.loads(AGG05.read_text(encoding="utf-8"))
agg15 = json.loads(AGG15.read_text(encoding="utf-8"))
path0 = manifest["paths"][0]
head, middle = path0["head"], path0["middle"]
assert path0["facts"][0]["head"] == head and path0["facts"][0]["tail"] == middle

results05 = {
    "SFT": rev(agg05, "transcript"),
    "Para.": rev(agg05, "paraphrase"),
    "KL": rev(agg05, "opcd_offpolicy"),
    "Oracle": rev(agg05, "oracle"),
}
oracle15 = rev(agg15, "oracle")
transcript15 = rev(agg15, "transcript")

OUT.mkdir(parents=True, exist_ok=True)
fig = plt.figure(figsize=(7.0, 3.0), facecolor="white")
ax = fig.add_axes([0.008, 0.02, 0.984, 0.96])
ax.set_axis_off()

# Two large lanes mirror SkillCorpus's build/use split.
rounded(ax, 0.008, 0.53, 0.984, 0.43, fc=CREAM, ec=CREAM_EDGE, lw=0.9, radius=0.02)
rounded(ax, 0.008, 0.055, 0.984, 0.43, fc=BLUE_BG, ec=BLUE_EDGE, lw=0.9, radius=0.02)

text(ax, 0.035, 0.87, "BUILD\nUPDATE", ha="left", family="DejaVu Serif", weight="bold", fontsize=8.0, color=NAVY)
text(ax, 0.035, 0.39, "TEST\nASSOCIATION", ha="left", family="DejaVu Serif", weight="bold", fontsize=8.0, color=NAVY)

# ----------------------------------------------------------------- top lane
section_title(ax, 0.205, 0.90, "Interaction", 0.11)
rounded(ax, 0.115, 0.61, 0.16, 0.22, fc="white", ec=NAVY, lw=0.9)
text(ax, 0.132, 0.79, "one new fact", ha="left", weight="bold", color=NAVY)
text(ax, 0.132, 0.735, f"Q: Whom does {head}", ha="left", fontsize=5.7)
text(ax, 0.132, 0.695, "mentor?", ha="left", fontsize=5.7)
text(ax, 0.132, 0.64, f"A: {middle}", ha="left", fontsize=6.0, weight="bold")

section_title(ax, 0.435, 0.90, "Construct updates", 0.16)
method_cards = (
    ("1", "Transcript", GREY_FILL, GREY),
    ("2", "Paraphrase", ORANGE_FILL, ORANGE),
    ("3", "Context KL", RED_FILL, RED),
    ("4", "Inverse oracle", GREEN_FILL, GREEN),
)
for index, (number, name, fill, edge) in enumerate(method_cards):
    x = 0.315 + index * 0.065
    rounded(ax, x, 0.625, 0.055, 0.19, fc=fill, ec=edge, lw=0.9, radius=0.012)
    rounded(ax, x + 0.013, 0.765, 0.029, 0.032, fc=edge, ec=edge, lw=0, radius=0.006)
    text(ax, x + 0.0275, 0.781, number, color="white", weight="bold", fontsize=5.8)
    text(ax, x + 0.0275, 0.695, name, rotation=90, fontsize=5.7, weight="bold", color=edge)

section_title(ax, 0.655, 0.90, "Adapt", 0.09)
rounded(ax, 0.605, 0.63, 0.12, 0.18, fc=PURPLE_FILL, ec=PURPLE, lw=1.0)
text(ax, 0.665, 0.755, "same frozen base", fontsize=5.7, color=PURPLE)
text(ax, 0.665, 0.705, "+ LoRA adapter", fontsize=7.0, weight="bold", color=PURPLE)
text(ax, 0.665, 0.655, "one adapter / method", fontsize=5.6, color=MUTED)

section_title(ax, 0.86, 0.90, "Candidate\nmemories", 0.15, fontsize=6.5)
rounded(ax, 0.77, 0.60, 0.18, 0.235, fc=GREEN_FILL, ec=GREEN, lw=1.1)
text(ax, 0.86, 0.785, "updated weights", fontsize=7.2, weight="bold", color=GREEN)
for row in range(3):
    for col in range(6):
        ax.add_patch(
            Rectangle(
                (0.795 + col * 0.022, 0.665 + row * 0.028),
                0.015,
                0.018,
                transform=ax.transAxes,
                facecolor=("#8ed3a8" if (row + col) % 3 else "white"),
                edgecolor=GREEN,
                linewidth=0.45,
            )
        )
text(ax, 0.86, 0.635, "forward-only vs inverse labels", fontsize=5.35, color=MUTED)

arrow(ax, (0.28, 0.715), (0.305, 0.715), color=NAVY)
arrow(ax, (0.58, 0.715), (0.60, 0.715), color=NAVY)
arrow(ax, (0.73, 0.715), (0.765, 0.715), color=NAVY)

# Connector from built candidates to evaluation.
arrow(ax, (0.86, 0.595), (0.51, 0.465), color=TEAL, lw=1.6, rad=0.18)
text(ax, 0.69, 0.515, "evaluate every adapter", color=TEAL, weight="bold", fontsize=5.9, rotation=-10)

# --------------------------------------------------------------- bottom lane
section_title(ax, 0.205, 0.42, "Match\ndirect recall", 0.14, fontsize=6.4)
rounded(ax, 0.12, 0.145, 0.17, 0.205, fc="white", ec=BLUE_EDGE, lw=1.0)
text(ax, 0.205, 0.305, "calibration facts only", weight="bold", color=NAVY)
for index, value in enumerate((0.30, 0.48, 0.68, 0.84)):
    ax.plot(
        [0.145, 0.145 + value * 0.11],
        [0.265 - index * 0.035] * 2,
        color=(GREY, ORANGE, RED, GREEN)[index],
        lw=3.0,
        solid_capstyle="round",
        transform=ax.transAxes,
    )
ax.plot([0.24, 0.24], [0.16, 0.285], "--", color=TEAL, lw=1.0, transform=ax.transAxes)
text(ax, 0.24, 0.125, "common band", color=TEAL, fontsize=5.6)

section_title(ax, 0.405, 0.42, "Select\ncheckpoint", 0.13, fontsize=6.4)
rounded(ax, 0.33, 0.15, 0.15, 0.195, fc=TEAL_FILL, ec=TEAL, lw=1.0)
text(ax, 0.405, 0.295, "earliest checkpoint", color=TEAL, weight="bold")
text(ax, 0.405, 0.245, "inside the shared", fontsize=5.8)
text(ax, 0.405, 0.210, "direct-recall band", fontsize=5.8)
rounded(ax, 0.365, 0.165, 0.08, 0.035, fc="white", ec=TEAL, lw=0.7)
text(ax, 0.405, 0.182, "no test peeking", fontsize=5.3, color=TEAL)

section_title(ax, 0.59, 0.42, "Probe\nusability", 0.11, fontsize=6.4)
rounded(ax, 0.525, 0.15, 0.13, 0.195, fc=PURPLE_FILL, ec=PURPLE, lw=1.0)
text(ax, 0.59, 0.296, "held-out probes", color=PURPLE, weight="bold")
text(ax, 0.59, 0.25, "reverse QA", fontsize=6.1)
text(ax, 0.59, 0.215, "two-hop QA", fontsize=6.1)
text(ax, 0.59, 0.175, "paired bootstrap", fontsize=5.5, color=MUTED)

section_title(ax, 0.82, 0.42, "Measured\nverdict", 0.13, fontsize=6.4)
rounded(ax, 0.705, 0.105, 0.235, 0.275, fc="white", ec=GREEN, lw=1.1)
text(ax, 0.822, 0.342, "reversal at matched 0.5B recall", fontsize=5.55, color=MUTED)
bar_x = (0.74, 0.79, 0.84, 0.89)
bar_colors = (GREY, ORANGE, RED, GREEN)
max_h = 0.14
for x, (name, value), color in zip(bar_x, results05.items(), bar_colors):
    height = max(0.006, max_h * value / 25.0)
    ax.add_patch(
        Rectangle(
            (x - 0.013, 0.17),
            0.026,
            height,
            transform=ax.transAxes,
            facecolor=color + "22",
            edgecolor=color,
            linewidth=0.9,
        )
    )
    text(ax, x, 0.17 + height + 0.023, f"{value:.1f}", fontsize=5.6, color=color, weight="bold")
    text(ax, x, 0.143, name, fontsize=4.9, rotation=20)
text(
    ax,
    0.822,
    0.112,
    f"1.5B oracle {oracle15:.1f} vs transcript {transcript15:.1f}",
    fontsize=5.1,
    color=GREEN,
    weight="bold",
)

arrow(ax, (0.295, 0.245), (0.325, 0.245), color=NAVY)
arrow(ax, (0.485, 0.245), (0.52, 0.245), color=NAVY)
arrow(ax, (0.66, 0.245), (0.70, 0.245), color=NAVY)

fig.savefig(OUT / "self-distillation-teaser-v2.pdf")
fig.savefig(OUT / "self-distillation-teaser-v2.png", dpi=220)
plt.close(fig)

print(
    json.dumps(
        {
            "fact": f"{head}->{middle}",
            "reversal_05": {name: round(value, 3) for name, value in results05.items()},
            "oracle_15": round(oracle15, 3),
            "transcript_15": round(transcript15, 3),
            "output": str(OUT / "self-distillation-teaser-v2.pdf"),
        },
        indent=2,
    )
)
