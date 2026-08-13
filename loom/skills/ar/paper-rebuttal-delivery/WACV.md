# WACV Delivery Conventions

Venue-specific companion to `SKILL.md`. Applies when the attempt's frozen
delivery policy names WACV (Round-1 "Revise and Resubmit" revisions on
OpenReview). Numbers below restate the policy for convenience; when they
disagree, `delivery-policy.json` wins.

## Artifact shape

- **Revised paper**: body exactly 8 pages and packed full to the bottom of
  page 8; the References heading starts on page 9 (references do not count
  toward the limit). Appendix content never ships inline - rebuild it as a
  separate `supplement.pdf`.
- **Rebuttal**: exactly one page on the official WACV rebuttal template
  (`\usepackage[rebuttal,<track>]{wacv}`), two-column, US Letter, anonymous,
  with the correct `\wacvPaperID` and track option. Longer than one page, or
  altered margins/fonts, will not be reviewed.
- **Supplement**: optional per policy, but if the original submission carried
  appendix material it must reappear here, updated to match the revision.
- **Title changes**: allowed - the R&R revision keeps the same OpenReview
  paper ID (`same_submission_revision`) - but a retitle must be explicitly
  disclosed near the top of the one-page rebuttal, with a one-line rationale,
  so reviewers can reconcile the revision with the original submission.

## One-page response style (PDF format allows color)

Reference exemplar: `rebuttal-reference/344_rebuttal.pdf` inside the paper
package (WACV #344). Mirror its structure:

1. Gratitude opening plus a `Summary of revision updates` list with
   enumerated items.
2. Every question block opens with a **colored italic one-sentence
   restatement** of the question (questioned aspect + what the reviewer says
   is wrong or asks), then the answer in black text.
3. Fixed per-reviewer palette, used everywhere that reviewer's questions or
   concern IDs appear, including when one point answers several reviewers
   (each tag keeps its own color):
   - Meta-review / AC: blue
   - R1: dark red
   - R2: orange
   - R3: teal
   (Print-safe, clearly distinguishable tones; extend the palette in the same
   spirit for more reviewers.)
4. Evidence enumerated as (1) (2) (3) with exact locators into the revised
   paper and supplement.

## Template gotchas (learned 2026-08)

- Neutralize any `latexmkrc` post-build hook in the copied source before the
  harness rebuilds it strictly.
- The phrases "supplementary material" / "supplemental material" in the
  revised paper body trip the separate-supplement preflight; refer to
  "the supplement" instead.
- A wrong `wacv.sty` track option (e.g. `datasets` vs `algorithms`) is a
  deterministic preflight failure - copy the track from the policy.
- A known-good WACV 2027 style file lives in the original packages under
  `latex/wacv.sty`; reuse it rather than downloading a new kit.
