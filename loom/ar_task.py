"""AR (Automated Research) task state and paper pipeline helpers.

An AR task is one of two roles, both stored in ``.RUD/<slug>/ar.json``:

* ``studio`` - the seed task created from the Create Task modal. It carries the
  research direction, the target venue and the idea-generation mode, mines
  recent papers, proposes idea cards, and spawns one child task per idea the
  user selects.
* ``paper``  - one child task per idea. It walks a fixed pipeline: LaTeX draft
  from the venue template, a human gate, N rounds of author/reviewer, a final
  human gate, then delivery of the compiled PDF.

Loom owns this state machine so the round counter, the human gates and the
delivered artifact survive an agent losing its context or the server
restarting; the agent-facing methodology lives in ``loom/skills/ar/*.md``.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loom.paths import ar_root, bundled_skills_path, paper_templates_dir
from loom.rud_task import RUD_DIR, WORK_SUBDIR, slugify, task_root

# --- Task kind --------------------------------------------------------------

KIND_AR = "ar"
# Tasks created before the rename carry kind="aris" in their task.json; they
# keep working as AR tasks (they simply have no ar.json until one is written).
LEGACY_AR_KINDS = frozenset({"aris"})


def normalize_kind(kind: str | None) -> str:
    """Canonical task kind, mapping the legacy ``aris`` kind onto ``ar``."""
    s = (kind or "").strip().lower()
    if s in LEGACY_AR_KINDS:
        return KIND_AR
    return s or "agent"


def is_ar_kind(kind: str | None) -> bool:
    return normalize_kind(kind) == KIND_AR


# --- Layout -----------------------------------------------------------------

AR_STATE = "ar.json"
ROUNDS_SUBDIR = "rounds"
# A paper task's work/ holds two sibling repositories: the experiment code and
# the manuscript. The agent pane starts at work/, so both are one cd away and
# both show up in the Changes tab.
CODE_SUBDIR = "code"
MANUSCRIPT_SUBDIR = "manuscript"
AUTHOR_NOTE = "author.md"
REVIEW_NOTE = "review.md"

# Separator between a studio's slug and its paper tasks'. Loom stores tasks
# flat, so the prefix is what groups a studio with its children on disk and in
# the sidebar.
CHILD_SLUG_SEP = "--"

ROLE_STUDIO = "studio"
ROLE_PAPER = "paper"

STAGE_DRAFT = "draft"
STAGE_AWAIT_DRAFT_REVIEW = "await_draft_review"
STAGE_LOOP = "loop"
STAGE_AWAIT_FINAL_REVIEW = "await_final_review"
STAGE_DELIVERED = "delivered"

STAGE_LABELS = {
    STAGE_DRAFT: "Writing draft",
    STAGE_AWAIT_DRAFT_REVIEW: "Waiting for your draft review",
    STAGE_LOOP: "Author / reviewer rounds",
    STAGE_AWAIT_FINAL_REVIEW: "Waiting for your final review",
    STAGE_DELIVERED: "Delivered",
}

GATE_DRAFT = "draft"
GATE_FINAL = "final"

DEFAULT_MAX_ROUNDS = 10
MAX_ROUNDS_LIMIT = 50

MODE_AUTO = "auto"
MODE_SEED = "seed"


# --- Catalogs ---------------------------------------------------------------

# Research directions offered in the Create Task modal, efficiency topics first.
#
# The list is grounded in a survey of ICLR/ICML/NeurIPS-accepted arXiv papers:
# every entry below corresponds to a theme with a real body of recent venue
# work behind it, so an idea in any of them has reviewers who know the area.
# Only the first few ``terms`` reach the arXiv query (see _ARXIV_MAX_TERMS), so
# order each list with its highest-signal phrase first; the rest document the
# area for the studio agent. ``custom`` lets the user type their own.
DIRECTIONS: tuple[dict[str, Any], ...] = (
    {
        "id": "quantization",
        "label": "Quantization (PTQ / QAT / low-bit)",
        "terms": ["quantization", "low-bit", "post-training quantization", "int4", "fp8"],
    },
    {
        "id": "sparsity",
        "label": "Pruning and sparsity",
        "terms": ["pruning", "sparsity", "structured pruning", "sparse attention"],
    },
    {
        "id": "distillation",
        "label": "Knowledge distillation",
        "terms": ["knowledge distillation", "distillation", "student model"],
    },
    {
        "id": "low-rank",
        "label": "Low-rank and weight compression",
        "terms": ["low-rank", "model compression", "matrix factorization", "SVD compression"],
    },
    {
        "id": "kv-cache",
        "label": "KV-cache compression",
        "terms": ["KV cache", "key-value cache", "cache compression", "paged attention"],
    },
    {
        "id": "cot-efficiency",
        "label": "Chain-of-thought efficiency (reasoning length)",
        "terms": ["chain-of-thought", "reasoning length", "overthinking", "efficient reasoning"],
    },
    {
        "id": "reasoning",
        "label": "Reasoning and test-time compute",
        "terms": ["test-time compute", "reasoning", "self-consistency", "process reward"],
    },
    {
        "id": "architectures",
        "label": "Efficient architectures (SSM / Mamba / hybrid)",
        "terms": ["state space model", "linear attention", "Mamba", "hybrid architecture"],
    },
    {
        "id": "long-context",
        "label": "Efficient attention and long context",
        "terms": ["long context", "efficient attention", "context extension", "sparse attention"],
    },
    {
        "id": "token-reduction",
        "label": "Token reduction and early exit",
        "terms": ["token pruning", "token merging", "early exit", "visual token compression"],
    },
    {
        "id": "speculative",
        "label": "Speculative decoding",
        "terms": ["speculative decoding", "draft model", "speculative sampling"],
    },
    {
        "id": "moe",
        "label": "Mixture of experts",
        "terms": ["mixture of experts", "expert routing", "sparse expert", "MoE"],
    },
    {
        "id": "diffusion-efficiency",
        "label": "Diffusion efficiency (few-step sampling)",
        "terms": ["diffusion distillation", "few-step sampling", "consistency model", "flow matching"],
    },
    {
        "id": "serving",
        "label": "Inference and serving systems",
        "terms": ["LLM serving", "inference system", "continuous batching", "throughput"],
    },
    {
        "id": "kernels",
        "label": "Kernels and compilers",
        "terms": ["CUDA kernel", "Triton", "fused kernel", "compiler"],
    },
    {
        "id": "peft",
        "label": "Fine-tuning (PEFT / LoRA)",
        "terms": ["parameter-efficient fine-tuning", "LoRA", "adapter", "PEFT"],
    },
    {
        "id": "memory-training",
        "label": "Memory-efficient training",
        "terms": ["memory-efficient training", "gradient checkpointing", "optimizer state", "offloading"],
    },
    {
        "id": "optimization",
        "label": "Optimizers and training stability",
        "terms": ["optimizer", "training stability", "learning rate schedule", "muon"],
    },
    {
        "id": "post-training",
        "label": "RL post-training (RLHF / RLVR)",
        "terms": ["RLHF", "preference optimization", "DPO", "reinforcement learning from human feedback"],
    },
    {
        "id": "data",
        "label": "Data curation and synthetic data",
        "terms": ["data curation", "synthetic data", "data selection", "pretraining data"],
    },
    {
        "id": "multimodal",
        "label": "Multimodal models",
        "terms": ["multimodal", "vision language model", "VLM", "image text"],
    },
    {
        "id": "agents",
        "label": "Agents and tool use",
        "terms": ["LLM agent", "tool use", "function calling", "agentic"],
    },
    {
        "id": "retrieval",
        "label": "Retrieval and RAG",
        "terms": ["retrieval augmented generation", "RAG", "dense retrieval", "reranking"],
    },
    {
        "id": "evaluation",
        "label": "Evaluation and benchmarks",
        "terms": ["benchmark", "evaluation", "contamination", "LLM judge"],
    },
    {
        "id": "custom",
        "label": "Custom (describe below)",
        "terms": [],
    },
)

DIRECTION_IDS = frozenset(d["id"] for d in DIRECTIONS)

# Target venues. ``template`` names a directory under ``loom/templates/paper/``
# holding that venue's official style files plus the section skeleton.
# ``invitation`` is the OpenReview submission invitation, used read-only to
# check a venue's live requirements and whether its window is open. The id
# shapes were verified against api2.openreview.net.
VENUES: tuple[dict[str, Any], ...] = (
    {
        "id": "iclr",
        "label": "ICLR",
        "template": "iclr",
        "aliases": ["ICLR"],
        "page_limit": 9,
        "invitation": "ICLR.cc/{year}/Conference/-/Submission",
    },
    {
        "id": "neurips",
        "label": "NeurIPS",
        "template": "neurips",
        "aliases": ["NeurIPS", "NIPS", "Neural Information Processing Systems"],
        "page_limit": 9,
        "invitation": "NeurIPS.cc/{year}/Conference/-/Submission",
    },
    {
        "id": "icml",
        "label": "ICML",
        "template": "icml",
        "aliases": ["ICML", "International Conference on Machine Learning"],
        "page_limit": 8,
        "invitation": "ICML.cc/{year}/Conference/-/Submission",
    },
    {
        "id": "colm",
        "label": "COLM",
        "template": "colm",
        "aliases": ["COLM", "Conference on Language Modeling"],
        "page_limit": 9,
        "invitation": "colmweb.org/COLM/{year}/Conference/-/Submission",
    },
)

VENUE_IDS = frozenset(v["id"] for v in VENUES)
DEFAULT_VENUE = "iclr"


def direction_entry(direction_id: str) -> dict[str, Any]:
    for d in DIRECTIONS:
        if d["id"] == direction_id:
            return d
    return DIRECTIONS[0]


def venue_entry(venue_id: str) -> dict[str, Any]:
    for v in VENUES:
        if v["id"] == venue_id:
            return v
    return VENUES[0]


def direction_label(state: dict[str, Any]) -> str:
    """Human-readable direction, preferring the user's custom text."""
    custom = str(state.get("custom_direction") or "").strip()
    if custom:
        return custom
    return str(direction_entry(str(state.get("direction") or "")).get("label", ""))


def catalog() -> dict[str, Any]:
    """Everything the create-task UI needs to render the AR fields."""
    return {
        "root": str(ar_root()),
        "relations": list(IDEA_RELATIONS),
        "directions": [{"id": d["id"], "label": d["label"]} for d in DIRECTIONS],
        "venues": [{"id": v["id"], "label": v["label"]} for v in VENUES],
        "default_venue": DEFAULT_VENUE,
        "default_max_rounds": DEFAULT_MAX_ROUNDS,
        "max_rounds_limit": MAX_ROUNDS_LIMIT,
        "modes": [
            {
                "id": MODE_AUTO,
                "label": "Auto direction",
                "hint": "Mine recent papers in this direction, then propose ideas to choose from.",
            },
            {
                "id": MODE_SEED,
                "label": "My idea",
                "hint": "Start from a rough idea you describe, and iterate it into concrete proposals.",
            },
        ],
    }


# --- State IO ---------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ar_state_path(project_root: Path, slug: str) -> Path:
    return task_root(project_root, slug) / AR_STATE


def read_ar_state(project_root: Path, slug: str) -> dict[str, Any]:
    """Return the task's AR state, or ``{}`` when it has none / is corrupt."""
    p = ar_state_path(project_root, slug)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def write_ar_state(project_root: Path, slug: str, state: dict[str, Any]) -> bool:
    """Atomically persist the AR state next to the task."""
    td = task_root(project_root, slug)
    if not td.is_dir():
        return False
    payload = dict(state)
    payload["updated_at"] = _now_iso()
    text = json.dumps(payload, indent=2, ensure_ascii=False)
    path = td / AR_STATE
    tmp = path.with_suffix(".json.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    except OSError:
        return False
    return True


def update_ar_state(
    project_root: Path, slug: str, **changes: Any
) -> dict[str, Any]:
    """Merge ``changes`` into the stored state and return the new state."""
    state = read_ar_state(project_root, slug)
    state.update(changes)
    write_ar_state(project_root, slug, state)
    return read_ar_state(project_root, slug)


# --- State factories --------------------------------------------------------


def _clamp_rounds(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_MAX_ROUNDS
    return max(1, min(MAX_ROUNDS_LIMIT, n))


def new_studio_state(
    *,
    direction: str = "",
    custom_direction: str = "",
    venue: str = DEFAULT_VENUE,
    mode: str = MODE_AUTO,
    seed_idea: str = "",
    max_rounds: Any = DEFAULT_MAX_ROUNDS,
) -> dict[str, Any]:
    d = (direction or "").strip().lower()
    if d not in DIRECTION_IDS:
        d = DIRECTIONS[0]["id"]
    v = (venue or "").strip().lower()
    if v not in VENUE_IDS:
        v = DEFAULT_VENUE
    m = (mode or "").strip().lower()
    if m not in {MODE_AUTO, MODE_SEED}:
        m = MODE_AUTO
    return {
        "role": ROLE_STUDIO,
        "direction": d,
        "custom_direction": custom_direction.strip(),
        "venue": v,
        "mode": m,
        "seed_idea": seed_idea.strip(),
        "max_rounds": _clamp_rounds(max_rounds),
        "papers": [],
        "papers_updated_at": "",
        "ideas": [],
        "ideas_updated_at": "",
        "cost_usd": 0.0,
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }


def new_paper_state(
    *,
    parent_slug: str,
    idea: dict[str, Any],
    venue: str = DEFAULT_VENUE,
    direction: str = "",
    custom_direction: str = "",
    max_rounds: Any = DEFAULT_MAX_ROUNDS,
    author_model: str = "",
    reviewer_model: str = "",
) -> dict[str, Any]:
    v = (venue or "").strip().lower()
    if v not in VENUE_IDS:
        v = DEFAULT_VENUE
    return {
        "role": ROLE_PAPER,
        "parent_slug": parent_slug,
        "idea": dict(idea or {}),
        "venue": v,
        "direction": direction,
        "custom_direction": custom_direction,
        "stage": STAGE_DRAFT,
        "round": 0,
        "max_rounds": _clamp_rounds(max_rounds),
        "rounds": [],
        "gates": [],
        "loop_running": False,
        "author_model": author_model,
        "reviewer_model": reviewer_model,
        "stop_rating": DEFAULT_STOP_RATING,
        "stop_reason": "",
        "cost_usd": 0.0,
        "paper_dir": "",
        "pdf_path": "",
        "pdf_built_at": "",
        "pdf_error": "",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
    }


def default_general_goal(state: dict[str, Any]) -> str:
    """Stand-in general goal for a studio task.

    An AR task has no goal to interview about - what it has is the paper's
    content, which the user gives as the seed idea. When they leave that empty
    (auto mode), describe the direction instead so the task header, the pane
    prompt and OpenClaw all still say something useful.
    """
    venue = venue_entry(str(state.get("venue") or DEFAULT_VENUE)).get("label")
    seed = str(state.get("seed_idea") or "").strip()
    if seed:
        return f"Write a paper for {venue} on: {seed}"
    return (
        f"Find and develop a publishable idea for {venue} in "
        f"{direction_label(state)}: mine recent work in this direction, propose "
        "ideas, and turn the ones worth pursuing into paper tasks."
    )


def is_studio(state: dict[str, Any]) -> bool:
    return str(state.get("role") or "") == ROLE_STUDIO


def is_paper(state: dict[str, Any]) -> bool:
    return str(state.get("role") or "") == ROLE_PAPER


# --- Idea helpers -----------------------------------------------------------

IDEA_STATUS_PROPOSED = "proposed"
IDEA_STATUS_SPAWNED = "spawned"

# How an idea stands relative to the work it came from. A small closed
# vocabulary keeps the knowledge graph readable and makes a novelty claim
# checkable: "extends" and "contradicts" are very different bets.
IDEA_RELATIONS = (
    "extends",
    "contradicts",
    "combines",
    "ports",
    "controls-for",
    "relates-to",
)
DEFAULT_RELATION = "relates-to"


def normalize_edge(raw: Any) -> dict[str, str] | None:
    """One ``idea -> prior work`` link, as the knowledge graph draws it."""
    if isinstance(raw, str):
        raw = {"paper": raw}
    if not isinstance(raw, dict):
        return None
    paper = str(raw.get("paper") or raw.get("arxiv_id") or raw.get("id") or "").strip()
    title = str(raw.get("title") or "").strip()
    if not paper and not title:
        return None
    relation = str(raw.get("relation") or "").strip().lower().replace(" ", "-")
    if relation not in IDEA_RELATIONS:
        relation = DEFAULT_RELATION
    return {"paper": paper, "title": title, "relation": relation}


def normalize_idea(raw: Any, index: int = 0) -> dict[str, Any]:
    """Coerce a model-proposed idea into the card shape the UI renders."""
    d = raw if isinstance(raw, dict) else {}
    experiments = d.get("experiments")
    if isinstance(experiments, str):
        experiments = [experiments]
    if not isinstance(experiments, list):
        experiments = []
    try:
        score = float(d.get("score", 0) or 0)
    except (TypeError, ValueError):
        score = 0.0
    raw_edges = d.get("derived_from")
    if isinstance(raw_edges, (str, dict)):
        raw_edges = [raw_edges]
    edges = [e for e in (normalize_edge(x) for x in (raw_edges or [])) if e] \
        if isinstance(raw_edges, list) else []

    idea_id = str(d.get("id") or "").strip() or f"idea-{index + 1}"
    return {
        "id": idea_id,
        "derived_from": edges,
        "title": str(d.get("title") or "").strip() or f"Idea {index + 1}",
        "hypothesis": str(d.get("hypothesis") or "").strip(),
        "novelty": str(d.get("novelty") or "").strip(),
        "metric": str(d.get("metric") or "").strip(),
        "experiments": [str(x).strip() for x in experiments if str(x).strip()],
        "risk": str(d.get("risk") or "").strip(),
        "score": round(score, 2),
        "status": str(d.get("status") or IDEA_STATUS_PROPOSED),
        "child_slug": str(d.get("child_slug") or ""),
    }


def child_slug(parent_slug: str, title: str, limit: int = 80) -> str:
    """Slug for a paper task, prefixed so it groups under its studio."""
    base = f"{parent_slug}{CHILD_SLUG_SEP}{slugify(title)}"
    return base[:limit].rstrip("-_") or f"{parent_slug}{CHILD_SLUG_SEP}paper"


def find_idea(state: dict[str, Any], idea_id: str) -> dict[str, Any] | None:
    for idea in state.get("ideas") or []:
        if isinstance(idea, dict) and str(idea.get("id")) == idea_id:
            return idea
    return None


def idea_summary(idea: dict[str, Any]) -> str:
    """Plain-text idea brief injected into agent prompts."""
    lines = [f"Title: {idea.get('title', '')}"]
    for key, label in (
        ("hypothesis", "Hypothesis"),
        ("novelty", "Why it is new"),
        ("metric", "Headline metric"),
        ("risk", "Main risk"),
    ):
        value = str(idea.get(key) or "").strip()
        if value:
            lines.append(f"{label}: {value}")
    experiments = [str(x) for x in (idea.get("experiments") or []) if str(x).strip()]
    if experiments:
        lines.append("Planned experiments:")
        lines.extend(f"  - {x}" for x in experiments)
    return "\n".join(lines)


# --- Paper task layout ------------------------------------------------------


def ensure_ar_root() -> tuple[Path, bool]:
    """Create the AR project root if it isn't there. Returns ``(path, created)``."""
    root = ar_root()
    existed = (root / RUD_DIR).is_dir()
    try:
        (root / RUD_DIR).mkdir(parents=True, exist_ok=True)
    except OSError:
        return root, False
    return root, not existed


def shared_cache_dir() -> Path:
    """One model/dataset cache for every AR task on this host."""
    return ar_root() / ".cache"


def agent_env() -> dict[str, str]:
    """Environment for an AR agent pane.

    Left to itself an agent puts a fresh cache next to each experiment, so the
    same checkpoints get downloaded again per experiment and per task - the
    first paper here spent 18 GB that way. Pointing every pane at one cache
    makes the second download a no-op.
    """
    cache = shared_cache_dir()
    hf = cache / "huggingface"
    for path in (hf, cache / "torch", cache / "pip"):
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
    return {
        "HF_HOME": str(hf),
        "HF_HUB_CACHE": str(hf / "hub"),
        "HF_DATASETS_CACHE": str(hf / "datasets"),
        "TORCH_HOME": str(cache / "torch"),
        "PIP_CACHE_DIR": str(cache / "pip"),
    }


def work_root(project_root: Path, slug: str) -> Path:
    """``<task>/work/`` - where the agent pane starts and both repos live."""
    return task_root(project_root, slug) / WORK_SUBDIR


def paper_root(project_root: Path, slug: str) -> Path:
    """``<task>/work/manuscript/`` - the LaTeX sources, its own git repo."""
    return work_root(project_root, slug) / MANUSCRIPT_SUBDIR


def code_root(project_root: Path, slug: str) -> Path:
    """``<task>/work/code/`` - the experiment code, its own git repo.

    A paper's experiments get a repository of their own rather than a branch of
    whatever project spawned the task: the two have separate lifetimes, and a
    paper about one subject should not bury its code in an unrelated library's
    history.
    """
    return work_root(project_root, slug) / CODE_SUBDIR


def _git_init(repo: Path, message: str) -> tuple[bool, str]:
    """Create *repo* as a git repository with one initial commit."""
    repo.mkdir(parents=True, exist_ok=True)
    if (repo / ".git").exists():
        return True, "already a repository"
    steps = [
        ["git", "init", "-q"],
        ["git", "add", "-A"],
        ["git", "-c", "user.name=Loom AR", "-c", "user.email=ar@loom.local",
         "commit", "-q", "--allow-empty", "-m", message],
    ]
    for cmd in steps:
        try:
            proc = subprocess.run(
                cmd, cwd=str(repo), capture_output=True, text=True, timeout=60
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)
        if proc.returncode != 0:
            return False, (proc.stderr or proc.stdout or "").strip()[:300]
    return True, "initialised"


def init_paper_workspace(
    project_root: Path,
    slug: str,
    venue: str,
    idea: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Lay out ``work/code`` and ``work/manuscript`` for a new paper task."""
    code = code_root(project_root, slug)
    paper = paper_root(project_root, slug)
    title = str((idea or {}).get("title") or slug)

    code.mkdir(parents=True, exist_ok=True)
    readme = code / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# Experiments for: {title}\n\n"
            "Code backing the paper in `../manuscript/`. One directory per\n"
            "experiment, each with its runner, its aggregation step and the\n"
            "exact command that produced the numbers in the paper.\n",
            encoding="utf-8",
        )
    seeded, message = seed_paper_skeleton(paper, venue, idea)
    code_ok, code_msg = _git_init(code, f"Start experiments for {title}")
    paper_ok, paper_msg = _git_init(paper, f"Start the {venue_entry(venue)['label']} manuscript")
    return {
        "ok": seeded and code_ok and paper_ok,
        "code": str(code),
        "manuscript": str(paper),
        "skeleton": message,
        "code_repo": code_msg,
        "manuscript_repo": paper_msg,
    }


def rounds_root(project_root: Path, slug: str) -> Path:
    """Round artifacts stay in the task dir, not the worktree: they are Loom
    bookkeeping, not part of the paper the user ships."""
    return task_root(project_root, slug) / ROUNDS_SUBDIR


def round_dir(project_root: Path, slug: str, n: int) -> Path:
    return rounds_root(project_root, slug) / f"round-{n:02d}"


def author_note_path(project_root: Path, slug: str, n: int) -> Path:
    return round_dir(project_root, slug, n) / AUTHOR_NOTE


def review_note_path(project_root: Path, slug: str, n: int) -> Path:
    return round_dir(project_root, slug, n) / REVIEW_NOTE


# --- Paper skeleton ---------------------------------------------------------

SHARED_TEMPLATE = "_shared"
TOKEN_TITLE = "@@TITLE@@"
TOKEN_RUNNING_TITLE = "@@RUNNING_TITLE@@"
TOKEN_KEYWORDS = "@@KEYWORDS@@"


def templates_paper_dir() -> Path:
    return paper_templates_dir()


def venue_template_dir(venue: str) -> Path:
    return templates_paper_dir() / str(venue_entry(venue).get("template") or venue)


def venue_is_available(venue: str) -> bool:
    """True when the venue's style files have been vendored."""
    d = venue_template_dir(venue)
    return (d / "main.tex").is_file() and any(d.glob("*.sty"))


def _tex_escape(text: str) -> str:
    out = str(text or "")
    for char, repl in (
        ("\\", r"\textbackslash{}"),
        ("&", r"\&"),
        ("%", r"\%"),
        ("$", r"\$"),
        ("#", r"\#"),
        ("_", r"\_"),
        ("{", r"\{"),
        ("}", r"\}"),
        ("~", r"\textasciitilde{}"),
        ("^", r"\textasciicircum{}"),
    ):
        out = out.replace(char, repl)
    return out


def _copy_tree(src: Path, dest: Path) -> None:
    """Copy ``src`` over ``dest``, merging directories and replacing files."""
    for item in sorted(src.rglob("*")):
        rel = item.relative_to(src)
        target = dest / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)


def seed_paper_skeleton(
    dest: Path,
    venue: str,
    idea: dict[str, Any] | None = None,
    *,
    overwrite: bool = False,
) -> tuple[bool, str]:
    """Lay the venue's LaTeX skeleton down at ``dest``.

    The shared section scaffold goes down first and the venue directory is
    copied over it, so a venue can override any shared file just by shipping
    its own copy. Returns ``(ok, message)``.
    """
    venue_dir = venue_template_dir(venue)
    if not (venue_dir / "main.tex").is_file():
        return False, f"no template for venue {venue!r} (run scripts/fetch_paper_styles.py)"
    if (dest / "main.tex").is_file() and not overwrite:
        return False, f"{dest / 'main.tex'} already exists"

    shared = templates_paper_dir() / SHARED_TEMPLATE
    try:
        dest.mkdir(parents=True, exist_ok=True)
        if shared.is_dir():
            _copy_tree(shared, dest)
        _copy_tree(venue_dir, dest)
        (dest / "figures").mkdir(exist_ok=True)
        gitkeep = dest / "figures" / ".gitkeep"
        if not gitkeep.exists():
            gitkeep.write_text("", encoding="utf-8")
    except OSError as exc:
        return False, f"failed to seed skeleton: {exc}"

    title = str((idea or {}).get("title") or "").strip() or "Untitled AR Submission"
    keywords = str((idea or {}).get("metric") or "").strip() or "machine learning"
    running = title if len(title) <= 60 else title[:57].rstrip() + "..."
    main = dest / "main.tex"
    try:
        text = main.read_text(encoding="utf-8")
        text = (
            text.replace(TOKEN_TITLE, _tex_escape(title))
            .replace(TOKEN_RUNNING_TITLE, _tex_escape(running))
            .replace(TOKEN_KEYWORDS, _tex_escape(keywords))
        )
        main.write_text(text, encoding="utf-8")
    except OSError as exc:
        return False, f"failed to write main.tex: {exc}"
    return True, f"seeded {venue} skeleton at {dest}"


# --- PDF build --------------------------------------------------------------

_LOG_TAIL_CHARS = 4000


def build_pdf(paper_dir: Path, timeout: int = 420) -> dict[str, Any]:
    """Compile ``main.tex`` with latexmk.

    Runs with ``-f`` so a draft that still has a broken snippet somewhere
    produces a PDF the human gate can look at, rather than nothing at all; the
    caller decides how loudly to report a non-zero exit.
    """
    main = paper_dir / "main.tex"
    if not main.is_file():
        return {"ok": False, "error": f"no main.tex under {paper_dir}"}
    cmd = [
        "latexmk",
        "-pdf",
        "-f",
        "-interaction=nonstopmode",
        "-file-line-error",
        "main.tex",
    ]
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(paper_dir),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"latexmk timed out after {timeout}s"}
    except OSError as exc:
        return {"ok": False, "error": f"latexmk not runnable: {exc}"}

    pdf = paper_dir / "main.pdf"
    log = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
    tail = log[-_LOG_TAIL_CHARS:]
    missing = missing_latex_packages(log)
    if not pdf.is_file():
        error = "latexmk produced no PDF"
        if missing:
            error += (
                f" - missing LaTeX package(s): {', '.join(missing)}"
                " (Debian: sudo apt-get install texlive-fonts-extra texlive-science)"
            )
        return {
            "ok": False,
            "error": error,
            "missing_packages": missing,
            "log": tail,
            "returncode": proc.returncode,
        }
    return {
        "ok": True,
        "pdf": str(pdf),
        "bytes": pdf.stat().st_size,
        "clean": proc.returncode == 0,
        "missing_packages": missing,
        "log": tail,
        "returncode": proc.returncode,
    }


def missing_latex_packages(log: str) -> list[str]:
    """Package names behind ``File 'x.sty' not found`` errors.

    A missing style file is the one build failure a user cannot fix by editing
    the paper, so it is worth separating from ordinary LaTeX errors.
    """
    names: list[str] = []
    for match in re.finditer(r"File `([^']+)\.(?:sty|cls)' not found", log or ""):
        name = match.group(1)
        if name not in names:
            names.append(name)
    return names


def latex_errors(log: str, limit: int = 20) -> list[str]:
    """Pull ``file:line: message`` errors out of a latexmk log."""
    out: list[str] = []
    for line in (log or "").splitlines():
        if re.match(r"^[^:]+\.(tex|sty|cls):\d+:", line.strip()):
            out.append(line.strip())
            if len(out) >= limit:
                break
    return out


def paper_source_text(paper_dir: Path, limit: int = 90000) -> str:
    """Concatenate the paper's LaTeX sources for a reviewer prompt."""
    parts: list[str] = []
    total = 0
    candidates = [paper_dir / "main.tex"]
    sections = paper_dir / "sections"
    if sections.is_dir():
        candidates.extend(sorted(sections.glob("*.tex")))
    for path in candidates:
        try:
            body = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            name = str(path.relative_to(paper_dir))
        except ValueError:
            name = path.name
        chunk = f"% ===== {name} =====\n{body}\n"
        if total + len(chunk) > limit:
            parts.append(chunk[: max(0, limit - total)])
            parts.append("\n% ... (sources truncated for review) ...\n")
            break
        parts.append(chunk)
        total += len(chunk)
    return "".join(parts).strip()


# --- Paper mining -----------------------------------------------------------

ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV_CATEGORIES = ("cs.LG", "cs.CL", "cs.AI")
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_ARXIV_NS = "{http://arxiv.org/schemas/atom}"

# arXiv asks for one request every three seconds and throttles an IP that
# ignores it by silently hanging subsequent connections, which looks exactly
# like a network outage. Serialise our calls so a burst of UI clicks cannot put
# the host in that state.
_ARXIV_MIN_INTERVAL = 3.0
_arxiv_lock = threading.Lock()
_arxiv_last_call = 0.0

# Long phrases make arXiv's query planner crawl, so only the first few terms go
# into the query; the rest are what the studio agent searches for itself.
_ARXIV_MAX_TERMS = 3


def _arxiv_query(terms: list[str]) -> str:
    cats = " OR ".join(f"cat:{c}" for c in ARXIV_CATEGORIES)
    cleaned = [t.strip() for t in terms if t and t.strip()][:_ARXIV_MAX_TERMS]
    if not cleaned:
        return f"({cats})"
    phrases = " OR ".join(f'abs:"{t}"' for t in cleaned)
    return f"({cats}) AND ({phrases})"


def _arxiv_fetch(url: str, timeout: int, attempts: int = 3) -> tuple[str, str]:
    """Fetch an arXiv feed, honouring their rate limit. Returns ``(body, err)``."""
    global _arxiv_last_call
    last_err = ""
    for attempt in range(attempts):
        with _arxiv_lock:
            wait = _ARXIV_MIN_INTERVAL - (time.monotonic() - _arxiv_last_call)
            if wait > 0:
                time.sleep(wait)
            _arxiv_last_call = time.monotonic()
        req = urllib.request.Request(url, headers={"User-Agent": "loom-ar/1.0"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8", errors="replace"), ""
        except urllib.error.HTTPError as exc:
            last_err = f"HTTP {exc.code}"
            if exc.code not in (429, 500, 502, 503):
                break
        except (urllib.error.URLError, OSError) as exc:
            last_err = str(exc)
        if attempt < attempts - 1:
            time.sleep(2.0 * (attempt + 1))
    return "", last_err or "unknown error"


def _detect_venue(text: str) -> str:
    """Venue named in an arXiv comment field, if any."""
    haystack = text or ""
    for v in VENUES:
        for alias in v["aliases"]:
            if re.search(rf"\b{re.escape(alias)}\b", haystack, re.IGNORECASE):
                year = re.search(
                    rf"{re.escape(alias)}\s*'?\s*(20\d{{2}})", haystack, re.IGNORECASE
                )
                return f"{v['label']} {year.group(1)}" if year else str(v["label"])
    return ""


def parse_arxiv_feed(xml_text: str) -> list[dict[str, Any]]:
    """Parse an arXiv Atom feed into paper records."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []
    papers: list[dict[str, Any]] = []
    for entry in root.findall(f"{_ATOM_NS}entry"):

        def text_of(tag: str, ns: str = _ATOM_NS) -> str:
            node = entry.find(f"{ns}{tag}")
            return " ".join((node.text or "").split()) if node is not None else ""

        url = text_of("id")
        comment = text_of("comment", _ARXIV_NS)
        authors = [
            " ".join((n.text or "").split())
            for n in entry.findall(f"{_ATOM_NS}author/{_ATOM_NS}name")
        ]
        papers.append(
            {
                "title": text_of("title"),
                "summary": text_of("summary")[:1200],
                "authors": authors[:8],
                "published": text_of("published")[:10],
                "updated": text_of("updated")[:10],
                "url": url,
                "arxiv_id": url.rsplit("/", 1)[-1] if url else "",
                "comment": comment,
                "venue": _detect_venue(comment),
            }
        )
    return papers


def mine_papers(
    direction: str = "",
    custom_direction: str = "",
    *,
    limit: int = 40,
    venue_only: bool = False,
    timeout: int = 45,
) -> dict[str, Any]:
    """Recent arXiv papers for a research direction, newest first.

    arXiv is the only source mined automatically: OpenReview's API answers
    scripted requests with a challenge-verification 403, so venue-accepted lists
    are left to the studio agent's own web search. Papers that announce a venue
    in their comment field are tagged, and ``venue_only`` keeps just those.
    """
    entry = direction_entry(direction)
    terms = list(entry.get("terms") or [])
    extra = (custom_direction or "").strip()
    if extra:
        terms.append(extra)
    if not terms:
        return {"ok": False, "error": "no search terms for this direction", "papers": []}

    params = {
        "search_query": _arxiv_query(terms),
        "start": "0",
        "max_results": str(max(1, min(200, int(limit) * 2 if venue_only else int(limit)))),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    body, err = _arxiv_fetch(url, timeout=timeout)
    if err:
        return {
            "ok": False,
            "error": (
                f"arXiv query failed ({err}). arXiv throttles bursts by hanging "
                "later requests; wait a few minutes, or let the studio agent "
                "survey the direction with its own web search instead."
            ),
            "papers": [],
        }

    papers = parse_arxiv_feed(body)
    if venue_only:
        papers = [p for p in papers if p.get("venue")]
    return {"ok": True, "papers": papers[: int(limit)], "query": params["search_query"]}


# --- Headless model calls ---------------------------------------------------


# --- Job logs ---------------------------------------------------------------

# Mining, ideation and review each take minutes behind a single button, so they
# stream a progress log to disk. Bounded: this is a live activity feed, not an
# audit trail, and the transcript already lives in the model's own session.
AR_LOG_MAX_LINES = 400
AR_LOG_TAIL = 60

JOB_PAPERS = "papers"
JOB_IDEAS = "ideas"
JOB_REVIEW = "review"


def job_log_path(project_root: Path, slug: str, job: str) -> Path:
    return task_root(project_root, slug) / f"ar-{job}.log"


def reset_job_log(path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("", encoding="utf-8")
    except OSError:
        pass


def append_job_log(path: Path, line: str) -> None:
    stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {line}\n")
    except OSError:
        return
    # Trim in place once the file grows past the cap.
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if len(lines) > AR_LOG_MAX_LINES * 2:
            path.write_text(
                "\n".join(lines[-AR_LOG_MAX_LINES:]) + "\n", encoding="utf-8"
            )
    except OSError:
        pass


def read_job_log(path: Path, limit: int = AR_LOG_TAIL) -> list[str]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return [ln for ln in lines[-limit:] if ln.strip()]


# The field that best identifies what a tool call is actually doing, per tool.
_TOOL_INPUT_KEYS = ("query", "command", "url", "pattern", "file_path", "path", "prompt")

_HEARTBEAT_POLL_SECONDS = 15.0
_HEARTBEAT_SILENCE_SECONDS = 30.0


def _clip(text: str, limit: int = 120) -> str:
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


def stream_event_line(event: dict[str, Any]) -> str | None:
    """One human-readable progress line for a `stream-json` event.

    Returns ``None`` for events with nothing worth showing, so the log reads as
    a sequence of actions rather than a protocol dump.
    """
    kind = str(event.get("type") or "")

    if kind == "system" and event.get("subtype") == "init":
        return f"started · model {event.get('model', '?')}"

    if kind == "assistant":
        out: list[str] = []
        for block in (event.get("message") or {}).get("content") or []:
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_use":
                name = block.get("name", "tool")
                data = block.get("input") or {}
                detail = ""
                for key in _TOOL_INPUT_KEYS:
                    if data.get(key):
                        detail = _clip(data[key], 100)
                        break
                out.append(f"→ {name}{': ' + detail if detail else ''}")
            elif block.get("type") == "text" and str(block.get("text") or "").strip():
                out.append(_clip(block["text"], 160))
        return "\n".join(out) or None

    if kind == "user":
        for block in (event.get("message") or {}).get("content") or []:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                content = block.get("content")
                if isinstance(content, list):
                    content = " ".join(
                        str(c.get("text", "")) for c in content if isinstance(c, dict)
                    )
                return f"   ← {_clip(content, 100)}"
        return None

    if kind == "result":
        secs = round(float(event.get("duration_ms") or 0) / 1000, 1)
        cost = event.get("total_cost_usd")
        bits = [f"finished in {secs}s", f"{event.get('num_turns', '?')} turns"]
        if isinstance(cost, (int, float)):
            bits.append(f"${cost:.3f}")
        return "· " + ", ".join(bits)

    return None


def _run_headless(
    prompt: str,
    model: str = "",
    timeout: int = 600,
    on_line: Any = None,
) -> dict[str, Any]:
    """One-shot `claude -p` call against the logged-in host CLI.

    Runs in `stream-json` mode so a caller can watch the tool calls as they
    happen: these jobs take minutes, and a button that only says "working" for
    that long is indistinguishable from one that has hung.
    """
    cmd = [
        "claude",
        "-p",
        prompt,
        "--dangerously-skip-permissions",
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    if model:
        cmd += ["--model", model]
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        return {"ok": False, "error": f"claude CLI not runnable: {exc}", "cost": 0.0}

    # A hung CLI would block on readline forever, so enforce the deadline out
    # of band rather than around a single read.
    killer = threading.Timer(timeout, proc.kill)
    killer.start()
    # Composing a long answer produces no events for a minute or more, which
    # reads as a hang. A heartbeat during silence keeps the log honest.
    heartbeat_stop = threading.Event()
    last_line_at = [time.monotonic()]
    started_at = time.monotonic()

    def _heartbeat() -> None:
        while not heartbeat_stop.wait(_HEARTBEAT_POLL_SECONDS):
            if time.monotonic() - last_line_at[0] >= _HEARTBEAT_SILENCE_SECONDS:
                on_line(f"… still working ({int(time.monotonic() - started_at)}s)")
                last_line_at[0] = time.monotonic()

    if on_line is not None:
        threading.Thread(target=_heartbeat, daemon=True).start()

    final = ""
    cost = 0.0
    texts: list[str] = []
    try:
        for raw in proc.stdout or ():
            line = raw.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "result":
                final = str(event.get("result") or "")
                try:
                    cost = float(event.get("total_cost_usd") or 0.0)
                except (TypeError, ValueError):
                    cost = 0.0
            elif event.get("type") == "assistant":
                for block in (event.get("message") or {}).get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "text":
                        texts.append(str(block.get("text") or ""))
            if on_line is not None:
                message = stream_event_line(event)
                if message:
                    for part in message.split("\n"):
                        on_line(part)
                    last_line_at[0] = time.monotonic()
    finally:
        heartbeat_stop.set()
        killer.cancel()
        try:
            stderr = (proc.stderr.read() if proc.stderr else "") or ""
        except (OSError, ValueError):
            stderr = ""
        try:
            proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()

    if proc.returncode is not None and proc.returncode < 0:
        return {"ok": False, "error": f"model call timed out after {timeout}s"}
    text = (final or "\n".join(texts)).strip()
    if not text:
        return {
            "ok": False,
            "error": "empty response from claude",
            "stderr": stderr[-500:],
            "cost": cost,
        }
    return {"ok": True, "text": text, "cost": cost}


def _extract_json_array(text: str) -> list[Any] | None:
    """Pull a JSON array out of a model reply, fenced or bare."""
    fenced = re.search(r"```(?:json)?\s*(\[.*?\])\s*```", text, re.DOTALL)
    candidates = [fenced.group(1)] if fenced else []
    bare = re.search(r"(\[\s*\{.*\}\s*\])", text, re.DOTALL)
    if bare:
        candidates.append(bare.group(1))
    for blob in candidates:
        try:
            data = json.loads(blob)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            return data
    return None


def _papers_block(papers: list[dict[str, Any]], limit: int = 30) -> str:
    if not papers:
        return "(no papers mined yet - survey the direction yourself)"
    lines: list[str] = []
    for p in papers[:limit]:
        venue = f" [{p['venue']}]" if p.get("venue") else ""
        lines.append(f"- {p.get('title', '')}{venue} ({p.get('published', '')}) {p.get('url', '')}")
        summary = str(p.get("summary") or "")[:320]
        if summary:
            lines.append(f"    {summary}")
    return "\n".join(lines)


def propose_ideas(
    state: dict[str, Any],
    skill_text: str,
    *,
    count: int = 6,
    model: str = "",
    timeout: int = 900,
    on_line: Any = None,
) -> dict[str, Any]:
    """Ask the model for idea cards, in whichever mode the studio is set to."""
    mode = str(state.get("mode") or MODE_AUTO)
    venue = str(venue_entry(str(state.get("venue") or DEFAULT_VENUE)).get("label"))
    seed = str(state.get("seed_idea") or "").strip()
    papers = [p for p in (state.get("papers") or []) if isinstance(p, dict)]

    if mode == MODE_SEED and seed:
        task_block = (
            "MODE: seed idea. The user supplied the idea below. Sharpen it into "
            f"{count} concrete variants that differ in mechanism, and say plainly "
            "in the `novelty` field if the seed as written is already covered by "
            "existing work.\n\n"
            f"User's idea:\n{seed}"
        )
    else:
        task_block = (
            f"MODE: auto direction. Propose {count} ideas in this direction, "
            "grounded in the recent work listed below plus your own search."
        )
        if seed:
            task_block += f"\n\nExtra context from the user:\n{seed}"

    prompt = (
        f"{skill_text}\n\n"
        "=== end methodology ===\n\n"
        f"Research direction: {direction_label(state)}\n"
        f"Target venue: {venue}\n\n"
        f"{task_block}\n\n"
        f"Recent papers mined from arXiv:\n{_papers_block(papers)}\n\n"
        "Reply with the JSON array of idea cards and nothing else."
    )
    if on_line is not None:
        on_line(
            f"asking for {count} idea(s) in {direction_label(state)} "
            f"for {venue} ({mode} mode, {len(papers)} mined paper(s))"
        )
    res = _run_headless(prompt, model=model, timeout=timeout, on_line=on_line)
    if not res.get("ok"):
        return res
    raw = _extract_json_array(str(res.get("text") or ""))
    if raw is None:
        return {
            "ok": False,
            "error": "model did not return a JSON array of ideas",
            "raw": str(res.get("text") or "")[-1500:],
        }
    ideas = [normalize_idea(item, i) for i, item in enumerate(raw)]
    ideas = [i for i in ideas if i["title"]]
    ideas.sort(key=lambda i: i["score"], reverse=True)
    if on_line is not None:
        on_line(f"parsed {len(ideas)} idea card(s)")
    return {"ok": True, "ideas": ideas}


def link_ideas(
    state: dict[str, Any],
    *,
    model: str = "",
    timeout: int = 600,
    on_line: Any = None,
) -> dict[str, Any]:
    """Recover the graph edges for ideas that have none.

    An idea's ``novelty`` field already names the work it stands on or against
    - that is what makes it a novelty claim - but ideas proposed before edges
    existed, or pasted in by hand, carry that only as prose. This reads it back
    out as structured edges, leaving everything else about the idea untouched.
    """
    ideas = [i for i in (state.get("ideas") or []) if isinstance(i, dict)]
    todo = [i for i in ideas if not i.get("derived_from")]
    if not todo:
        return {"ok": True, "ideas": ideas, "linked": 0}

    papers = [p for p in (state.get("papers") or []) if isinstance(p, dict)]
    paper_block = "\n".join(
        f"- {p.get('arxiv_id', '')} {p.get('title', '')}" for p in papers[:40]
    ) or "(none mined)"
    idea_block = "\n\n".join(
        f"id: {i['id']}\ntitle: {i.get('title', '')}\nnovelty: {i.get('novelty', '')}"
        for i in todo
    )
    prompt = f"""You are grounding research ideas against the prior work they cite.

Each idea below has a `novelty` paragraph that already names the work it builds
on or argues against. Turn that prose into the edges of a knowledge graph.

Papers mined for this direction (arXiv id, then title):
{paper_block}

Ideas:
{idea_block}

Reply with JSON only - an array, one entry per idea:

[{{"id": "<the idea's id, copied exactly>",
  "derived_from": [
    {{"paper": "<arXiv id, bare, or empty>", "title": "<short name, e.g. QeRL>",
     "relation": "<{'|'.join(IDEA_RELATIONS[:-1])}>"}}
  ]}}]

Rules:
- Use the arXiv id whenever the novelty text gives one, or when the named work
  matches a mined paper above. Work named without an id still gets an edge,
  with the title alone.
- Choose the relation from what the text actually says, not from what would
  sound strongest: "asserts X but never runs the control" is controls-for;
  "eliminates/aligns/corrects" that the idea builds past is extends; "we
  predict their explanation is wrong" is contradicts.
- Two to four edges per idea. Do not invent work the novelty text never names.
"""
    if on_line is not None:
        on_line(f"linking {len(todo)} idea(s) against {len(papers)} mined paper(s)")
    res = _run_headless(prompt, model=model, timeout=timeout, on_line=on_line)
    if not res.get("ok"):
        return res
    raw = _extract_json_array(str(res.get("text") or ""))
    if raw is None:
        return {"ok": False, "error": "model did not return a JSON array of links"}

    by_id = {str(i["id"]): i for i in ideas}
    linked = 0
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        idea = by_id.get(str(entry.get("id") or ""))
        if idea is None:
            continue
        edges = [e for e in (normalize_edge(x) for x in (entry.get("derived_from") or [])) if e]
        if edges:
            idea["derived_from"] = edges
            linked += 1
    if on_line is not None:
        on_line(f"linked {linked} idea(s)")
    return {"ok": True, "ideas": ideas, "linked": linked, "cost": res.get("cost", 0.0)}


# --- Reviewer ---------------------------------------------------------------

_SCORE_FIELDS = {
    "soundness": (1, 4),
    "presentation": (1, 4),
    "contribution": (1, 4),
    "rating": (1, 10),
    "confidence": (1, 5),
}

RECOMMENDATIONS = (
    "accept",
    "weak accept",
    "borderline",
    "weak reject",
    "reject",
)


def parse_review_scores(text: str) -> dict[str, Any]:
    """Pull the reviewer's score block out of the markdown review.

    Tolerates the bold and ``3/4`` variants models drift into; a field the
    reviewer omitted is simply absent rather than defaulted, so the UI can show
    the gap instead of inventing a score.
    """
    scores: dict[str, Any] = {}
    for field, (low, high) in _SCORE_FIELDS.items():
        m = re.search(
            rf"^\s*[*_]{{0,2}}{field}[*_]{{0,2}}\s*[:：]\s*[*_]{{0,2}}\s*(\d+(?:\.\d+)?)",
            text or "",
            re.IGNORECASE | re.MULTILINE,
        )
        if not m:
            continue
        try:
            value = float(m.group(1))
        except ValueError:
            continue
        if low <= value <= high:
            scores[field] = int(value) if value.is_integer() else value

    m = re.search(
        r"^\s*[*_]{0,2}recommendation[*_]{0,2}\s*[:：]\s*[*_]{0,2}\s*([A-Za-z ]+)",
        text or "",
        re.IGNORECASE | re.MULTILINE,
    )
    if m:
        raw = " ".join(m.group(1).split()).strip().lower().rstrip(".")
        for rec in RECOMMENDATIONS:
            if raw.startswith(rec):
                scores["recommendation"] = rec
                break
    return scores


def review_headline(scores: dict[str, Any]) -> str:
    """Short label for the round timeline."""
    if not scores:
        return "no scores parsed"
    bits = []
    if "rating" in scores:
        bits.append(f"rating {scores['rating']}/10")
    if "soundness" in scores:
        bits.append(f"soundness {scores['soundness']}/4")
    if "recommendation" in scores:
        bits.append(str(scores["recommendation"]))
    return " · ".join(bits) or "no scores parsed"


def run_reviewer(
    paper_dir: Path,
    skill_text: str,
    *,
    venue: str = DEFAULT_VENUE,
    idea: dict[str, Any] | None = None,
    round_n: int = 1,
    author_note: str = "",
    build: dict[str, Any] | None = None,
    model: str = "",
    timeout: int = 900,
    on_line: Any = None,
) -> dict[str, Any]:
    """Review the current state of the paper as a program committee member."""
    source = paper_source_text(paper_dir)
    if not source:
        return {"ok": False, "error": f"no LaTeX sources under {paper_dir}"}

    build = build or {}
    if build.get("ok"):
        build_line = (
            "The paper compiles."
            if build.get("clean")
            else "The paper compiles with LaTeX warnings/errors."
        )
    else:
        build_line = f"The paper does NOT compile: {build.get('error', 'unknown error')}"

    idea_block = idea_summary(idea) if idea else "(not recorded)"
    author_block = (author_note or "").strip() or "(the author left no note this round)"

    prompt = (
        f"{skill_text}\n\n"
        "=== end reviewer instructions ===\n\n"
        f"Venue: {venue_entry(venue).get('label')}\n"
        f"Review round: {round_n}\n"
        f"Build status: {build_line}\n\n"
        f"The idea this submission is meant to establish:\n{idea_block}\n\n"
        f"What the authors say they did this round:\n{author_block}\n\n"
        "LaTeX sources of the submission follow. Markers such as \\ARTODO{...}, "
        "\\ARnum{} and \\ARfig{...} are deliberate placeholders for work that has "
        "not been done yet - treat them as honest gaps, not as claims.\n\n"
        f"{source}\n\n"
        "Write your review now, in exactly the required markdown structure."
    )
    if on_line is not None:
        on_line(
            f"reviewing round {round_n} as {venue_entry(venue).get('label')} "
            f"({len(source)} chars of LaTeX)"
        )
    res = _run_headless(prompt, model=model, timeout=timeout, on_line=on_line)
    if not res.get("ok"):
        return res
    text = str(res.get("text") or "").strip()
    scores = parse_review_scores(text)
    if on_line is not None:
        on_line(review_headline(scores))
    return {
        "ok": True,
        "review": text,
        "scores": scores,
        "headline": review_headline(scores),
    }


# --- Round / gate state machine ---------------------------------------------


def current_round(state: dict[str, Any]) -> int:
    try:
        return int(state.get("round") or 0)
    except (TypeError, ValueError):
        return 0


def max_rounds(state: dict[str, Any]) -> int:
    return _clamp_rounds(state.get("max_rounds"))


def round_record(state: dict[str, Any], n: int) -> dict[str, Any] | None:
    for r in state.get("rounds") or []:
        if isinstance(r, dict) and int(r.get("n") or 0) == n:
            return r
    return None


def ensure_round(state: dict[str, Any], n: int) -> dict[str, Any]:
    rec = round_record(state, n)
    if rec is not None:
        return rec
    rec = {"n": n, "started_at": _now_iso(), "author": None, "review": None}
    rounds = state.setdefault("rounds", [])
    rounds.append(rec)
    rounds.sort(key=lambda r: int(r.get("n") or 0))
    return rec


def record_gate(
    state: dict[str, Any], kind: str, decision: str, note: str = ""
) -> dict[str, Any]:
    """Append a human decision and move the paper to the resulting stage.

    ``approve`` on the draft gate opens the loop; ``approve`` on the final gate
    delivers. A rejection sends the paper back to the work stage with the note
    carried into the next author prompt.
    """
    entry = {
        "kind": kind,
        "decision": decision,
        "note": (note or "").strip(),
        "at": _now_iso(),
    }
    state.setdefault("gates", []).append(entry)
    if kind == GATE_DRAFT:
        state["stage"] = STAGE_LOOP if decision == "approve" else STAGE_DRAFT
    elif kind == GATE_FINAL:
        if decision == "approve":
            state["stage"] = STAGE_DELIVERED
            state["loop_running"] = False
        else:
            # Rejected: reopen the loop for another batch of rounds on top of
            # whatever has already been done.
            state["stage"] = STAGE_LOOP
            state["max_rounds"] = _clamp_rounds(max_rounds(state) + DEFAULT_MAX_ROUNDS)
    return state


def last_gate(state: dict[str, Any], kind: str) -> dict[str, Any] | None:
    for entry in reversed(state.get("gates") or []):
        if isinstance(entry, dict) and entry.get("kind") == kind:
            return entry
    return None


def latest_review(state: dict[str, Any]) -> dict[str, Any] | None:
    for rec in reversed(state.get("rounds") or []):
        if isinstance(rec, dict) and isinstance(rec.get("review"), dict):
            return rec["review"]
    return None


def loop_is_complete(state: dict[str, Any]) -> bool:
    return current_round(state) >= max_rounds(state)


# --- Adapting the loop ------------------------------------------------------

# A rating this high means the reviewer would argue for the paper, so more
# rounds buy polish rather than acceptance. Stop and hand it back to the human.
DEFAULT_STOP_RATING = 8
# Consecutive reviews without improvement before we treat the loop as stuck.
PLATEAU_WINDOW = 3
# Rotated through when the score stops moving: a second opinion from the same
# model tends to repeat the same asks, and repeating them is what stalled.
REVIEWER_ROTATION = ("claude-fable-5", "claude-opus-4-8", "claude-sonnet-5")

SCORE_DIMENSIONS = ("soundness", "presentation", "contribution")


def score_history(state: dict[str, Any], field: str = "rating") -> list[float]:
    """Every recorded value of one score field, oldest first."""
    out: list[float] = []
    for rec in state.get("rounds") or []:
        scores = ((rec or {}).get("review") or {}).get("scores") or {}
        value = scores.get(field)
        if isinstance(value, (int, float)):
            out.append(float(value))
    return out


def best_rating(state: dict[str, Any]) -> float:
    ratings = score_history(state, "rating")
    return max(ratings) if ratings else 0.0


def stop_rating(state: dict[str, Any]) -> int:
    try:
        return int(state.get("stop_rating") or DEFAULT_STOP_RATING)
    except (TypeError, ValueError):
        return DEFAULT_STOP_RATING


def should_stop_early(state: dict[str, Any]) -> bool:
    """True once the reviewer rates the paper at or above the target."""
    return bool(score_history(state, "rating")) and best_rating(state) >= stop_rating(state)


def is_plateaued(state: dict[str, Any], window: int = PLATEAU_WINDOW) -> bool:
    """True when the rating has not improved across the last *window* reviews."""
    ratings = score_history(state, "rating")
    if len(ratings) < window:
        return False
    recent = ratings[-window:]
    return max(recent) <= max(ratings[:-window] or [0]) or len(set(recent)) == 1


def stuck_dimensions(state: dict[str, Any], window: int = PLATEAU_WINDOW) -> list[str]:
    """Score dimensions that have not moved across the last *window* reviews."""
    out: list[str] = []
    for field in SCORE_DIMENSIONS:
        values = score_history(state, field)
        if len(values) >= window and len(set(values[-window:])) == 1:
            out.append(field)
    return out


def reviewer_model_for(state: dict[str, Any], base: str, round_n: int) -> str:
    """Reviewer model for a round, rotated once the score stops moving."""
    if not is_plateaued(state):
        return base
    rotation = [m for m in REVIEWER_ROTATION if m != base] or list(REVIEWER_ROTATION)
    return rotation[round_n % len(rotation)]


def plateau_note(state: dict[str, Any], window: int = PLATEAU_WINDOW) -> str:
    """Instruction added to the author's prompt when the loop is stuck."""
    if not is_plateaued(state, window):
        return ""
    ratings = score_history(state, "rating")
    stuck = stuck_dimensions(state, window)
    stuck_text = (
        f" {', '.join(stuck)}ha{'s' if len(stuck) == 1 else 've'} not moved at all."
        if stuck
        else ""
    )
    return (
        f"The rating has not improved in {window} rounds "
        f"({', '.join(str(int(r)) for r in ratings[-window:])}).{stuck_text}\n"
        "Incremental responses to the review are not working, so do not spend "
        "this round on another one. Pick exactly one:\n"
        "  (a) Attack the stuck dimension directly - if contribution is stuck, "
        "the claim itself is too small or too well covered by prior work, so "
        "sharpen or change it.\n"
        "  (b) Run the experiment the reviewer keeps asking for, even a reduced "
        "version, and report it honestly.\n"
        "  (c) If neither is possible with the compute available, say so plainly "
        "in the paper's limitations and narrow the claim to what the evidence "
        "actually supports. A correct narrow paper beats a stuck broad one.\n"
        "State which you chose, and why, at the top of your round note."
    )


def progress_summary(state: dict[str, Any]) -> str:
    """One-line status for prompts and log lines."""
    stage = str(state.get("stage") or STAGE_DRAFT)
    label = STAGE_LABELS.get(stage, stage)
    if stage == STAGE_LOOP:
        return f"{label} ({current_round(state)}/{max_rounds(state)})"
    return label


# --- OpenReview submission prep ---------------------------------------------
#
# Loom prepares a submission; it never posts one. Everything below is
# read-only against OpenReview and produces artifacts you inspect and submit
# yourself with your own credentials, because signing your name to a paper is
# a decision a pipeline should not be able to make on your behalf.

SUBMISSION = "submission.json"
OPENREVIEW_API = "https://api2.openreview.net"
# The API2 submission schema caps these; checking locally saves a round trip
# to a rejection.
MAX_TITLE_CHARS = 250
MAX_ABSTRACT_CHARS = 5000

_MARKER_RE = re.compile(r"\\AR(TODO|num|fig)\b")


def submission_path(project_root: Path, slug: str) -> Path:
    return task_root(project_root, slug) / SUBMISSION


def submission_invitation(venue: str, year: int) -> str:
    template = str(venue_entry(venue).get("invitation") or "")
    return template.format(year=year) if template else ""


def fetch_invitation(invitation_id: str, timeout: int = 20) -> dict[str, Any]:
    """Look up a venue's submission invitation, read-only.

    OpenReview answers this endpoint without authentication, and its errors are
    the useful part: ``expired`` means the deadline has passed, ``missing``
    means the venue has not opened its CFP yet.
    """
    url = f"{OPENREVIEW_API}/invitations?{urllib.parse.urlencode({'id': invitation_id})}"
    req = urllib.request.Request(url, headers={"User-Agent": "loom-ar/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read().decode("utf-8", errors="replace"))
        except (ValueError, OSError):
            payload = {}
        name = str(payload.get("name") or "")
        message = str(payload.get("message") or f"HTTP {exc.code}")
        status = {
            "InvitationExpiredError": "expired",
            "NotFoundError": "missing",
            "ChallengeRequiredError": "blocked",
        }.get(name, "error")
        return {"ok": False, "status": status, "message": message}
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return {"ok": False, "status": "error", "message": str(exc)}

    invitations = data.get("invitations") or []
    if not invitations:
        return {"ok": False, "status": "missing", "message": "no such invitation"}
    note = ((invitations[0].get("edit") or {}).get("note") or {})
    content = note.get("content") or {}
    required = [
        key
        for key, spec in content.items()
        if isinstance(spec, dict)
        and not (((spec.get("value") or {}).get("param") or {}).get("optional"))
    ]
    return {
        "ok": True,
        "status": "open",
        "fields": sorted(content.keys()),
        "required": sorted(required),
        "duedate": invitations[0].get("duedate"),
    }


def resolve_invitation(venue: str, years: list[int] | None = None) -> dict[str, Any]:
    """Find the venue's most relevant submission invitation.

    Tries the coming years newest-first and returns the first open one, else
    the most informative failure, so the UI can say "not open yet" rather than
    just "error".
    """
    if years is None:
        this_year = datetime.now(timezone.utc).year
        years = [this_year + 1, this_year]
    best: dict[str, Any] = {"ok": False, "status": "error", "message": "no venue mapping"}
    for year in years:
        invitation_id = submission_invitation(venue, year)
        if not invitation_id:
            continue
        result = fetch_invitation(invitation_id)
        result["invitation"] = invitation_id
        result["year"] = year
        if result.get("status") == "open":
            return result
        # "expired" tells the user the window closed; prefer it over "missing".
        if best.get("status") in ("error", "missing"):
            best = result
    return best


def _delatex(text: str) -> str:
    """Roughly convert a LaTeX fragment to the plain text OpenReview wants."""
    out = re.sub(r"(?<!\\)%.*$", "", text or "", flags=re.MULTILINE)
    out = re.sub(r"\\(?:label|ref|cite[a-z]*|input|include)\s*\{[^}]*\}", "", out)
    # Drop placeholders *including* their argument: the prompt text inside an
    # \ARTODO is instructions to the author, not prose that belongs in an
    # abstract, and leaving it in would make an unwritten section look written.
    out = re.sub(r"\\ARfig\s*(?:\[[^\]]*\])?\s*\{[^{}]*\}", "", out)
    out = re.sub(r"\\ARTODO\s*\{[^{}]*\}", "", out)
    out = _MARKER_RE.sub("", out)
    # Unwrap one level of \command{...} formatting, twice for nesting.
    for _ in range(2):
        out = re.sub(r"\\[a-zA-Z]+\s*\{([^{}]*)\}", r"\1", out)
    out = re.sub(r"\\[a-zA-Z]+\b", "", out)
    out = out.replace("\\\\", " ").replace("~", " ")
    out = re.sub(r"[{}]", "", out)
    return " ".join(out.split())


def extract_paper_fields(paper_dir: Path) -> dict[str, Any]:
    """Title, abstract and keywords as OpenReview would want them."""
    main = paper_dir / "main.tex"
    source = ""
    try:
        source = main.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass

    title = ""
    for pattern in (r"\\icmltitle\{(.+?)\}\s*$", r"\\title\{(.+?)\}\s*$"):
        match = re.search(pattern, source, re.DOTALL | re.MULTILINE)
        if match:
            title = _delatex(match.group(1))
            break

    keywords: list[str] = []
    match = re.search(r"\\icmlkeywords\{(.+?)\}", source, re.DOTALL)
    if match:
        keywords = [k.strip() for k in _delatex(match.group(1)).split(",") if k.strip()]

    abstract_raw = ""
    abstract_file = paper_dir / "sections" / "00_abstract.tex"
    if abstract_file.is_file():
        try:
            abstract_raw = abstract_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            abstract_raw = ""

    return {
        "title": title,
        "abstract": _delatex(abstract_raw),
        "keywords": keywords,
        "abstract_markers": len(_MARKER_RE.findall(abstract_raw)),
    }


def count_placeholder_markers(paper_dir: Path) -> int:
    """Unfilled \\ARTODO / \\ARnum / \\ARfig slots left in the paper body."""
    total = 0
    sections = paper_dir / "sections"
    files = list(sections.glob("*.tex")) if sections.is_dir() else []
    for path in files:
        try:
            total += len(_MARKER_RE.findall(path.read_text(encoding="utf-8", errors="replace")))
        except OSError:
            continue
    return total


def pdf_page_count(pdf: Path) -> int | None:
    if not pdf.is_file():
        return None
    try:
        proc = subprocess.run(
            ["pdfinfo", str(pdf)], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"^Pages:\s+(\d+)", proc.stdout or "", re.MULTILINE)
    return int(match.group(1)) if match else None


def _has_real_results(paper_dir: Path) -> bool:
    """True once the experiments section carries an uncommented table or figure."""
    path = paper_dir / "sections" / "04_experiments.tex"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("%"):
            continue
        if r"\begin{table}" in stripped or r"\includegraphics" in stripped:
            return True
    return False


def _bib_entry_count(paper_dir: Path) -> int:
    try:
        text = (paper_dir / "main.bib").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0
    return len(re.findall(r"^@\w+\s*\{", text, re.MULTILINE))


# The three entries the template ships so the bibliography compiles from day one.
SEED_BIB_ENTRIES = 3


def build_submission(
    project_root: Path,
    slug: str,
    state: dict[str, Any],
    *,
    check_invitation: bool = True,
) -> dict[str, Any]:
    """Everything needed to submit this paper, plus what still blocks it.

    Produces the field values OpenReview asks for and a checklist of problems
    a program chair would desk-reject over, so the failures surface here rather
    than after the deadline.
    """
    paper_dir = paper_root(project_root, slug)
    venue = str(state.get("venue") or DEFAULT_VENUE)
    entry = venue_entry(venue)
    fields = extract_paper_fields(paper_dir)
    pdf = paper_dir / "main.pdf"
    pages = pdf_page_count(pdf)
    markers = count_placeholder_markers(paper_dir)
    checks: list[dict[str, Any]] = []

    def check(ok: bool, label: str, detail: str = "") -> None:
        checks.append({"ok": bool(ok), "label": label, "detail": detail})

    check(
        str(state.get("stage")) == STAGE_DELIVERED,
        "You approved the paper at the final gate",
        f"stage: {progress_summary(state)}",
    )
    check(pdf.is_file(), "PDF is compiled", str(pdf) if pdf.is_file() else "run Rebuild PDF")
    limit = int(entry.get("page_limit") or 0)
    if pages is not None and limit:
        check(
            pages <= limit + 2,
            f"Page count within the {entry['label']} limit",
            f"{pages} pages, main-text limit {limit} (references and appendix usually excluded)",
        )
    check(
        markers == 0,
        "No unfilled placeholders left",
        "none" if markers == 0 else f"{markers} \\ARTODO/\\ARnum/\\ARfig marker(s) remain",
    )
    check(
        bool(fields["title"]) and len(fields["title"]) <= MAX_TITLE_CHARS,
        "Title extracted and within length",
        fields["title"] or "no \\title{...} found in main.tex",
    )
    abstract = fields["abstract"]
    check(
        bool(abstract) and fields["abstract_markers"] == 0 and len(abstract) <= MAX_ABSTRACT_CHARS,
        "Abstract is written",
        f"{len(abstract)} chars"
        + (f", {fields['abstract_markers']} placeholder(s)" if fields["abstract_markers"] else ""),
    )
    check(_has_real_results(paper_dir), "Experiments section has a real table or figure")
    bib = _bib_entry_count(paper_dir)
    check(
        bib > SEED_BIB_ENTRIES,
        "Bibliography goes beyond the template seeds",
        f"{bib} entries",
    )

    invitation: dict[str, Any] = {"status": "unchecked"}
    if check_invitation:
        invitation = resolve_invitation(venue)
        status = invitation.get("status")
        check(
            status == "open",
            f"{entry['label']} submission window is open",
            {
                "open": f"{invitation.get('invitation', '')}",
                "expired": f"deadline passed for {invitation.get('invitation', '')}",
                "missing": f"{entry['label']} has not opened its next CFP yet",
                "blocked": "OpenReview is challenge-gating requests from this host",
            }.get(str(status), str(invitation.get("message") or "could not check")),
        )

    payload = {
        "venue": venue,
        "venue_label": entry["label"],
        "invitation": invitation,
        "fields": {
            "title": fields["title"],
            "abstract": abstract,
            "keywords": fields["keywords"],
            "authors": [],
            "authorids": [],
            "pdf": str(pdf) if pdf.is_file() else "",
        },
        "pages": pages,
        "checks": checks,
        "ready": all(c["ok"] for c in checks),
        "generated_at": _now_iso(),
    }
    payload["command"] = submission_command(payload)
    return payload


def submission_command(payload: dict[str, Any]) -> str:
    """The openreview-py call to run yourself, with this paper's values filled in."""
    fields = payload.get("fields") or {}
    invitation = (payload.get("invitation") or {}).get("invitation") or (
        f"<{payload.get('venue_label', 'VENUE')} submission invitation>"
    )
    return f"""# Loom prepares; you submit. Run this yourself, signed in as you.
#   pip install openreview-py
import json, openreview
from openreview.api import Note, OpenReviewClient

sub = json.load(open({json.dumps(SUBMISSION)}))          # this task's submission.json
client = OpenReviewClient(baseurl={json.dumps(OPENREVIEW_API)},
                          username="you@example.com", password="...")

# Fill these in - Loom cannot know them:
authors   = ["Your Name"]
authorids = ["~Your_Profile1"]

pdf_url = client.put_attachment({json.dumps(fields.get("pdf", "") or "main.pdf")}, {json.dumps(invitation)}, "pdf")
client.post_note_edit(
    invitation={json.dumps(invitation)},
    signatures=authorids[:1],
    note=Note(content={{
        "title":     {{"value": sub["fields"]["title"]}},
        "abstract":  {{"value": sub["fields"]["abstract"]}},
        "keywords":  {{"value": sub["fields"]["keywords"]}},
        "authors":   {{"value": authors}},
        "authorids": {{"value": authorids}},
        "pdf":       {{"value": pdf_url}},
    }}),
)"""


# --- Skills -----------------------------------------------------------------

SKILL_STUDIO = "AR-STUDIO.md"
SKILL_AUTHOR = "AR-AUTHOR.md"
SKILL_REVIEWER = "AR-REVIEWER.md"


def ar_skills_dir() -> Path:
    return bundled_skills_path().parent / "ar"


FIGURE_SKILLS_SUBDIR = "figures"


def figure_skills() -> list[dict[str, str]]:
    """Paper-figure skills available to the author, newest listing each time.

    Only the name, the one-line description and the path go into a prompt: the
    five SKILL.md files together are ~38k characters, so the author is pointed
    at them and reads the one it needs, rather than carrying all five into
    every round.
    """
    root = ar_skills_dir() / FIGURE_SKILLS_SUBDIR
    if not root.is_dir():
        return []
    out: list[dict[str, str]] = []
    for skill in sorted(root.iterdir()):
        doc = skill / "SKILL.md"
        if not doc.is_file():
            continue
        name, description = skill.name, ""
        try:
            head = doc.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            head = ""
        if head.startswith("---"):
            block = head.split("---", 2)[1] if head.count("---") >= 2 else ""
            for line in block.splitlines():
                key, _, value = line.partition(":")
                if key.strip() == "name" and value.strip():
                    name = value.strip()
                elif key.strip() == "description" and value.strip():
                    description = value.strip()
        # The first sentence carries what it makes; the rest is trigger phrasing.
        description = description.split(". ")[0].strip().rstrip(".")
        out.append({"name": name, "description": description, "path": str(doc)})
    return out


def figure_skills_block() -> str:
    """The figure-skill menu as it appears in an author prompt."""
    skills = figure_skills()
    if not skills:
        return ""
    lines = [
        "Figure skills are installed. Read the SKILL.md before drawing - each",
        "carries a house style, a drawing kit under its scripts/, and a worked",
        "example you can run:",
    ]
    for skill in skills:
        lines.append(f"  {skill['name']} - {skill['description']}")
        lines.append(f"      {skill['path']}")
    return "\n".join(lines)


def ar_skill_text(name: str, limit: int = 24000) -> str:
    path = ar_skills_dir() / name
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


# --- Agent prompts ----------------------------------------------------------


def studio_prompt(
    task_dir: Path, state: dict[str, Any], general_goal: str = ""
) -> str:
    """Prompt for a studio task's interactive pane."""
    venue = venue_entry(str(state.get("venue") or DEFAULT_VENUE)).get("label")
    mode = str(state.get("mode") or MODE_AUTO)
    seed = str(state.get("seed_idea") or "").strip()
    papers = [p for p in (state.get("papers") or []) if isinstance(p, dict)]
    mode_line = (
        f"Mode: seed idea. The user's starting idea:\n{seed}"
        if mode == MODE_SEED
        else "Mode: auto direction. Mine the direction and propose ideas from what you find."
    )
    return f"""You are the studio half of an AR (Automated Research) task in Loom.

Task directory:
{task_dir}

Research direction: {direction_label(state)}
Target venue: {venue}
{mode_line}

General goal:
{general_goal or "(none given)"}

Loom has already mined {len(papers)} recent arXiv paper(s) into the AR panel.
Your job is to survey the direction and produce idea cards. The user picks the
ones worth pursuing in the AR panel, and Loom turns each pick into its own
paper task with its own author and reviewer agents - so do not start writing a
paper here.

=== AR studio methodology - follow this exactly ===
{ar_skill_text(SKILL_STUDIO) or "(AR studio skill missing)"}
=== end methodology ===

You can either work here in the pane (survey, then paste your JSON idea array
into the panel) or let the user press "Generate ideas", which runs the same
methodology headlessly. Start by surveying what Loom mined and filling its gaps
with your own search.
"""


def author_draft_prompt(
    task_dir: Path, paper_dir: Path, state: dict[str, Any]
) -> str:
    """Stage-1 prompt: write the skeleton draft, leave results empty."""
    venue = venue_entry(str(state.get("venue") or DEFAULT_VENUE)).get("label")
    note = author_note_path_for(task_dir, 0)
    return f"""You are the author of an AR paper task in Loom. This is the FIRST DRAFT.

Task directory:
{task_dir}

Your pane starts in {task_dir / WORK_SUBDIR}, which holds two git repositories:
  code/        your experiments
  manuscript/  the paper, already seeded with the {venue} LaTeX skeleton
Full path to the manuscript: {paper_dir}

The idea this paper must establish:
{idea_summary(state.get("idea") or {})}

=== AR author methodology - follow this exactly ===
{ar_skill_text(SKILL_AUTHOR) or "(AR author skill missing)"}
=== end methodology ===

{figure_skills_block()}

This round you are writing the SKELETON, not results. Finish the title,
abstract arc, introduction with its contribution list, related work with real
citations, and a method section precise enough to reimplement from. Build out
the full experiments structure - setup, baselines, metrics, main results,
ablations, analysis - but leave every number as \\ARnum{{}}, every table
commented out and every figure an \\ARfig{{}} placeholder. Do not run
experiments yet.

When the draft compiles, write your summary to:
{note}

then stop. A human reviews the draft before the author/reviewer loop opens.
"""


def author_round_prompt(
    task_dir: Path,
    paper_dir: Path,
    state: dict[str, Any],
    round_n: int,
    review_text: str = "",
    gate_note: str = "",
) -> str:
    """Phase-1 prompt for one loop round, carrying the previous review."""
    venue = venue_entry(str(state.get("venue") or DEFAULT_VENUE)).get("label")
    note = author_note_path_for(task_dir, round_n)
    work = task_dir / WORK_SUBDIR
    total = max_rounds(state)
    if review_text.strip():
        feedback = (
            "The reviewer's report on the previous round follows. Work through "
            f"every point in it.\n\n{review_text.strip()}"
        )
    else:
        feedback = (
            "There is no reviewer report yet - this is the first round after the "
            "human approved the draft. Start from the experiments the idea needs "
            "and the weakest part of the current paper."
        )
    gate_block = (
        f"\n\nThe human left this instruction at the gate:\n{gate_note.strip()}\n"
        if gate_note.strip()
        else ""
    )
    stuck = plateau_note(state)
    stuck_block = f"\n=== THE LOOP IS STUCK - READ THIS FIRST ===\n{stuck}\n\n" if stuck else ""
    return f"""You are the author of an AR paper task in Loom. This is ROUND {round_n} of {total}.

Task directory:
{task_dir}

Your pane starts in {work}, which holds two git repositories:
  code/        your experiments
  manuscript/  the paper in {venue} format ({paper_dir})

The idea this paper must establish:
{idea_summary(state.get("idea") or {})}
{gate_block}
=== AR author methodology - follow this exactly ===
{ar_skill_text(SKILL_AUTHOR) or "(AR author skill missing)"}
=== end methodology ===

{figure_skills_block()}
{stuck_block}
{feedback}

Run the experiments first, then fold the real numbers into the paper, then
rebuild the PDF. Never write a number an experiment did not produce.

When the round is finished, write your summary to:
{note}

Writing that file is how Loom knows the round is over and hands the paper to
the reviewer, so make it the last thing you do, then stop.
"""


def author_note_path_for(task_dir: Path, n: int) -> Path:
    """``rounds/round-NN/author.md`` relative to an already-resolved task dir."""
    return task_dir / ROUNDS_SUBDIR / f"round-{n:02d}" / AUTHOR_NOTE
