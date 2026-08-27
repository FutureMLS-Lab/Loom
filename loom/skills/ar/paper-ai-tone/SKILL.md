# Paper prose — kill the AI accent, keep the science

Machine-written papers fail reviews for how they read, not only for what they
claim. Apply these rules to every section you write or revise.

**Hard invariants while editing prose: every number, citation, model name,
and the strength of every conclusion stays exactly as it was. Never add facts
during a style pass.**

## Tells to remove (the AI accent)

- Rhetorical contrast scaffolding ("not X, but Y"), slogan topic sentences,
  dramatic headings, and meta-commentary about the paper itself.
- Formulaic three-part lists; bullet points where the content has causal or
  progressive structure — write those as connected paragraphs.
- Template connectives: "Moreover", "Notably", "Furthermore", "It is worth
  noting that". Connect sentences by their actual logic instead.
- Hype modifiers: "elegantly", "remarkably", "fundamentally", "theoretically"
  (without a theorem), "significantly" (without a significance test).
- Self-praise: "our method effectively/successfully achieves" — point at the
  table and say what improved and by how much.
- Em-dash and semicolon overuse, multi-clause pileups, anthropomorphized
  methods ("the model wants/believes").
- The same claim repeated in three places. Say it once, where it lands
  hardest.
- Each paragraph serves one purpose and hands off to the next with a real
  transition, not a formula.

## Numbers

One number ± one number. Never composite forms like "4.5 + [-0.1, 0.2]";
pick the single clearest statistic, present it directly, and keep the same
format for that quantity everywhere in the paper.

## Narrative spine

- One motivating question runs from Introduction through Method, Experiments
  and Analysis. Every module, design choice, and experiment ties back to it;
  no mid-paper pivot.
- High-level intuition before formalism: what problem, what core idea, why
  that idea is plausible — then the equations.
- Explain every design choice. Not "we introduce X" but why X is necessary
  and what concretely breaks without it. Every low-level implementation
  detail should trace back to the high-level problem.
- Position against baselines only after the method is understood — comparison
  locates the method; it must not interrupt its exposition.

## Method mechanics

- Define every symbol at first use: meaning, dimensions, role. One notation
  per concept, one spelling per name and abbreviation, consistent through the
  appendix.
- Prose around every equation: purpose before, meaning after. No equation
  dumping.
- Pseudocode only when an algorithm block genuinely aids understanding —
  never as a template ornament.

## Experiments and analysis

- Every experiment answers a named question; every ablation tests a named
  design choice and states what the outcome supports or refutes. No stacking
  datasets, metrics and tables for volume.
- Analysis explains why the results occur and what regularities or limits
  they reveal — it does not re-narrate table cells.
- Close the loop: connect results back to the motivating question, and leave
  a one-sentence takeaway where a subsection earns one.

## Claims and citations

- The scope and strength of every claim match the evidence exactly.
- Every citation genuinely supports its sentence — related-but-not-evidence
  papers do not count. Verify each cited paper exists with the stated title,
  authors and venue; a hallucinated or decorative citation is a soundness
  violation, not a style issue.
- Related work states what existing methods can and cannot do and how this
  paper relates — never a generic AI-survey paragraph.

## Revision passes on existing text

- Edit editable source, one small scope at a time (abstract + introduction
  first), diff against the original, and confirm no number, citation, or
  claim drifted before widening scope.
- A follow-up pass only flags residual tells for case-by-case decisions — no
  second full rewrite. Local edits must not break the paper-wide narrative;
  the appendix is held to main-text quality.
- The target is restrained, precise, natural academic prose — never an
  AI-detector score.
