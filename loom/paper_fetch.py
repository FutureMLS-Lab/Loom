"""Fetch a paper - and, from OpenReview, its reviews - off a public URL.

One fetcher for every factory: the Review Factory pulls a PDF to sit its
panel in front of, and the Rebuttal Factory pulls a whole forum (submission
plus official reviews) to answer. Kept together so URL validation, size
caps and OpenReview quirks are fixed in exactly one place.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

# The same public-URL policy the Rebuttal Factory already enforces for CFP
# fetches; importing it is the point - two validators would drift.
from loom.rebuttal_task import _validate_url_syntax as validate_public_url

MAX_PDF_BYTES = 80 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
_UA = "loom-paper-fetch/1.0"
OPENREVIEW_API = "https://api2.openreview.net"


def _fetch(url: str, limit: int, timeout: int = 60) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"download exceeds {limit // (1024 * 1024)}MB cap: {url}")
    return data


def openreview_forum_id(url: str) -> str:
    """The ``id=`` of an openreview.net forum/pdf URL, or ''. """
    parsed = urllib.parse.urlparse(str(url or ""))
    if not parsed.hostname or not parsed.hostname.endswith("openreview.net"):
        return ""
    ident = (urllib.parse.parse_qs(parsed.query).get("id") or [""])[0].strip()
    return ident if re.fullmatch(r"[A-Za-z0-9_-]{4,64}", ident or "") else ""


def _arxiv_id(url: str) -> str:
    m = re.match(
        r"^https?://arxiv\.org/(?:abs|pdf)/([0-9]{4}\.[0-9]{4,5})(?:v\d+)?(?:\.pdf)?$",
        str(url or "").strip(),
    )
    return m.group(1) if m else ""


def _arxiv_pdf_url(url: str) -> str:
    ident = _arxiv_id(url)
    return f"https://arxiv.org/pdf/{ident}" if ident else ""


def _arxiv_title(ident: str) -> str:
    """The paper's title off the arXiv Atom API; empty on any trouble."""
    try:
        feed = _fetch(
            f"https://export.arxiv.org/api/query?id_list={urllib.parse.quote(ident)}",
            MAX_JSON_BYTES,
            timeout=20,
        ).decode("utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - a title is a nicety, not a requirement
        return ""
    titles = re.findall(r"<title>(.*?)</title>", feed, re.DOTALL)
    # The feed's own <title> comes first; the entry's follows.
    return re.sub(r"\s+", " ", titles[1]).strip() if len(titles) > 1 else ""


def _note_value(content: dict[str, Any], key: str) -> str:
    """OpenReview API v2 wraps every field as {'value': ...}."""
    raw = content.get(key)
    if isinstance(raw, dict):
        raw = raw.get("value")
    if isinstance(raw, list):
        return ", ".join(str(x) for x in raw)
    return str(raw or "")


def fetch_openreview_forum(forum_id: str) -> dict[str, Any]:
    """The submission note and its official reviews, off the public v2 API."""
    data = json.loads(
        _fetch(
            f"{OPENREVIEW_API}/notes?forum={urllib.parse.quote(forum_id)}",
            MAX_JSON_BYTES,
        ).decode("utf-8", errors="replace")
    )
    notes = data.get("notes") or []
    submission = next((n for n in notes if n.get("id") == forum_id), None)
    if submission is None:
        raise ValueError(f"no submission note found for forum {forum_id}")

    def _kind(note: dict[str, Any], marker: str) -> bool:
        return any(marker in str(inv) for inv in (note.get("invitations") or []))

    return {
        "forum": forum_id,
        "title": _note_value(submission.get("content") or {}, "title"),
        "submission": submission,
        "reviews": [n for n in notes if _kind(n, "Official_Review")],
        "meta_reviews": [n for n in notes if _kind(n, "Meta_Review")],
        "decisions": [n for n in notes if _kind(n, "Decision")],
    }


def note_markdown(note: dict[str, Any]) -> str:
    """One review note flattened to readable markdown, field by field."""
    content = note.get("content") or {}
    signature = ", ".join(str(s).rsplit("/", 1)[-1] for s in (note.get("signatures") or []))
    lines = [f"# {signature or 'Review'}", ""]
    for key, raw in content.items():
        value = raw.get("value") if isinstance(raw, dict) else raw
        if value in (None, ""):
            continue
        title = key.replace("_", " ").strip().title()
        lines.append(f"## {title}\n\n{value}\n")
    return "\n".join(lines)


def fetch_paper_pdf(url: str, dest: Path) -> dict[str, Any]:
    """Download the PDF a URL points at (arXiv page, OpenReview forum, or
    a direct PDF link) to *dest*. Returns ``{ok, title?}``."""
    clean = validate_public_url(str(url or "").strip(), "Paper URL")
    title = ""
    forum = openreview_forum_id(clean)
    if forum:
        info = fetch_openreview_forum(forum)
        title = info["title"]
        pdf_url = f"https://openreview.net/pdf?id={urllib.parse.quote(forum)}"
    else:
        arxiv_id = _arxiv_id(clean)
        if arxiv_id:
            title = _arxiv_title(arxiv_id)
        pdf_url = _arxiv_pdf_url(clean) or clean
    data = _fetch(pdf_url, MAX_PDF_BYTES)
    if not data.startswith(b"%PDF"):
        raise ValueError(f"not a PDF: {pdf_url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return {"ok": True, "title": title}


def materialize_rebuttal_package(url: str, dest_root: Path) -> dict[str, Any]:
    """Build a Rebuttal Factory source package from an OpenReview forum URL.

    Lays down what the intake scanner expects to find on disk: the submission
    PDF plus one markdown file per official review (and the meta-review and
    decision when present), with the raw forum JSON kept for audit.
    """
    clean = validate_public_url(str(url or "").strip(), "OpenReview URL")
    forum = openreview_forum_id(clean)
    if not forum:
        raise ValueError("not an openreview.net forum URL (need ...?id=<forum>)")
    info = fetch_openreview_forum(forum)
    if not info["reviews"]:
        raise ValueError("this forum has no official reviews yet")

    package = dest_root / forum
    reviews_dir = package / "reviews"
    reviews_dir.mkdir(parents=True, exist_ok=True)

    pdf = _fetch(f"https://openreview.net/pdf?id={urllib.parse.quote(forum)}", MAX_PDF_BYTES)
    if not pdf.startswith(b"%PDF"):
        raise ValueError("the forum's PDF download did not return a PDF")
    (package / "submission.pdf").write_bytes(pdf)

    for n, note in enumerate(info["reviews"], start=1):
        (reviews_dir / f"reviewer-{n}.md").write_text(
            note_markdown(note), encoding="utf-8"
        )
    for name, notes in (
        ("meta-review.md", info["meta_reviews"]),
        ("decision.md", info["decisions"]),
    ):
        if notes:
            (reviews_dir / name).write_text(
                "\n\n---\n\n".join(note_markdown(n) for n in notes), encoding="utf-8"
            )
    (package / "forum.json").write_text(
        json.dumps(
            {
                "forum": forum,
                "title": info["title"],
                "fetched_from": clean,
                "submission": info["submission"],
                "reviews": info["reviews"],
                "meta_reviews": info["meta_reviews"],
                "decisions": info["decisions"],
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )
    return {
        "ok": True,
        "dir": str(package),
        "title": info["title"],
        "reviews": len(info["reviews"]),
    }
