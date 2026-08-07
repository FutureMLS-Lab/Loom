---
name: results-figure-replicates
description: Draw a results figure that shows the distribution behind every number it asserts — the aggregate in one panel, every individual run in the next, dashed reference lines carrying the published value in their own colour, and the statistics set inside the panel. The Nature-style evidence idiom, with bold lowercase panel keys and one figure-level legend. Use when the user runs /results-figure-replicates, asks to show replicates, spread, variance, per-trial or per-seed results, asks for a figure in the style of arXiv 2505.13803, or when a claim rests on a mean that hides its distribution. Read the results-figure skill first; this is that plus one idea.
disable-model-invocation: true
---

# results-figure-replicates

## The one idea

**Every number the figure asserts is drawn together with the distribution it came from.** A mean is a claim about a sample; this style puts the sample on the page next to it.

Three devices follow from that, and they are the whole style:

1. **The aggregate and the replicates side by side.** Left panel the fitted curve or the family means, right panel the same quantity with every run drawn.
2. **A dashed reference line carrying the published value, with the number written in the line's own colour.** The reader never works out which line a figure belongs to, and never leaves the panel to find what is being beaten.
3. **The statistics inside the panel, right-aligned.** *n*, the spread, the step sizes, the significance count. Not three pages away in the body text.

Everything in [results-figure](../results-figure/SKILL.md) still applies — same palette, fonts, widths, compliance. Read it first.

## When it is worth it, and when it is not

Use it when a headline claim rests on an average: *tight*, *flat*, *stable across seeds*, *consistent across datasets*. Those are all claims about a distribution, and a line through the means neither supports nor refutes them.

Do not use it when there is one deterministic number per configuration, when there are fewer than about five replicates per cell (a strip of three dots is noise, quote the range in the caption instead), or when the spread is genuinely uninteresting and the panel would spend a third of the figure saying so.

## Getting the replicates out

This is the step that actually costs something. **Experiment scripts almost always average before they write.** The paper's own sweep computes twelve runs per cell and stores their mean, so the spread is not in the repository and no plotting change can recover it.

The safe way to get it back, without touching the paper's code:

```
- [ ] 1. Read the experiment script and note the seed, the loop order, and the trial count
- [ ] 2. Copy the loop into a new script that keeps the individual values
- [ ] 3. Keep the generator order identical -- the RNG stream depends on it
- [ ] 4. Assert your per-cell means equal the committed result file, cell by cell
- [ ] 5. Only then draw anything
```

Step 4 is what makes this legitimate rather than a second, differently-seeded experiment quietly replacing the first. The worked example reproduces all 84 cells of the paper's file exactly and says so when it runs. If they do not match, the loop order is wrong; fix that before plotting.

## What tends to fall out

Both of these came out of the worked example, and both had been invisible for the life of the paper:

- **Two of the seven metric families are deterministic** — every one of their twelve runs identical. The mean-only figure gave them the same standing as families with real variance.
- **The quantity is not flat, it saturates.** It climbs 2.17 → 3.05 with the steps per doubling shrinking to +0.06. Bounded, which is what the theorem needs, but not the same word.

Expect the style to change what the paper can honestly say. That is the point of it, and it is worth telling the author rather than quietly picking the axis that hides it.

## The axis tension, which is real

To make twelve points per cell visible you have to zoom the axis, and a zoomed axis makes a mild slope look dramatic. The paper's original figure runs the axis from 0 and the curves look flat; the replicate version starts near the data and the same curves visibly climb. Neither is a lie and the choice changes what the reader concludes.

Resolve it explicitly, and say which you did:

- zoom and reword the claim from *flat* to *saturating* — usually right, since the honest baseline is the alternative being beaten, not zero;
- keep the axis at zero and put the spread in a separate panel at its own scale;
- plot the quantity normalised by its value at the largest setting, which makes flatness the thing being measured.

## The kit

`scripts/replicate_style.py` re-exports all of `plot_style`, so import from it alone. `scripts/plot_style.py` is a symlink to the sibling skill's copy.

```python
import replicate_style as rs
from replicate_style import WIDE, GREY, plt

fig, ax = plt.subplots(1, 2, figsize=(WIDE, 2.85))
fig.subplots_adjust(...)                          # not bbox_inches="tight"
ys = rs.strip(ax[1], [(label, values, colour), ...])   # every run, mean as a tick
rs.vref(ax[1], mu, r"$\bar q/k = 3.05$")               # dashed, value in its colour
rs.refline(ax[0], 2.0, "$2k$ — prior")                 # horizontal baseline
rs.statblock(ax[0], ["doubling families", "..."])      # stats inside the panel
rs.panel_key(ax[0], "a")                               # bold lowercase, outside
rs.bottom_legend(fig, handles)                         # one legend under it all
rs.save(fig, path); rs.report(...)
```

`strip()` returns the row y positions, so a subset can be shaded or bracketed — the example uses that to mark the two families the theorem does not cover.

See [example.py](example.py) for the whole figure and `example.png` for what it should look like.

## Pitfalls

**Filled markers turn replicates into a blob.** `strip()` uses hollow ones with jitter for that reason. If a cell still reads as a smear, the panel wants fewer rows, not smaller markers.

**A collapsed row looks like a bug.** When every replicate of a group is identical they land on one mark. Annotate it — the example writes "all 12 runs identical" beside those rows — or a reader assumes the plotting broke.

**Do not average across things the theory treats differently.** The example's summary line is the mean over the five families with bounded doubling dimension only, because nothing is proved for the other two; folding all seven into one number would be a claim the paper does not make. Mark the excluded rows on the figure.

**A strip plot with a y-axis that means nothing.** If replicate index carries no information, do not give it ticks and a label — that dresses a strip plot as a scatter. Name the *groups* on the axis instead.

**Every panel needs its own n.** "mean of 12 trials" and "mean over seven families, 12 trials each" are different numbers. Put whichever it is in the axis label or the statblock.

**One legend, under the figure.** With replicates drawn there is no free corner left in any panel. Do not shrink the legend to fit; move it out with `bottom_legend()`.
