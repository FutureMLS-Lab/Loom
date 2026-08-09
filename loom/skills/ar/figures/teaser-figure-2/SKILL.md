---
name: teaser-figure-2
description: Draw a paper's page-one teaser in the unadorned conference idiom — white ground, no tinted panels, the objects themselves drawn rather than named, panel names underneath as "(a) Obstacle: ...", and a real measured chart as the result panel. This is the SAM / FlashAttention look, and the second of this repo's two teaser styles. Emits a full-width vector PDF with embedded fonts. Use when the user runs /teaser-figure-2, asks for the plain, unadorned, second or "v2" teaser style, names SAM or FlashAttention as the reference, or wants a Figure 1 whose panels draw the object instead of describing it in boxes.
disable-model-invocation: true
---

# teaser-figure-2

## Which of the two styles this is

This repo has two teaser skills and they are not versions of each other.

| | `teaser-figure-1` | `teaser-figure-2` (this one) |
|---|---|---|
| ground | tinted panel per column, coloured title pill | white, thin vertical rules |
| panel name | pill on the top edge | `(a) Obstacle: ...` underneath |
| box contents | a bold title and a line of prose | a word, or nothing — it is a drawing |
| result panel | text cards carrying the numbers | a chart with an axis and units |
| where the prose goes | inside the figure | the LaTeX caption |

Choose this one when the paper has **something concrete to draw** — a metric, a matrix, a trace, a table it never builds — and **a measured number** for the last panel. Choose the other when the contribution is an argument with no drawable object, or when the figure has to stand alone with no caption under it.

The trade this style makes: it is unreadable without its caption, and excellent with one. Do not use it for a figure that will be shown on a slide by itself.

## The red line

**Every number, name and claim comes from the paper's own text, macros or result files.** This style makes that harder, not easier: a chart with an axis invites the reader to trust a measurement, so the measurement has to be real and the condition attached to it has to be on the page.

- Label every bar with the condition it was measured under. `89.5` means nothing; `89.5, distortion 2.1` is a claim.
- Keep the qualifier that makes the bound true. `O(k)` is not `O(k) on doubling metrics`.
- State what was averaged over. "mean of 12 trials" and "mean over seven metric families, 12 trials each" are different numbers.
- Never draw a schematic that implies a stronger construction than the paper proves. If the two instances in the paper are four points, draw four points.

## The three panels

Same skeleton as the other style — **why**, **how**, **what** — but each panel is a drawing rather than a slide.

**(a) the obstacle.** Draw the actual object that makes it hard. SAM shows real photographs and the four real prompt types instead of writing "prompts can be points, boxes, masks or text"; the worked example shows the paper's two four-point metrics rather than saying they exist. If the paper's difficulty is that two things look identical but behave differently, draw them both — the reader does the comparison, which is far stronger than being told.

**(b) the mechanism.** Draw the data, not a block diagram. FlashAttention draws Q, K and V as strips of cells with their dimensions on them, and the two loops as two families of coloured arrows. If the contribution is that something is *never computed*, draw it as a dashed empty outline — `dashed_table()` exists for exactly this, and it is the single most transferable device in either reference figure.

**(c) what it buys.** A chart, with an axis, with units. Two or three bars is usually the whole story: the baseline, yours, and the expensive option that yours nearly matches. Hang the headline factor between two bar tops with `ratio()`. Put the sample size and conditions in a small italic line underneath.

## Visual grammar

- **Size**: 7.0 × 2.5 in for a `figure*`. Panels split roughly 190 / 250 / 210 — the mechanism gets the width.
- **Colour has one job per figure.** In the worked example: grey is what the algorithm can observe, red is what it cannot and what it has to pay for, green is the result. FlashAttention spends red and blue solely on the two loops. Resist using colour for panel identity here; there are no panels to identify.
- **Text**: nothing below 5.5 pt. Labels sit on the objects they name, not in a legend, wherever there is room.
- **Density**: far lower than the other style. If a panel needs three sentences, they belong in the caption.

## Workflow

```
- [ ] 1. Read the paper: abstract, method section, results table, and the scripts behind them
- [ ] 2. Find the drawable object in each panel; if (a) or (b) has none, use teaser-figure-1 instead
- [ ] 3. Find the numbers for (c) in a result file, and note what they were averaged over
- [ ] 4. Write <name>_overview.py against scripts/plain_style.py
- [ ] 5. Render; fix every OVERFLOW, TOO LONG and missing-glyph line
- [ ] 6. Read the rendered PNG back and look for collisions the audit cannot see
- [ ] 7. Check the PDF is 7.0 x 2.5 in with no Type 3 fonts
- [ ] 8. Re-check every number against its source file
```

Step 2 is the gate. This style fails badly when forced onto a paper with nothing to draw — it degenerates into three sparse panels of floating text, which is worse than the tinted version.

## The kit

`scripts/plain_style.py`. It re-exports everything shared with the other style, so a figure script imports from it alone. `scripts/overview_style.py` is a symlink to the other skill's copy; there is one real copy in the repo.

```python
fig, ax = canvas(7.0, 2.50)                       # data coords = 1/100 inch
dividers(ax, (207, 476))                          # the thin vertical rules
caption(ax, cx, ytop, [l1, l2], maxw)             # italic lead-in, lines sized together
sublabel(ax, cx, 14, "a", "Obstacle", "...")      # the under-panel name
dashed_table(ax, x, y, n, cell, filled={(0,1)})   # -> (x0, y0, x1, y1) of the drawn box
chart(ax, x, y, w, h, series, ymax, ticks=(0,250),
      ylabel="...")                               # -> [(x, top)] per bar
ratio(ax, x, y0, y1, "5.5×")                      # the factor between two bar tops
swatch(ax, x, y, "label", RED, dashed=False)      # a mark used in the panel, named
arrow(ax, a, b, RED, rad=-0.16)                   # rad bends it
tag(ax, x, y, "(1+ε) × tallest fresh", GREY)      # pill label for a line or arrow
text / measure / audit / save                     # as in teaser-figure-1
```

`chart()` is the piece to reach for first: `series` is `[(value, tone, name, note), ...]`, `note` being the condition the bar was measured under.

See [example.py](example.py) for the whole thing, and `example.png` for what it should look like.

## Pitfalls

**Auto-shrink bottoming out.** `fit()` stops at 4.8 pt and prints `TOO LONG`. Text that hits the floor is both too small to read and still overflowing. Shorten the string or widen the slot — never lower the floor. Roughly 3.7 canvas units per character at 6.1 pt, so a 108-wide slot holds about 29 characters.

**The under-label has to fit its own panel.** `sublabel()` centres the whole line, so a long one runs out of the narrow first panel and off the canvas. Keep it to a short noun phrase; `audit()` catches it.

**Missing glyphs.** TeX Gyre Heros has Greek and `× ≤ − ∞ ² ³ φ ℓ`, but not `⌈ ⌉ ⇔ ⋀ ⁴ ⁻ ₁ ✓ ✗`. Use mathtext: `$\lceil\log_2 n\rceil$`, `$\Leftrightarrow$`, `$\checkmark$`. Mathtext ignores bold, so wrap maths in a bold title as `\mathbf{}` or keep the title free of it.

**Do not duplicate a figure the paper already has.** Check `latex/figs/` first. The worked example uses a bar comparison precisely because the paper's own Figure 1 is already the distortion-against-queries scatter, and a teaser repeating it wastes the page.

**Font type.** `pdf.fonttype=42` is set for you; matplotlib's default Type 3 is forbidden by the AAAI kit. Verify with PyMuPDF: `[f for f in page.get_fonts(full=True) if f[2] == "Type3"]` must be empty.
