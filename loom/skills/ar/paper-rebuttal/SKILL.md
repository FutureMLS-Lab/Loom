---
name: paper-rebuttal
description: Draft reviewer-specific academic rebuttals that maximize acceptance probability through evidence-bounded advocacy, point-by-point responses, and venue-compliant formatting. Use when preparing an author response, rebuttal, discussion reply, AC response, reviewer reconsideration package, or response-to-reviewers document.
disable-model-invocation: true
---

# Paper Rebuttal

## Prime directive

**Acceptance-first, evidence-bounded advocacy.**

The objective is to maximize the paper's probability of acceptance. Use the
strongest defensible framing, put decisive evidence first, concede only what
the evidence forces, and describe corrections as clarifications or
strengthenings when that description is accurate.

Persuasion may change emphasis, ordering, tone, and qualifiers. It must not
change mathematical, experimental, or bibliographic facts.

Never:

- invent a result, experiment, proof, citation, or manuscript change;
- hide a known counterexample or contradiction;
- imply that a frozen submission has already been revised;
- turn evidence that is merely consistent with a claim into proof of it;
- extend a result beyond its verified assumptions;
- attack a reviewer or say that the reviewer failed to understand the paper.

## Rule priority

Apply constraints in this order:

1. Venue rebuttal policy and the exact current deadline.
2. The immutable submitted PDF and original reviews.
3. Verified proofs, result files, and artifact manifests.
4. Acceptance-oriented framing and presentation.

If the venue policy conflicts with this skill, the venue policy wins.

## Required inputs

Before drafting, collect:

- the submitted PDF or immutable manuscript snapshot;
- every reviewer report and the meta-review/AC note;
- venue policy: character limit, revision policy, links/attachments, anonymity,
  global-response support, and discussion dates;
- verified proof and experiment evidence;
- any user-approved strategic priority.

Do not draft from a summary when the original review is available.

## Build a concern matrix

Atomize every review into one row per concern:

```markdown
| ID | Reviewer | Type | Concern | Severity | Evidence needed | Disposition |
|---|---|---|---|---|---|---|
| R1-W1 | R1 | Weakness | ... | critical | theorem check | correct |
| R1-Q1 | R1 | Question | ... | high | Table 2 | clarify |
```

Use these dispositions:

- `correct` — the reviewer found a real error; acknowledge and correct it;
- `clarify` — the claim is supported but the submission was unclear;
- `scope` — the concern is valid outside the proved/evaluated regime;
- `dispute` — the reviewer's conclusion is contradicted by verified evidence;
- `future` — useful work that is not required to establish the current claim.

Repeated concerns from different reviewers retain separate IDs because each
reviewer needs a self-contained answer.

## Response structure

Write one independent response per reviewer unless the venue explicitly
supports a global response.

```markdown
# Response to Reviewer <ID>

Thank you for the careful and constructive review. We appreciate the
reviewer's recognition of <specific positive point>. We respond to each
concern below.

### W1: <faithful one-line restatement of the weakness>

Thank you for raising this important point.

**Response.** <Direct answer in the first sentence.>

**Evidence.** <Exact theorem, number, table, figure, or controlled result.>

**Action/Scope.** <Correct, clarify, narrow, dispute, or conditionally revise.>

### Q1: <faithful one-line restatement of the question>

Thank you for asking for this clarification.

**Response.** ...

We hope these responses address the reviewer's concerns and clarify the
scope and contribution of the work.
```

Every `W#` and `Q#` raised by the reviewer must appear exactly once.

## Point-by-point writing rule

For every concern:

1. Thank the reviewer briefly.
2. Restate the concern accurately without weakening it.
3. Give the direct answer before background.
4. Present the minimum decisive evidence.
5. State the disposition and scope.
6. If permitted, state the precise post-decision action.

Do not merge unrelated concerns into one broad paragraph.

## Response patterns

### When the reviewer is correct

```text
Thank you for identifying this issue. We agree that the submitted statement
was too broad. The defensible claim is ... The supporting evidence is ...
```

### When clarification is sufficient

```text
Thank you for asking for this clarification. The intended claim is Y rather
than X. Specifically, ...
```

### When disputing a conclusion

```text
Thank you for raising this concern. We respectfully disagree with this
conclusion because ... The decisive evidence is ...
```

Never write:

```text
The reviewer misunderstood the paper.
```

Prefer:

```text
We apologize that this distinction was not sufficiently clear in the
submission. The relevant distinction is ...
```

## Acceptance-oriented framing

Allowed persuasive choices:

- lead with evidence most likely to change the score;
- acknowledge a narrow defect without surrendering the supported headline;
- frame a valid correction as a strengthening when it genuinely yields a
  cleaner, more precise, or more general result;
- distinguish an operative empirical conclusion from an unverified mechanism;
- turn a counterexample into a boundary or sanity check when the corrected
  statement really passes it;
- use precise positive language such as `supports`, `is consistent with`,
  `establishes under`, `remains valid for`, and `strengthens`;
- move unresolved extensions to explicit future work rather than allowing them
  to blur the current contribution.

Evidence-sensitive qualifiers:

- `proves` / `establishes` require a checked proof;
- `demonstrates` requires direct evidence;
- `supports` and `is consistent with` are appropriate for finite experiments;
- `to our knowledge` requires a documented literature search;
- `first` and `state of the art` require explicit verification.

The best framing is the strongest wording that remains true under adversarial
review.

## Manuscript freeze

Read the venue policy before any edit.

When the submission is frozen:

- do not modify the submitted manuscript or PDF;
- do not say `we revised`, `we added to the paper`, or `in the revised paper`;
- transmit corrections, derivations, and new evidence only in the response;
- describe future manuscript edits exactly as:

```text
If accepted, we will ...
```

New experiments may be reported only if the venue allows them. Make clear that
they are rebuttal evidence and are not part of the original submission.

## Evidence discipline

Create a claim-evidence map:

```markdown
| Concern | Response claim | Evidence locator | Verified | Safe wording |
|---|---|---|---:|---|
| R1-W1 | ... | result.json / theorem | yes | supports ... |
```

Rules:

- every number must come from one unique source;
- preserve failed and censored runs;
- never mix numbers from incompatible experiment versions;
- theory objections require derivations, not empirical substitution;
- disclose when an experiment supports a phenomenon but not its proposed
  mechanism;
- do not promise an experiment or proof that cannot be completed in the
  response window.

## Reviewer-specific strategy

Prioritize by decision impact:

1. AC/meta-review blockers.
2. Correctness counterexamples.
3. Evidence gaps that can change ratings.
4. Scope and definition concerns.
5. Presentation issues.

Use positive comments from the same reviewer in the opening, but do not spend
response budget repeating praise.

Each reviewer response must be self-contained when cross-references are not
supported. Do not write `see our response to Reviewer 2`.

## Mechanical preflight

Before presenting a response to the user:

- count Unicode code points against the venue limit and keep a safety margin;
- ensure all concerns are covered;
- remove placeholders, internal Gate names, paths, filenames, commits, hosts,
  identities, affiliations, funding, and acknowledgements;
- reject links, attachments, or new files when the venue forbids them;
- verify anonymity;
- validate Markdown and TeX in the venue preview;
- distinguish readable source from the exact paste-ready representation when
  the platform requires escaped TeX;
- verify every future manuscript action is conditional on acceptance when the
  submission is frozen.

## Human gate

Never submit automatically.

Deliver:

1. the concern matrix;
2. one response per reviewer;
3. an AC/meta-review response when applicable;
4. character counts;
5. unresolved risks;
6. a final paste-ready package.

Stop for explicit human approval before any external submission.
