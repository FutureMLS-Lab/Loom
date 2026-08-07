---
name: results-figure
description: Draw a results figure for one of this repo's papers — a chart carrying measurements, in the house style the existing figures already use: Okabe-Ito colours, the paper's serif face, TrueType output, references drawn as labelled baselines rather than legend entries, and a printed summary of every number the figure asserts. Use when the user runs /results-figure, or asks for a results plot, an experiment figure, a scaling or ablation chart, or asks to fix, restyle or check an existing figure in a paper's latex/figs. Not for teasers or schematics — those are teaser-figure and teaser-figure-plain.
disable-model-invocation: true
---

# results-figure

## What this covers

The **evidence** half of figure-making: a chart that carries measurements, lives in the results section or the supplement, and is read by someone deciding whether to believe a claim. The teaser skills (`teaser-figure`, `teaser-figure-plain`) cover the other half, schematics that explain an idea. The two sets of rules conflict — decoration is necessary in a teaser and is noise here — so do not carry technique across.

There is also a sibling of this skill, `results-figure-replicates`, for when per-trial data exists and the point is the spread rather than the aggregate. Read this one first; that one is this plus one idea.

## The red line

**Everything plotted comes from a result file, and the script says so.** No number is retyped from the paper into the plotting script, and no series is smoothed, clipped or rescaled without the axis saying it.

- Load from the `.json`/`.csv` the experiment wrote. If the figure needs a quantity the result file does not have, change the experiment, not the plot.
- End the script with `report(...)`, printing the numbers the figure asserts. The caption and the body quote those numbers; the printout is what they get checked against without reopening the PDF.
- Assert the invariants the figure relies on while computing (`assert row["T"] == 2 * row["L"] - 1`). A figure that silently drew wrong data is worse than one that failed.
- Cache anything slow to a `.json` beside the script, with a `--recompute` flag, so the figure is reproducible without a 40-second wait.

## House conventions

Import `scripts/plot_style.py` before pyplot; it applies all of this.

| | |
|---|---|
| width | `WIDE = 7.0` in for `figure*`, `COL = 3.3` in for one column. Nothing in between. |
| fonts | TeX Gyre Termes to match the body face, DejaVu Serif as fallback. `pdf.fonttype = 42` — the AAAI kit forbids Type 3, and matplotlib emits it by default. |
| sizes | body 8, axis labels 8, ticks 7, legend 6.6, annotations 6.4–6.6. Nothing smaller than 6. |
| colour | Okabe-Ito only (`BLUE ORANGE GREEN VERM SKY PURPLE YELLOW`), which survives every common colour-vision deficiency. Never encode by colour alone — pair it with a marker or a dash pattern. |
| spines | top and right off, grid dotted `#bbbbbb` at alpha 0.6. |
| output | `save(fig, "../latex/figs/name.pdf")`. Scripts live in `code/`, figures land in `latex/figs/`. |

## Practices that carry the argument

**Draw the baseline the claim is against, and name it on the line.** Prior work, a proved bound, chance level, the quadratic alternative. `refline()` puts the label on the line rather than in the legend, so the comparison needs no lookup. A results figure whose reader has to remember what to compare against has failed.

**Anchor reference curves at the first data point.** The example's polynomial guides all start where the measurement starts, so the eye compares *growth rates* and not constants. On a log axis an exponential is then straight and every polynomial visibly bends away.

**Shade the gap the paragraph is about.** If the text says two quantities diverge, `fill_between` them.

**Annotate in the series' own colour, with an offset.** `xytext=(dx, dy), textcoords="offset points"` and `color=` the same as the line. This replaces most legend entries.

**Merge series that coincide exactly.** The existing scaling figure draws HST *b*=2 and *b*=4 as one line labelled for both, because they agree to the last digit — overplotting them would suggest one is hiding the other.

**Write log ticks plainly.** `logticks(ax, [10, 100, 1000])` sets the scale, the ticks and plain labels, and kills the unlabelled minor ticks that read as noise at 7 pt.

## Workflow

```
- [ ] 1. Find the result file and read what it actually contains
- [ ] 2. Say in one sentence what the figure has to make believable
- [ ] 3. Identify the baseline that sentence is implicitly against; it goes on the plot
- [ ] 4. Write <name>.py in the paper's code/, output to ../latex/figs/
- [ ] 5. Render, then look at the PNG at 100% -- overlaps do not show in the code
- [ ] 6. Check the printed report against the caption and the body text
- [ ] 7. Confirm the PDF is exactly WIDE or COL wide, with no Type 3 fonts
```

Step 3 is the one that gets skipped. A figure showing only your own numbers is a description; a figure showing your numbers against the thing they beat is an argument.

## The kit

```python
import plot_style as ps
from plot_style import BLUE, ORANGE, GREEN, VERM, SKY, PURPLE, GREY, WIDE, COL, plt

fig, ax = plt.subplots(1, 2, figsize=(WIDE, 2.45))
fig.subplots_adjust(left=.07, right=.99, top=.94, bottom=.17, wspace=.26)
ps.logticks(ax[0], [20, 50, 100])                  # log scale, plain labels
ps.refline(ax[0], k*(k-1)/2, "$k(k-1)/2$, exact")  # baseline named on the line
ax[0].legend(loc="upper left", ncol=2, **ps.LEGEND)
ps.save(fig, "../latex/figs/name.pdf")             # warns if the size is wrong
ps.report(k_range="8..128", mean_qk="2.17 -> 3.05")
```

See [example.py](example.py) for a complete figure, drawn from paper 45654's own cached results, and `example.png` for what it should look like.

## Pitfalls

**`bbox_inches="tight"` silently changes the width.** This repo already has the bug: `scaling.pdf` is declared `figsize=(7.0, 2.45)` but saved tight, so the file is 5.90 in wide, and the supplement includes it at `width=\textwidth`. LaTeX scales it back up by 1.19, so its 8 pt labels render around 9.5 pt — visibly larger than `frontier.pdf` two pages earlier. Set margins with `subplots_adjust` and leave `tight` off; `save()` warns when the output is not the size that was asked for.

**Bars on a log axis.** Bar length stops being proportional to the value, so the comparison the chart invites is wrong. Use points, or a linear axis, or plot the ratio.

**A grid of subplots with different axis ranges.** The layout invites cross-panel comparison and the ranges forbid it. Share the range or do not use a grid.

**Legends that cover data.** Prefer direct labelling. When a legend is unavoidable and there is no free corner, put one legend under the whole figure (`fig.legend(..., loc="lower center", ncol=n)`) rather than one per panel.

**Type 3 fonts.** Verify rather than assume: `[f for f in fitz.open(p)[0].get_fonts(full=True) if f[2] == "Type3"]` must be empty. Also note the author kit forbids pgfplots and forbids cropping with `\includegraphics[trim=...]`; crop by fixing the figure, not the include.

**Do not draw a figure the paper already has.** Check `latex/figs/` first.
