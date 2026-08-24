---
name: paper-results-reporting
description: Standardize venue-independent, evidence-backed result tables, main-paper interval placement, provenance hygiene, and final submission-artifact naming. Use for any paper when reporting multi-seed experiments, keeping numeric interval endpoints out of the abstract, body, and main tables, formatting mean plus-or-minus sample standard deviation, removing machine hashes from manuscripts, naming a final PDF by submission ID, or validating statistical tables.
---

# Paper Results Reporting

## Objective

Make every manuscript-facing result readable, statistically defined, and
traceable without exposing internal artifact metadata. The paper shows the
scientific result; a separate experiment-details record preserves machine
provenance.

This skill is venue-independent. It defines result reporting, provenance
hygiene, and the cross-venue final-PDF naming convention. It does not define
page limits, templates, ethical-section placement, appendix policy, or other
conference rules. Apply a separate venue skill for venue-specific packaging.

## Statistical table rule

For stochastic experimental measurements, report:

```text
mean ± sample standard deviation
```

The replicate unit must be the independent final training seed or independent
final run. First aggregate evaluation examples within each replicate, then
compute the sample standard deviation across replicate-level values:

```python
from statistics import stdev

mean = sum(per_seed) / len(per_seed)
sd = stdev(per_seed)  # denominator n - 1
```

Every affected caption states `mean ± sample SD over N independent seeds`
(or runs) and names a different replicate unit when applicable.

### Hard constraints

- Read the actual per-seed/per-run values from raw results or a
  completion-verified aggregate.
- Never infer a standard deviation from confidence-interval endpoints.
- Never invent dispersion or silently substitute standard error.
- With fewer than two independent replicates, do not print a fake `± 0`.
  Run another replicate or report the scalar and disclose the limitation.
- Preserve failed and censored runs according to the frozen protocol.
- Do not mix runs, configurations, checkpoints, or aggregate revisions.
- Round only for display; compute from full-precision replicate values.

### Values that do not receive a standard deviation

Do not append `±` to deterministic metadata such as dataset size, parameter
count, beam width, budget, fixed hyperparameters, theoretical constants, or
event counts. A genuinely seed-independent exact quantity may be shown as
`± 0.00` only when that convention is scientifically useful and the caption
explicitly says why it is zero.

Mean ± SD is descriptive run-to-run variability, not an inferential confidence
interval. It may remain in stochastic main-table cells under this rule, but it
must never be described as a confidence interval.

## Main-paper interval-placement rule

Apply this rule across venues. In the rendered main paper, do not print numeric
interval endpoints in the abstract, body prose, tables, captions, or figure
labels. This includes confidence, credible, percentile-bootstrap, standard-error,
and min--max intervals written as `[lower, upper]`, `(lower, upper)`, or an
estimate followed by an endpoint pair.

- Report the point estimate, normally the mean, in the abstract and body prose.
- In main-paper tables, keep stochastic cells as `mean ± sample SD` when the
  statistical table rule applies. Sample SD is a dispersion summary, not a pair
  of interval endpoints. Do not add CI columns or endpoint pairs to those cells.
- Describe inferential outcomes qualitatively when needed, for example that a
  comparison remains unresolved or that a paired difference stays positive
  under resampling, without printing endpoint values.
- Do not print endpoint values in a main-paper figure callout. Visual error bars
  or shaded bands may remain only when their caption defines the statistic
  without giving numeric endpoints.
- Put full interval methodology, endpoint values, per-replicate records, and
  additional uncertainty analysis in appendix experiment details. If the venue
  cannot accept an appendix, preserve them in a separate experiment-details
  artifact rather than the main PDF.
- Preserve CI, SD, and SE fields in machine-readable results even when the main
  paper displays only the permitted summary.

Update the source exporter or figure generator as well as generated artifacts,
so rebuilding cannot restore forbidden intervals.

## Reproducible export

1. Identify the unique aggregate and completion manifest behind each table.
2. Add mean and sample-SD fields or LaTeX macros to the aggregator/exporter.
3. Regenerate the table source; do not hand-copy numbers into multiple files.
4. Keep CI fields for appendix experiment details and machine-readable audits,
   not for numeric endpoint display in the main paper.
5. Record the aggregate revision and input artifacts in experiment details.

Recommended LaTeX:

```latex
\newcommand{\SDcell}[2]{\ensuremath{#1 \mathbin{\pm} #2}}
```

Use one consistent precision per metric family. A displayed mean and SD should
normally use the same number of decimal places.

## Provenance belongs outside the rendered paper

Do not expose raw SHA hashes, commit hashes, completion digests, local paths,
hostnames, or internal run-directory names in manuscript tables, captions, or
body text, including the reproducibility section. This is a conditional
double-blind linkage risk, not a claim that hashes are secrets or personal
data: a reviewer may search an identifier that belongs to a public repository
and recover the authors' identities. Repository visibility can also change
during review, so do not make manuscript inclusion depend on whether the
repository is private today.

Do not print full or abbreviated commit IDs from either internal or third-party
repositories in an anonymous manuscript. Cite the public implementation and
name a stable release when available; keep the exact revision in experiment
details. Replace internal identifiers with human-readable labels such as
`Run A`, `final seeds 1--5`, or a configuration name.

Preserve the full mapping in an existing experiment-details/provenance file. If
none exists, create `EXPERIMENT_DETAILS.md` outside the `main.tex` input tree.
For each label record:

- artifact or run purpose;
- full hash and hash type;
- producing configuration and seed set;
- source path relative to the project;
- verification or completion-manifest status.

Removing a hash from the PDF must never destroy provenance.

## Final main-PDF naming

Name every final main-paper artifact:

```text
main-paper-<submission-ID>.pdf
```

Replace `<submission-ID>` with the assigned venue ID. This convention applies
across venues, including WSDM and WACV. It does not prescribe names for
supplements or internal appendix backups.

- Prefer building directly to the final name, for example with
  `latexmk -jobname=main-paper-<submission-ID> main.tex`.
- If a toolchain must first emit `main.pdf`, move the freshly verified artifact
  to the final name and delete `main.pdf`; never leave both files.
- Update `.gitignore`, READMEs, submission manifests, upload instructions, and
  automation that still refers to `main.pdf`.
- Recompute recorded size and checksum values after the final build or rename.
- Reject a package when the expected ID-specific PDF is missing, when a stale
  `main.pdf` remains, or when the PDF predates source changes.

## Batch-paper workflow

When several papers need the same polish:

1. Assign one worker per paper with disjoint directory ownership.
2. Each worker locates evidence, updates exporters and manuscript source,
   compiles the PDF, and reports all exceptions.
3. The coordinating agent performs independent acceptance checks; it does not
   accept a worker's summary as proof.
4. Return only the failing paper to its worker, with exact evidence.

Do not let parallel workers edit a shared template or shared generated file.

## Acceptance checks

Before declaring a paper ready:

- enumerate every table appearing in the compiled main PDF;
- classify each numeric field as stochastic measurement or deterministic
  metadata;
- recompute sampled table cells from replicate arrays and compare after
  rounding;
- confirm every stochastic result cell uses `mean ± sample SD` and every
  caption names `N` and the replicate unit;
- reject numeric interval endpoints in the main-paper abstract, body prose,
  tables, captions, and figure labels; verify moved interval details are in an
  appendix experiment-details section or separate experiment-details artifact;
- scan rendered text for hexadecimal hashes, private paths, hosts, identity
  leaks, stale CI descriptions, and placeholders, including abbreviated
  7--12-character commit IDs in reproducibility sections;
- confirm the final artifact is `main-paper-<submission-ID>.pdf`, contains the
  correct assigned ID, and has no sibling legacy `main.pdf`;
- compile from source and reject undefined references/citations or overfull
  table content;
- visually inspect every table for clipping, overlap, and unreadable type.

Report deterministic fields that intentionally remain scalar. “Every number
has ±” is not a valid acceptance criterion if it fabricates uncertainty.
