---
name: checkbib
description: Verify every citation in a LaTeX paper against a real fetched source, and catch fabricated references before submission. Scans \cite keys, cross-checks them against the .bib, confirms each entry from a DOI, arXiv id, author page, or venue archive, and records the evidence in a verified field. Use when the user runs /checkbib, or asks to check citations, verify a bibliography, audit references, or hunt for hallucinated or non-existent citations in a paper.
disable-model-invocation: true
---

# checkbib

A separate citation pass over a draft. Ported from the `theory-research-workflow` librarian agent's citations mode, with the `kb/` scaffolding dependency removed — this runs on any LaTeX directory.

Citation checking is its own pass for a reason. Done inline while writing, it degrades into pattern-matching plausible metadata. Major venues treat non-existent references as a sanctionable integrity violation rather than a typo: AAAI lists "non-existent references" alongside plagiarism, with penalties up to multi-year bans.

## The red line

**Every claim about a paper rests on a source actually fetched in this session.** Never invent or "correct" authors, years, venues, arXiv ids, page numbers, or DOIs. Recall of a paper's metadata is a hypothesis, never a source.

Cannot confirm a citation → mark it `UNVERIFIED` and list the methods tried. **Never fix by guessing.** One fabricated reference reaching the human poisons the whole draft, because it destroys the reader's basis for trusting any other citation.

## Workflow

```
locate → scan → triage → verify → write back → re-scan
```

### 1. Locate the paper

Ask for the paper directory if it is not obvious from context. Identify the root `.tex` (usually `main.tex`) and the bibliography.

### 2. Scan

```bash
python3 scripts/check_bib.py main.tex refs.bib
```

Naming the root `.tex` explicitly is the precise mode: the script follows `\input`, `\include`, and `\subfile` transitively and scans only that tree. **Prefer it.** Passing a bare directory globs every `.tex` present, which sweeps in conference template files (`AnonymousSubmission2027.tex` and the like) and reports their sample citations as fabricated.

```bash
python3 scripts/check_bib.py latex/                        # glob a directory
python3 scripts/check_bib.py latex/ --exclude Anonymous    # glob, minus template noise
```

The script reports four categories and exits 1 if either of the first two is non-empty:

| Category | Meaning |
|---|---|
| `MISSING` | Cited in the text, absent from the `.bib`. A typo, or a fabricated citation. |
| `UNVERIFIED` | In the `.bib` with no `verified` field. Not yet confirmed against a source. |
| `DUPLICATE` | Same key defined twice; the later definition silently wins. |
| `UNCITED` | In the `.bib`, never cited. Informational — harmless, but often a symptom of a renamed key. |

### 3. Triage MISSING keys first

A `MISSING` key is the dangerous category, and it has two very different causes. Distinguish them before touching anything:

- **Typo or renamed key.** A near-match exists in the `.bib`. Fix the key in the `.tex`.
- **The paper was never in the bibliography.** Treat the citing sentence as a claim that some specific paper exists. Try to find that paper. If it does not exist, the citation was fabricated: **the sentence itself has to be rewritten or dropped**, and this must be reported prominently to the human. Do not quietly substitute a different paper that happens to support the claim — the surrounding text was written against a source that never existed, so its claim is unsupported until a human re-checks it.

### 4. Verify each unconfirmed entry

For every `MISSING` and `UNVERIFIED` key, confirm the entry against a real source. Budget about **three distinct methods** per citation before giving up:

1. DOI resolution, or the Crossref API (`api.crossref.org/works/<doi>`) for structured metadata
2. arXiv (`arxiv.org/abs/...`, or `export.arxiv.org/api/query?id_list=...`)
3. dblp (`dblp.org/search/publ/api?q=<query>&format=json`)
4. Venue archive (PMLR, OpenReview, ACL Anthology, papers.nips.cc, ojs.aaai.org, ACM DL, IEEE Xplore)

**Fetch these with the web tool, not `curl`.** Sandboxes frequently have no network egress from the shell while the web tool reaches the same host fine — dblp in particular tends to hang rather than fail fast, burning the budget on a method that was never going to work.

**Crossref stores empty titles.** The DOI for the BERT paper (`10.18653/v1/N19-1423`) resolves with `title: ['']` — verified 2026-07-31 — and random sampling puts the empty-title rate around 4%. A verifier that matches on title alone therefore reports the most-cited reference in NLP as unresolvable. Match on the identifier resolving at all, and treat the title as corroboration when present rather than as the test.

Two dblp quirks worth knowing: parentheses in a title break its tokenizer, so a title like "On the (In)Tractability of ..." returns zero hits — search by author or by a parenthesis-free fragment instead. And it throttles rapid successive queries, returning transient 500s.

Confirm the fields that a reader would use to find the paper: title, author list, year, venue. Correct any that disagree with the fetched source, and say so in the report.

**Parallelize when there are more than roughly eight to verify.** Dispatch `generalPurpose` subagents in a single batch, five to ten citations each, with the red line inlined in every prompt and instructions to return a per-key verdict plus the URL used. Verification is I/O-bound and independent per citation, so this is close to free.

**Paste the raw `.bib` text into the subagent prompt verbatim — never retype it.** Retyping silently drops LaTeX accent macros (`Szepesv{\'a}ri` becomes `Szepesvari`), and the subagent then dutifully reports a diacritics correction against a defect that exists only in the prompt. Acting on those false positives corrupts a bibliography that was already right.

### 5. Write the evidence back

Add a `verified` field recording what was actually fetched:

```bibtex
@inproceedings{skowron2022proportional,
  title     = {Proportional Public Decisions},
  author    = {Skowron, Piotr and Górnowicz, Adrian},
  booktitle = {AAAI},
  year      = {2022},
  verified  = {https://doi.org/10.1609/aaai.v36i5.20434}
}
```

Use the identifier that was resolved: a DOI URL, `arXiv:2301.12345`, a `dblp:` key, or the venue archive URL. BibTeX ignores unknown fields, so `verified` never appears in the rendered bibliography and is safe to leave in the submitted source.

### 6. Re-scan

Re-run the script. Iterate until it exits 0, or until everything remaining is genuinely unconfirmable — which is a result to report, not a failure to hide.

## Report

Close with this shape:

```
checkbib: <N> cited, <V> verified, <U> unverified, <M> missing

Fixed
  - <key> — what was wrong, source used

Rewritten or dropped
  - <key> — no such paper found; cites at <file>:<line> need author review

Still UNVERIFIED
  - <key> — methods tried
```

Report every remaining `UNVERIFIED` key explicitly. Silence here reads as "all clear", which is the one thing this pass must never say falsely.

## Utility script

**scripts/check_bib.py** — no dependencies, Python 3 standard library only. Execute it; there is no need to read it first.

```bash
python3 scripts/check_bib.py [--exclude SUBSTR] [PATH ...]
```

`PATH` is a directory (searched recursively) or an individual `.tex` / `.bib` file, defaulting to the current directory. Naming any `.tex` switches to `\input`-following mode for the tex side; directories still supply `.bib` files in that mode. `--exclude` is repeatable and drops any path containing the given substring.
