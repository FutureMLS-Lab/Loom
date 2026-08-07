#!/usr/bin/env python3
"""Check that every \\cite key in a LaTeX paper resolves to a verified .bib entry.

Usage:
    python3 check_bib.py [--exclude SUBSTR] [PATH ...]

Each PATH is a directory (searched recursively for .tex and .bib) or a single
.tex / .bib file. PATH defaults to the current directory.

Naming a .tex file explicitly is the precise mode: only that file and whatever
it pulls in via \\input / \\include / \\subfile is scanned. Use it when template
or scratch .tex files share the directory with the real paper. Directories are
still searched for .bib in that mode.

Exit code is 1 if any citation is missing from the bibliography or lacks a
`verified` field, 0 otherwise.
"""
import os
import re
import sys
import glob

CITE_RE = re.compile(r"\\[a-zA-Z]*[Cc]ite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{([^}]*)\}")
INPUT_RE = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]*)\}")
ENTRY_RE = re.compile(r"@(\w+)\s*\{")
VERIFIED_RE = re.compile(r"\bverified\s*=\s*[{\"]?\s*([^,}\n\"]*)", re.I)
SKIP_TYPES = {"comment", "string", "preamble"}


def read(path):
    with open(path, encoding="utf-8", errors="ignore") as fh:
        return fh.read()


def collect(paths, exclude):
    """Split the given paths into a list of .tex files and a list of .bib files.

    Explicitly named .tex files win: when any is given, the tex set is their
    \\input closure and directories contribute .bib only.
    """
    roots, globbed_tex, bib = [], [], []
    for path in paths:
        if os.path.isdir(path):
            globbed_tex += glob.glob(os.path.join(path, "**", "*.tex"), recursive=True)
            bib += glob.glob(os.path.join(path, "**", "*.bib"), recursive=True)
        elif path.endswith(".tex"):
            roots.append(path)
        elif path.endswith(".bib"):
            bib.append(path)
        else:
            print(f"warning: ignoring {path} (not a directory, .tex, or .bib)")

    tex = expand_inputs(roots) if roots else globbed_tex
    keep = lambda p: not any(s in p for s in exclude)
    return sorted(filter(keep, set(tex))), sorted(filter(keep, set(bib)))


def expand_inputs(roots):
    """Return each root .tex plus every .tex it pulls in, transitively."""
    seen, queue = [], list(roots)
    while queue:
        path = queue.pop(0)
        if not os.path.exists(path) or path in seen:
            continue
        seen.append(path)
        base = os.path.dirname(path)
        for match in INPUT_RE.finditer(strip_comments(read(path))):
            child = match.group(1).strip()
            if not child.endswith(".tex"):
                child += ".tex"
            queue.append(os.path.normpath(os.path.join(base, child)))
    return seen


def strip_comments(text):
    """Drop LaTeX comments so that commented-out citations are not counted."""
    out = []
    for line in text.split("\n"):
        i, escaped = 0, False
        while i < len(line):
            if escaped:
                escaped = False
            elif line[i] == "\\":
                escaped = True
            elif line[i] == "%":
                break
            i += 1
        out.append(line[:i])
    return "\n".join(out)


def cited_keys(tex_files):
    """Map each cited key to the set of .tex files citing it."""
    keys = {}
    for path in tex_files:
        for match in CITE_RE.finditer(strip_comments(read(path))):
            for key in match.group(1).split(","):
                key = key.strip()
                if key and key != "*":
                    keys.setdefault(key, set()).add(os.path.basename(path))
    return keys


def bib_entries(bib_files):
    """Map each bib key to (verified_value_or_None, source_file). Also return duplicates."""
    entries, duplicates = {}, []
    for path in bib_files:
        text = read(path)
        for match in ENTRY_RE.finditer(text):
            if match.group(1).lower() in SKIP_TYPES:
                continue
            body = _brace_body(text, match.end())
            key, _, fields = body.partition(",")
            key = key.strip()
            if not key:
                continue
            if key in entries:
                duplicates.append((key, entries[key][1], os.path.basename(path)))
            found = VERIFIED_RE.search(fields)
            value = found.group(1).strip() if found else None
            entries[key] = (value or None, os.path.basename(path))
    return entries, duplicates


def _brace_body(text, start):
    """Return the text between the brace at start-1 and its matching close brace."""
    depth, i, escaped = 1, start, False
    while i < len(text) and depth:
        char = text[i]
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        i += 1
    return text[start:i - 1]


def main():
    args, paths, exclude = sys.argv[1:], [], []
    while args:
        arg = args.pop(0)
        if arg == "--exclude" and args:
            exclude.append(args.pop(0))
        else:
            paths.append(arg)

    tex_files, bib_files = collect(paths or ["."], exclude)
    if not tex_files:
        print("error: no .tex files found")
        return 2
    if not bib_files:
        print("error: no .bib files found")
        return 2

    cited = cited_keys(tex_files)
    entries, duplicates = bib_entries(bib_files)

    missing = sorted(k for k in cited if k not in entries)
    unverified = sorted(k for k in cited if k in entries and not entries[k][0])
    uncited = sorted(k for k in entries if k not in cited)
    verified = len(cited) - len(missing) - len(unverified)

    print(f"tex={len(tex_files)} bib={len(bib_files)}")
    print(f"cited={len(cited)} entries={len(entries)} verified={verified}")

    if missing:
        print("\nMISSING from the bibliography (possible fabricated citation):")
        for key in missing:
            print(f"  - {key}  [cited in {', '.join(sorted(cited[key]))}]")

    if unverified:
        print("\nUNVERIFIED (no verified field — confirm against a real source):")
        for key in unverified:
            print(f"  - {key}  [{entries[key][1]}]")

    if duplicates:
        print("\nDUPLICATE keys (the later definition wins):")
        for key, first, second in duplicates:
            print(f"  - {key}  [{first} and {second}]")

    if uncited:
        print(f"\nUNCITED entries ({len(uncited)}, informational — not a failure):")
        for key in uncited:
            print(f"  - {key}  [{entries[key][1]}]")

    if not (missing or unverified):
        print("\nOK: every citation resolves to a verified entry.")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
