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
- Do not add unrun experiments merely because reviewers requested them.

### 3. Write the one-page response

- Use the official venue rebuttal mode and the correct track.
- Put acceptance-critical AC and foundational reviewer issues first.
- Merge duplicate objections rather than repeating full answers.
- Lead with direct answers; use exact evidence and section/page locators.
- State limitations plainly but compactly.
- Keep requested future work prospective.
- Satisfy the page limit through prioritization and compression, never template
  manipulation.

### 4. Produce the revision map

Every concern ID must appear in `revision-map.json` under either a concrete
change or an explicitly unresolved/scoped item. Each implemented item must name
its section, page range, and factual summary.

### 5. Self-check, then hand off

You may compile while iterating. Before writing the marker, inspect both PDFs
and source for:

- wrong track, title, or Paper ID;
- extra rebuttal pages;
- anonymous-identity leakage or external links;
- placeholders, undefined references, overfull boxes, or clipped content;
- response claims not reflected in the revised paper;
- supplementary material left in the main-paper artifact.

Write the exact run-scoped completion marker last, then stop. Loom will rebuild
from source and may reject the attempt with deterministic feedback.
