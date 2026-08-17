"""Sign in to OpenReview and post the factory's reviewer replies.

The last mile of the Rebuttal Factory: once responses are approved, push
each one onto the paper's forum through the official API v2 instead of
copy-paste. Nothing fires without an explicit confirm from the human, and
credentials stay on this machine - the password is exchanged for a bearer
token, only the token is cached (0600), and neither ever enters git or logs.

Every function here is deliberately small and side-channel free so the web
layer can dry-run the whole plan (who replies to which note, under which
invitation and signature) before a single byte is posted.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

DEFAULT_API = "https://api2.openreview.net"
_UA = "loom-openreview-submit/1.0"
_MAX_JSON = 8 * 1024 * 1024

# Content fields that can carry the response body, in preference order.
_BODY_FIELDS = ("rebuttal", "comment", "response", "justification")


def api_base() -> str:
    return os.environ.get("LOOM_OPENREVIEW_API", DEFAULT_API).rstrip("/")


def auth_path() -> Path:
    return Path(
        os.environ.get("LOOM_OPENREVIEW_AUTH", str(Path.home() / ".loom" / "openreview-auth.json"))
    )


def _request(url: str, payload: dict[str, Any] | None, token: str = "", method: str = "") -> Any:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method or ("POST" if payload is not None else "GET"),
        headers={"User-Agent": _UA, "Content-Type": "application/json"},
    )
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(_MAX_JSON + 1)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            raw = exc.read(4096).decode("utf-8", errors="replace")
            detail = str((json.loads(raw).get("message") or raw))[:300]
        except Exception:  # noqa: BLE001
            pass
        if exc.code == 403 and not detail:
            raise ValueError(
                "OpenReview requires a one-time browser challenge from this "
                "host's IP. Open https://openreview.net in a browser routed "
                "through this machine, then retry."
            ) from exc
        raise ValueError(f"OpenReview {exc.code}: {detail or exc.reason}") from exc
    if len(data) > _MAX_JSON:
        raise ValueError("OpenReview response exceeds size cap")
    return json.loads(data.decode("utf-8", errors="replace"))


# --- Authentication ----------------------------------------------------------


def login(username: str, password: str) -> dict[str, Any]:
    """Exchange credentials for a token and cache only the token."""
    username = str(username or "").strip()
    if not username or not password:
        raise ValueError("username and password are both required")
    reply = _request(f"{api_base()}/login", {"id": username, "password": password})
    token = str(reply.get("token") or "")
    if not token:
        raise ValueError("OpenReview login returned no token")
    path = auth_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"username": username, "token": token}, indent=1),
        encoding="utf-8",
    )
    path.chmod(0o600)
    return {"ok": True, "user": username}


def logout() -> dict[str, Any]:
    try:
        auth_path().unlink()
    except FileNotFoundError:
        pass
    return {"ok": True}


def cached_auth() -> dict[str, str]:
    try:
        data = json.loads(auth_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    token = str(data.get("token") or "")
    return {"username": str(data.get("username") or ""), "token": token} if token else {}


def auth_status(verify: bool = False) -> dict[str, Any]:
    auth = cached_auth()
    if not auth:
        return {"logged_in": False}
    status: dict[str, Any] = {"logged_in": True, "user": auth["username"]}
    if verify:
        try:
            _request(f"{api_base()}/profile", None, token=auth["token"])
            status["verified"] = True
        except ValueError as exc:
            status.update(logged_in=False, verified=False, error=str(exc))
    return status


# --- Building the submission plan --------------------------------------------


def _reviewer_number(reviewer_id: str) -> int:
    m = re.search(r"(\d+)$", str(reviewer_id or ""))
    return int(m.group(1)) if m else 0


def _signature_options(invitation: dict[str, Any]) -> list[str]:
    spec = (invitation.get("edit") or {}).get("signatures")
    out: list[str] = []
    if isinstance(spec, list):
        out = [s for s in spec if isinstance(s, str)]
    elif isinstance(spec, dict):
        param = spec.get("param") or {}
        for item in param.get("items") or []:
            value = item.get("value") or item.get("prefix")
            if value:
                out.append(str(value))
        for key in ("regex", "const"):
            if param.get(key):
                out.append(str(param[key]))
    return out


def pick_author_signature(invitation: dict[str, Any]) -> str:
    """The concrete Authors group this invitation lets us sign as, or ''."""
    for option in _signature_options(invitation):
        if "Authors" in option and not any(ch in option for ch in "*{}$"):
            return option
    return ""


def _content_spec(invitation: dict[str, Any]) -> dict[str, Any]:
    return ((invitation.get("edit") or {}).get("note") or {}).get("content") or {}


def build_note_content(
    invitation: dict[str, Any], title: str, body: str
) -> dict[str, Any]:
    """Fill the invitation's content schema with our response text."""
    spec = _content_spec(invitation)
    content: dict[str, Any] = {}
    body_key = next((k for k in _BODY_FIELDS if k in spec), "")
    if not body_key:
        raise ValueError(
            "invitation has no comment/rebuttal content field the factory can fill"
        )
    content[body_key] = {"value": body}
    if "title" in spec and title:
        content["title"] = {"value": title[:200]}
    for field, schema in spec.items():
        if field in content:
            continue
        param = ((schema or {}).get("value") or {}).get("param") or {}
        if not param.get("optional"):
            raise ValueError(
                f"invitation requires field {field!r} the factory cannot fill"
            )
    return content


def reply_invitations(forum_id: str, token: str) -> list[dict[str, Any]]:
    """Active invitations that accept replies on this forum."""
    reply = _request(
        f"{api_base()}/invitations?replyForum={urllib.parse.quote(forum_id)}",
        None,
        token=token,
    )
    return [inv for inv in reply.get("invitations") or [] if isinstance(inv, dict)]


def pick_reply_invitation(
    invitations: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Prefer a dedicated Rebuttal invitation, else Official_Comment."""
    for suffix in ("/Rebuttal", "/Official_Comment", "/Author_Rebuttal"):
        for inv in invitations:
            if str(inv.get("id") or "").endswith(suffix) and pick_author_signature(inv):
                return inv
    return None


def build_plan(
    forum_info: dict[str, Any],
    responses: dict[str, str],
    token: str,
) -> dict[str, Any]:
    """Map each reviewer response onto its forum reply target.

    ``forum_info`` is the audit record materialize_rebuttal_package wrote
    (forum id + ordered official reviews); ``responses`` maps reviewer ids
    (reviewer-1, reviewer-2, ...) to their final markdown bodies. The order
    contract is the one the package was built with: reviewer-N answers the
    N-th official review.
    """
    forum = str(forum_info.get("forum") or "")
    reviews = [r for r in forum_info.get("reviews") or [] if isinstance(r, dict)]
    if not forum or not reviews:
        raise ValueError(
            "no forum record - only packages imported from an OpenReview "
            "link carry the note ids replies must target"
        )
    invitation = pick_reply_invitation(reply_invitations(forum, token))
    if invitation is None:
        raise ValueError(
            "no open Rebuttal/Official_Comment invitation lets this account "
            "sign as Authors on this forum - is the rebuttal window open, "
            "and are you an author of this submission?"
        )
    signature = pick_author_signature(invitation)
    items: list[dict[str, Any]] = []
    for reviewer_id in sorted(responses, key=_reviewer_number):
        body = str(responses[reviewer_id] or "").strip()
        n = _reviewer_number(reviewer_id)
        if not body or n < 1 or n > len(reviews):
            items.append(
                {"reviewer_id": reviewer_id, "error": "no matching official review"}
            )
            continue
        review = reviews[n - 1]
        who = str((review.get("signatures") or ["Reviewer"])[-1]).rsplit("/", 1)[-1]
        title = f"Response to {who.replace('_', ' ')}"
        content = build_note_content(invitation, title, body)
        items.append(
            {
                "reviewer_id": reviewer_id,
                "replyto": str(review.get("id") or ""),
                "reviewer_label": who,
                "characters": len(body),
                "content": content,
            }
        )
    return {
        "forum": forum,
        "invitation": str(invitation.get("id") or ""),
        "signature": signature,
        "items": items,
    }


# --- Filling a venue's Official_Review form -----------------------------------
#
# The panel's review.md is structured (## Summary / Strengths / Weaknesses /
# Questions / Limitations, plus a scores block mirroring the OpenReview
# rubric), so most venue forms can be filled field-by-field from it. Anything
# the mapping cannot fill honestly is reported back as an error - a real
# venue form never gets placeholder junk.

_SECTION_FIELD_MAP = {
    "summary": ("summary",),
    "strengths": ("strengths",),
    "weaknesses": ("weaknesses",),
    "questions": ("questions for the authors", "questions"),
    "limitations": ("limitations and ethics", "limitations"),
}
_FULL_TEXT_FIELDS = ("review", "main_review", "detailed_comments", "comments")
_SCORE_FIELDS = ("rating", "confidence", "soundness", "presentation", "contribution")


def markdown_sections(md: str) -> dict[str, str]:
    """``## Heading`` blocks of a review, keyed by lower-cased heading."""
    out: dict[str, str] = {}
    current = ""
    lines: list[str] = []
    for line in str(md or "").splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if current:
                out[current] = "\n".join(lines).strip()
            current = m.group(1).strip().lower()
            lines = []
        elif current:
            lines.append(line)
    if current:
        out[current] = "\n".join(lines).strip()
    return out


def pick_reviewer_signature(invitation: dict[str, Any]) -> str:
    """The concrete reviewer group this invitation lets us sign as, or ''."""
    for option in _signature_options(invitation):
        if ("Reviewer" in option or "AnonReviewer" in option) and not any(
            ch in option for ch in "*{}$"
        ):
            return option
    return ""


def review_invitation(forum_id: str, token: str) -> dict[str, Any] | None:
    """The open Official_Review invitation the signed-in reviewer can use."""
    for inv in reply_invitations(forum_id, token):
        if str(inv.get("id") or "").endswith("/Official_Review") and pick_reviewer_signature(inv):
            return inv
    return None


def _enum_values(schema: dict[str, Any]) -> list[Any]:
    param = ((schema or {}).get("value") or {}).get("param") or {}
    values = param.get("enum") or []
    if not values and isinstance(param.get("items"), list):
        values = [i.get("value") for i in param["items"] if isinstance(i, dict)]
    return [v for v in values if v is not None]


def _leading_int(value: Any) -> int | None:
    m = re.match(r"\s*(\d+)", str(value))
    return int(m.group(1)) if m else None


def _pick_enum(values: list[Any], want: Any) -> Any:
    """The enum option matching a panel score - exact leading number first,
    else the numerically closest, else None."""
    want_n = _leading_int(want)
    if want_n is None:
        return None
    numbered = [(v, _leading_int(v)) for v in values]
    numbered = [(v, n) for v, n in numbered if n is not None]
    if not numbered:
        return None
    return min(numbered, key=lambda vn: abs(vn[1] - want_n))[0]


def _max_length(schema: dict[str, Any]) -> int:
    param = ((schema or {}).get("value") or {}).get("param") or {}
    try:
        return int(param.get("maxLength") or 0)
    except (TypeError, ValueError):
        return 0


def build_review_content(
    invitation: dict[str, Any],
    review_md: str,
    scores: dict[str, Any],
    headline: str = "",
) -> tuple[dict[str, Any], list[str]]:
    """Fill the invitation's review form from the panel report.

    Returns ``(content, mapping)`` where mapping says what went where; raises
    on a required field the report cannot fill honestly.
    """
    spec = _content_spec(invitation)
    if not spec:
        raise ValueError("invitation carries no content schema")
    sections = markdown_sections(review_md)
    content: dict[str, Any] = {}
    mapping: list[str] = []

    def put(field: str, value: Any, how: str) -> None:
        content[field] = {"value": value}
        mapping.append(f"{field} <- {how}")

    for field, schema in spec.items():
        key = field.lower()
        enum = _enum_values(schema)
        optional = bool(((schema or {}).get("value") or {}).get("param", {}).get("optional"))

        if key in _SCORE_FIELDS and enum:
            choice = _pick_enum(enum, scores.get(key))
            if choice is not None:
                put(field, choice, f"panel {key}={scores.get(key)}")
                continue
        if enum and len(enum) == 1:
            # Single-option enums are acknowledgements (code of conduct etc.).
            put(field, enum[0], "single-option acknowledgement")
            continue
        section_names = _SECTION_FIELD_MAP.get(key)
        if section_names:
            text = next((sections[n] for n in section_names if sections.get(n)), "")
            if text:
                limit = _max_length(schema)
                put(field, text[: limit or len(text)], f"review section '{section_names[0]}'")
                continue
        if key == "strengths_and_weaknesses":
            text = "\n\n".join(
                f"**{n.title()}**\n\n{sections[n]}"
                for n in ("strengths", "weaknesses")
                if sections.get(n)
            )
            if text:
                limit = _max_length(schema)
                put(field, text[: limit or len(text)], "strengths + weaknesses sections")
                continue
        if key in _FULL_TEXT_FIELDS:
            limit = _max_length(schema)
            put(field, review_md[: limit or len(review_md)], "full panel review")
            continue
        if key == "title":
            put(field, (headline or "Three-model panel review")[:200], "headline")
            continue
        if not optional:
            raise ValueError(
                f"venue form requires field {field!r} the panel report cannot fill - "
                "download review.md and submit that field by hand"
            )
    return content, mapping


# --- Posting ------------------------------------------------------------------


def post_reply(
    token: str,
    invitation_id: str,
    signature: str,
    forum: str,
    replyto: str,
    content: dict[str, Any],
) -> str:
    """POST one reply note; returns the created note id."""
    reply = _request(
        f"{api_base()}/notes/edits",
        {
            "invitation": invitation_id,
            "signatures": [signature],
            "note": {"forum": forum, "replyto": replyto, "content": content},
        },
        token=token,
    )
    note = reply.get("note") or {}
    return str(note.get("id") or reply.get("id") or "")


def execute_plan(plan: dict[str, Any], token: str) -> list[dict[str, Any]]:
    """Post every plan item; each item reports its own success or error."""
    results: list[dict[str, Any]] = []
    for item in plan.get("items") or []:
        if item.get("error"):
            results.append(dict(item))
            continue
        try:
            note_id = post_reply(
                token,
                plan["invitation"],
                plan["signature"],
                plan["forum"],
                item["replyto"],
                item["content"],
            )
            results.append(
                {"reviewer_id": item["reviewer_id"], "note_id": note_id, "ok": True}
            )
        except ValueError as exc:
            results.append({"reviewer_id": item["reviewer_id"], "error": str(exc)})
    return results
