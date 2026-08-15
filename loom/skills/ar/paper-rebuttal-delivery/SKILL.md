---
name: paper-rebuttal-delivery
description: Build a synchronized revised paper and venue-compliant rebuttal from human-approved response content.
---

# Paper Rebuttal Delivery

## Objective

Turn approved reviewer-response content into a coherent submission candidate.
The deterministic Loom harness, not this Agent, decides whether the candidate
passes and whether a bundle may be released.

## Immutable boundaries

1. Work only in the attempt workspace named by `DELIVERY_INSTRUCTIONS.md`.
2. Treat the original paper package and approved response snapshots as
   read-only evidence.
3. Never upload, email, post, or otherwise submit an artifact.
4. Never weaken anonymity, alter venue geometry, reduce font size, or change
   margins to satisfy a page limit.
5. Never represent an experiment, proof, comparison, or paper edit as completed
   unless it exists in the editable source copy and is supported by evidence.
6. The completion marker is not a success verdict. It only hands source files
   back to Loom for independent construction and validation.

## Venue parameters come from the policy, not from memory

Page limits, whether references count toward them, the rebuttal format
(PDF page vs. text box), and supplement separation are all read from the
attempt's frozen `delivery-policy.json`. Never hardcode them. When a
venue-specific companion file exists next to this skill (for example
`WACV.md`), read it before writing anything.

## Required method

### 1. Establish the fact ledger

- Read every approved response and every concern in the concern matrix.
- Inspect the revised manuscript source and relevant evidence.
- Classify each promised action as implemented, accurately scoped, or
  unsupported.
- If a response claims an edit that is absent, implement the defensible edit in
  the copy or narrow the response. Do not preserve a false past-tense claim.

### 2. Synchronize the revised paper

- Preserve the approved scientific position while correcting unsupported
  claims.
- Keep title, track, Paper ID, anonymity, references, figures, and section
  locators internally consistent.
- Keep main-paper and supplementary material separated when venue policy
  provides separate upload fields.
- Removal must be migration: content leaving the main paper moves intact into
  the supplement or appendix. Nothing silently disappears, and the paper keeps
  its page-one teaser/overview figure and its method figure through any
  reformatting.
- Reused figures must track the current claims: figures from the original
  package are assets to regenerate or adapt to the revised narrative, not to
  drop and not to paste back unchanged. Before reuse, audit every in-figure
  label, number, and caption claim against the current text - a withdrawn
  claim must not ride back in on an old figure.
- Visual repairs never change facts: alignment, color, layout, and font fixes
  must not alter any data point, value annotation, or scientific statement.
  Every number shown in a figure traces to a committed result file.
- When a supplement exists, the body must direct reviewers to it at the
  relevant points (observing any venue-banned phrasings) - an uncited
  supplement is invisible.
- Fill the body: the main text must occupy every allowed body page completely,
  with References starting on the following page. A half-empty final body page
  is a defect, and so is padding with filler prose - rebalance real content
  between body and supplement instead.
- Never print placeholder values ("unmeasured", "TBD", "N/A (not run)") in a
  results table. Report a real measured or derived number, or delete the row.
- Do not add unrun experiments merely because reviewers requested them.

### 3. Write the one-page response

- Use the official venue rebuttal mode and the correct track.
- If the paper package contains a reference exemplar (for example a
  `rebuttal-reference/` folder), render and read it first, then match its
  structure point by point.
- Open every question block by restating the question in one full sentence -
  the questioned aspect plus what the reviewer says is wrong or asks - so a
  reader who never saw the reviews understands it. A few-word topic label is
  not a restatement.
- Put acceptance-critical AC and foundational reviewer issues first.
- Merge duplicate objections rather than repeating full answers.
- Lead with direct answers; enumerate the evidence inside an answer as
  (1) (2) (3) with exact section/page locators, not as one running sentence.
- State limitations plainly but compactly.
- Keep requested future work prospective.
- Spend the entire granted budget (page or character limit). If prioritized
  content runs short, fill with neutral reviewer-facing material in the
  exemplar's style (a gratitude opening, a summary-of-revision-updates list,
  scope restatements) - never with new technical claims.
- No process or meta paragraphs (for example a "Revision boundary" note):
  every line must carry information addressed to the reviewers.
- Satisfy the page limit through prioritization and compression, never template
  manipulation.

### 4. Produce the revision map

Every concern ID must appear in `revision-map.json` under either a concrete
change or an explicitly unresolved/scoped item. Each implemented item must name
its section, page range, and factual summary.

### 5. Self-check, then hand off

You may compile while iterating. Before writing the marker, render every page
of every PDF to images and inspect them at print size. Check for:

- wrong track, title, or Paper ID;
- extra rebuttal pages, or a response that leaves granted space unused (a
  column that ends halfway is a failure);
- a body that stops short of the last allowed page, or References starting
  inside the body allowance;
- figures with clipped, overflowing, or overlapping text, or distorted aspect
  ratios (external reviewer panels are a backstop, not the first check - a
  panel rejection costs a full iteration);
- diagram text containment: every text element sits fully inside its own
  panel or box with visible padding, and arrow labels stay clear of panel
  borders;
- anonymous-identity leakage or external links;
- placeholders, undefined references, overfull boxes, or clipped content;
- response claims not reflected in the revised paper;
- supplementary material left in the main-paper artifact.

Write the exact run-scoped completion marker last, then stop. The marker must
declare every artifact you produced - a built supplement that is not named in
the marker does not exist as far as the harness is concerned. Loom will rebuild
from source and may reject the attempt with deterministic feedback.
