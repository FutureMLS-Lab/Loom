# How a paper gets written

What actually happens between "start a studio" and "download the PDF" —
the internals behind the Paper Factory. State for both roles lives in the
task's `.RUD/<slug>/ar.json` and survives killed panes and server restarts.

## The studio

A **studio** owns a research direction and a target venue (ICLR, NeurIPS,
ICML or COLM carry LaTeX templates). Its steps, each a button on the studio
page:

1. **Mine** — editable arXiv search settings (suggested from your brief) pull
   the newest work in the direction, so ideas are proposed against what the
   field actually published, not against model memory. Alternatively, a deep
   research pass over what the venue rewarded last cycle.
2. **Ideas** — specific, falsifiable idea cards: hypothesis, the prior work it
   stands against, the experiments that would settle it.
3. **Ground and verify** — each idea's novelty claim is read back out as
   citation edges, and every cited arXiv id is checked against OpenAlex, so a
   fabricated reference cannot pass as grounding.
4. **Spawn** — each idea you keep becomes its own **paper** task with fresh
   `code/` and `manuscript/` repositories.

## The paper

1. **Draft** — the author agent fills the venue's LaTeX skeleton: full
   experiment structure, every number an `\ARnum{}` marker, every results
   figure an `\ARfig{}` placeholder. The one exception is Figure 1: the
   page-one teaser is conceptual, so it is drawn immediately with the default
   figure skill and your gate review sees the paper's visual story.
2. **Your gate.** Approve to open the loop, or send it back with notes. On
   the fleet page, draft-ready papers can be selected across studios and
   approved together with **Start selected rounds**; each paper is still
   validated independently, so a stale item cannot move from the wrong stage.
3. **Rounds** — ten by default. The author works in the task's tmux pane
   (experiments run locally in the worktree) and ends its turn by writing
   `rounds/round-NN/author.md`, closing with a `Skills used:` line naming
   what it applied. If it stops without the note, the loop nudges it back to
   work, and reports through OpenClaw after twelve consecutive fruitless
   nudges. Loom then compiles the PDF and applies a **hard readiness gate**:
   no TODO/placeholder markers, missing figures, unresolved
   citations/references, incomplete core sections, build errors or visible
   `??`, and the paper must open with a page-one overview figure. A blocked
   paper goes back to the author in the same round with the exact failed
   checks. Only a complete submission reaches the **reviewer panel**: three
   independent Cursor models, each in an isolated workspace holding only the
   compiled PDF (never the LaTeX source), each told the venue's own review
   form — ICLR papers get ICLR's sections and scales, CVF papers the 1–5
   strong-reject-to-strong-accept shape. All reports are preserved; the
   lowest-Rating reviewer's complete score block is the round's verdict. If
   that lowest score plateaus for three rounds, the panel is frozen and the
   author must make a structural change; two more flat rounds pause the loop
   for a human decision.
4. **Your final gate.** Approve to deliver — the manuscript is handed to the
   Rebuttal Factory automatically — or send it back for more rounds.

The methodology the agents follow is markdown, not code: edit
`loom/skills/ar/` (`AR-STUDIO.md`, `AR-AUTHOR.md`, `AR-REVIEWER.md`, the
figure skills, `paper-rebuttal/`) to change how the pipeline writes and
reviews.

## Venue templates and LaTeX

Venue styles are vendored under `loom/templates/paper/<venue>/`. Refresh them
when a conference publishes a new template:

```bash
python3 scripts/fetch_paper_styles.py            # all venues
python3 scripts/fetch_paper_styles.py iclr icml  # just these
```

Building needs `latexmk` and a TeX Live install; on Debian the COLM template
additionally needs `texlive-fonts-extra`. Loom reports a missing style file
by name rather than dumping the LaTeX log.
