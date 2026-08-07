---
name: teaser-figure
description: Draw a paper's page-one teaser — the three-panel problem/method/result schematic of tinted rounded boxes and arrows that explains a contribution at a glance. Emits a full-width vector PDF with embedded fonts, ready to drop into a LaTeX figure*. Use when the user runs /teaser-figure, or asks for a teaser, a Figure 1, an overview or pull figure, a graphical abstract, a pipeline or flowchart that explains how a method works, or an "Excalidraw-style" diagram for a paper.
disable-model-invocation: true
---

# teaser-figure

## What this makes, and what it is called

The artifact is a **teaser figure** — also called an overview figure, a pull figure, or (in journals) a graphical abstract. It is the one figure a reader sees before deciding whether to read the paper.

There are two kinds and they are not interchangeable. A **results teaser** is a plot of the headline number. An **overview teaser** is a schematic that explains the idea. This skill makes the second kind: a **three-panel problem / method / result triptych**, drawn in a **flat boxes-and-arrows idiom** — pastel fills, rounded corners, thin coloured strokes, a caption pill on each panel. It is what people mean by "the Excalidraw look", though Excalidraw is only one of the tools it gets drawn in; here it is drawn in matplotlib so the output is a clean vector PDF with the right fonts.

Ask which kind is wanted if it is not obvious. A paper whose contribution is a *number* wants a results teaser; a paper whose contribution is a *mechanism* wants this one.

There is a second overview style in this repo, `teaser-figure-plain`: white ground, no tinted panels, the objects drawn rather than named, and a measured chart in the last panel — the SAM / FlashAttention idiom. Prefer it when the paper has something concrete to draw and a real measurement to plot, and the figure will sit under a caption that can carry the prose. Prefer this one when the contribution has no drawable object, or the figure must stand alone.

## The red line

**Every number, name and claim in the figure comes from the paper's own text, macros, or result files.** Read the abstract and the relevant section before drawing anything.

A teaser is read as a promise about the paper. So:

- Never strengthen a bound by dropping a qualifier. `O(k) queries` is not the same claim as `O(k) queries on doubling metrics`.
- Never drop a factor from a stated bound to make it fit. Shrink the font, shorten the prose, or cut the claim.
- Prefer the paper's own table over its abstract when they differ in detail — the abstract compresses, and the compression sometimes loses a case the table records honestly.
- If the paper hedges, the figure hedges. "a factor approaching 2" does not become "2×".

## The three panels

Left, centre, right answer **why**, **how**, **what**. Give each a short noun-phrase title, not a sentence.

**Left — the obstacle.** Why the problem is hard or why prior bounds do not meet. Land on one picture that carries the difficulty (a cone, a timeline that can stop anywhere, a starved task class, two identical histograms). End the panel with the consequence in a box.

**Centre — the mechanism.** Draw the *one idea* that makes the method work, not a block diagram of the system. If the method is a loop, show the loop and what makes it exit. If it is a decision, show what is on each side of it. A bar chart of internal state with the algorithm's own threshold line drawn across it beats four boxes of prose.

**Right — what it buys.** Almost always a before/after: a status table with a `before` row and an `ours` row, an interval that collapses to a point, a column of exponents with the improved ones lit up. Follow it with the caveat or the limit, in `GREY` or `AMBER`. Stating what is still open here costs one box and buys the reader's trust.

## Visual grammar

Colour is semantic, not decorative. Keep it consistent inside one figure and across a set:

| Tone | Panel it owns | What it marks inside a panel |
|---|---|---|
| `BLUE` | left, the problem | setting, definitions |
| `RED` | centre, the method | costs something, fails, the paid step |
| `GREEN` | right, the result | free, works, the improvement |
| `AMBER` | — | open, unresolved, the thing that hides the failure |
| `VIOLET` | — | a secondary or downstream consequence |
| `GREY` | — | known, inherited, or a hard limit |

- **Size**: 7.0 × 2.5 in, for a `figure*` spanning both columns. A single column (3.3 in) cannot hold three panels.
- **Density**: one two-line italic caption under each panel title, then at most four or five elements. The reference figures that work are dense but hierarchical — a reader should get the story from the titles and the bold lines alone.
- **Text**: bold for a box title, regular for its second line, italic grey for captions and asides. Nothing below 5.5 pt.

## Workflow

```
- [ ] 1. Read the paper: abstract, the method section, and any landscape/results table
- [ ] 2. Write the three panels out in prose first, one sentence each, and check them against the paper
- [ ] 3. Copy scripts/overview_style.py next to the figure scripts
- [ ] 4. Write <name>_overview.py, laying out coordinates panel by panel
- [ ] 5. Render; fix every OVERFLOW line and every missing-glyph warning
- [ ] 6. Look at the PNG and iterate on overlaps the audit cannot see
- [ ] 7. Confirm the PDF is 7.0 x 2.5 in with no Type 3 fonts
```

Step 2 is the one that gets skipped and the one that matters. If the three sentences do not tell a story on their own, no amount of drawing will fix it.

Step 6 is not optional. `audit()` catches text leaving a panel; it cannot see a label sitting on a bar, an arrow crossing a box, or two caption lines rendering at different sizes. **Always read the rendered PNG back.**

## The kit

`scripts/overview_style.py` — copy it next to the figure scripts and `import` it. Needs matplotlib; finds TeX Gyre Heros and Termes from a TeX install and falls back to DejaVu.

Coordinates are hundredths of an inch, origin bottom-left, so a full-width figure is 700 × 250.

```python
fig, ax = canvas(7.0, 2.50)                      # data coords = 1/100 inch
panel(ax, x, y, w, h, "Method: Lazy-FFT", RED)   # tinted region + caption pill
caption(ax, cx, ytop, [line1, line2], maxw)      # sizes all lines together
box(ax, x, y, w, h, title, sub, tone=RED)        # rounded box, auto-shrinks text
text(ax, x, y, s, size=7, maxw=None)             # maxw triggers auto-shrink
arrow(ax, (x1, y1), (x2, y2), GREY, rad=0.0)     # rad bends it
tag(ax, x, y, "1 query", RED)                    # pill label for an arrow
wedge(ax, apex, a1, a2, length, BLUE)            # a filled 2-D cone
measure(ax, s, size) -> (w, h)                   # real rendered extent
audit(ax, [("left", x, y, w, h), ...])           # prints text leaving a region
save(fig, "name_overview.pdf")                   # also writes a .png preview
```

Pass panel regions to `audit()` with about 12 units of extra height, since the caption pill straddles the top edge.

See [example.py](example.py) for a complete figure using all of it, and `example.png` for what it should look like.

## Pitfalls

**Missing glyphs.** TeX Gyre Heros has Greek, `× ≤ − ∞ ² ³ φ ℓ`, but *not* `⌈ ⌉ ⇔ ⋀ ⁴ ⁻ ₁ ✓ ✗`. Use mathtext for those: `$\lceil\log_2 n\rceil$`, `$\Leftrightarrow$`, `$\bigwedge_j$`, `$\epsilon^{-2}$`, `$\ell_1$`, `$\checkmark$`, `$\times$`. A missing glyph renders as a blank box and only shows up as a warning, so grep the render output for `missing`.

**Mathtext ignores bold.** A bold box title containing `$...$` renders half-bold and looks broken. Either keep the title free of math and use Unicode (`ε`, `×`, `≥`, `³`), or wrap the maths in `\mathbf{}`.

**`box()` with no `sub` centres its title vertically.** Do not use it as a container you then draw into — the title will land on top of your contents. Use `_round()` plus your own `text()` for that.

**Auto-shrink is per string.** Two caption lines sized separately end up visibly different. That is what `caption()` is for; use it rather than two `text()` calls.

**Estimating text width from character count does not work** — it is off by 30% for this font. Call `measure()`.

**Font type.** `overview_style` sets `pdf.fonttype=42`; matplotlib's default is Type 3, which the AAAI author kit forbids. Verify with PyMuPDF: `[f for f in page.get_fonts(full=True) if f[2] == "Type3"]` must be empty.
