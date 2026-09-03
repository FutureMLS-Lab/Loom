"""Private researcher-profile storage and extraction."""

from __future__ import annotations

import hashlib
import io
import json
import stat
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import pytest
from pypdf import PdfWriter

from loom import ar_task as ar
from loom import researcher_profile as profiles
from loom import routes_ar
from loom.rud_task import create_task

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolated_profiles_root(tmp_path, monkeypatch):
    root = tmp_path / "private-profiles"
    monkeypatch.setenv(profiles.PROFILES_ROOT_ENV, str(root))
    monkeypatch.delenv(profiles.EXTRACTION_MODEL_ENV, raising=False)
    yield root


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _pdf() -> bytes:
    stream = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(stream)
    return stream.getvalue()


def _wait_for_extraction(profile_id: str, timeout: float = 3.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        profile = profiles.read_profile(profile_id)
        if profile.get("extraction_status") != "running":
            return profile
        time.sleep(0.01)
    raise AssertionError("background extraction did not finish")


class _RouteHandler:
    def __init__(self, body: bytes = b"", content_type: str = "application/json"):
        self.rfile = io.BytesIO(body)
        self.headers = {
            "Content-Length": str(len(body)),
            "Content-Type": content_type,
        }
        self.response = None

    def _send(self, status, body, headers):
        self.response = (
            status,
            json.loads(body.decode("utf-8")),
            dict(headers),
        )


class _IdleArManager:
    @staticmethod
    def status(project_id, slug):
        return {"running": False}


def test_profile_http_route_contract_hides_storage_metadata():
    handler = _RouteHandler()
    parsed = urlparse("/api/ar/profiles")
    assert routes_ar.handle_post(
        handler,
        parsed.path,
        parsed,
        {"name": "Ada", "notes": "systems", "fit_mode": "strict"},
    )
    assert handler.response[0] == 201
    profile_id = handler.response[1]["profile"]["id"]

    source = b"# Scholar profile\n"
    upload = _RouteHandler(source, "text/markdown")
    parsed = urlparse(
        f"/api/ar/profiles/{profile_id}/sources?filename=scholar.md"
    )
    assert routes_ar.handle_raw_post(upload, parsed.path, parsed)
    assert upload.response[0] == 201
    assert "sha256" not in upload.response[1]["profile"]["source_files"][0]

    replacement = _RouteHandler(_pdf(), "application/pdf")
    parsed = urlparse(
        f"/api/ar/profiles/{profile_id}/sources"
        "?filename=google-scholar.pdf&replace=1"
    )
    assert routes_ar.handle_raw_post(replacement, parsed.path, parsed)
    assert replacement.response[0] == 201

    detail = _RouteHandler()
    parsed = urlparse(f"/api/ar/profiles/{profile_id}")
    assert routes_ar.handle_get(detail, parsed.path, parsed)
    payload = detail.response[1]["profile"]
    assert payload["notes"] == "systems"
    assert payload["source_files"][0]["name"] == "google-scholar.pdf"
    assert "sha256" not in payload["source_files"][0]
    assert "sources" not in payload

    listing = _RouteHandler()
    parsed = urlparse("/api/ar/profiles")
    assert routes_ar.handle_get(listing, parsed.path, parsed)
    summary = listing.response[1]["profiles"][0]
    assert summary["source_count"] == 1
    assert "notes" not in summary
    assert "source_files" not in summary

    assert routes_ar.handle_delete(
        detail,
        path=f"/api/ar/profiles/{profile_id}",
        parsed=urlparse(""),
    )
    assert detail.response[0] == 200


def test_generate_http_route_uses_two_field_contract(monkeypatch):
    captured = {}

    def fake_generate(research_profile, **kwargs):
        captured["research_profile"] = research_profile
        captured.update(kwargs)
        return {
            "id": "research-profile",
            "name": "Research profile",
            "status": "draft",
            "fit_mode": "balanced",
            "research_profile": research_profile,
            "notes": kwargs["notes"],
            "extraction_status": "running",
            "source_files": [],
        }

    monkeypatch.setattr(
        routes_ar.researcher_profiles, "generate_profile", fake_generate
    )
    handler = _RouteHandler()
    parsed = urlparse("/api/ar/profiles/generate")
    assert routes_ar.handle_post(
        handler,
        parsed.path,
        parsed,
        {
            "research_profile": "https://scholar.google.com/example",
            "notes": "Prefer efficient methods.",
        },
    )
    assert handler.response[0] == 202
    assert captured == {
        "research_profile": "https://scholar.google.com/example",
        "notes": "Prefer efficient methods.",
        "profile_id": "",
    }
    assert handler.response[1]["profile"]["extraction_status"] == "running"


def test_extract_route_can_request_automatic_activation(monkeypatch):
    captured = {}

    def fake_start(profile_id, **kwargs):
        captured["profile_id"] = profile_id
        captured.update(kwargs)
        return {
            "id": profile_id,
            "name": "Scholar export",
            "status": "draft",
            "fit_mode": "balanced",
            "extraction_status": "running",
            "source_files": [],
        }

    monkeypatch.setattr(
        routes_ar.researcher_profiles, "start_extraction", fake_start
    )
    handler = _RouteHandler()
    parsed = urlparse("/api/ar/profiles/scholar-export/extract")
    assert routes_ar.handle_post(
        handler,
        parsed.path,
        parsed,
        {"activate_on_success": True},
    )
    assert handler.response[0] == 202
    assert captured == {
        "profile_id": "scholar-export",
        "model": "",
        "activate_on_success": True,
    }


def test_factory_profile_creation_exposes_only_two_content_inputs():
    html = (REPO / "loom" / "web_static" / "factory.html").read_text(
        encoding="utf-8"
    )
    javascript = (REPO / "loom" / "web_static" / "factory.js").read_text(
        encoding="utf-8"
    )

    assert html.count('id="profile-pdf"') == 1
    assert html.count('id="profile-notes"') == 1
    assert 'accept=".pdf,application/pdf"' in html
    for removed_id in (
        "profile-research-profile",
        "profile-name",
        "profile-fit-mode",
        "profile-summary",
        "profile-interests",
        "profile-avoid",
        "profile-resources",
        "profile-files",
        "btn-profile-save",
        "btn-profile-upload",
        "btn-profile-extract",
        "btn-profile-activate",
    ):
        assert f'id="{removed_id}"' not in html
    assert 'id="btn-profile-generate"' in html
    assert "replace=1" in javascript
    assert "activate_on_success: true" in javascript


def test_studio_background_action_snapshots_and_clears_profile(tmp_path):
    profile = profiles.create_profile(
        "Ada", profile_id="ada", notes="Efficient inference on one GPU."
    )
    assert profile["status"] == "draft"
    profiles.extract_profile(
        "ada",
        runner=lambda *args, **kwargs: {
            "summary": "Studies efficient inference.",
            "methods": ["quantization"],
            "resources": ["one GPU"],
        },
    )
    profiles.activate_profile("ada")

    meta = create_task(
        tmp_path,
        "Studio",
        "goal",
        kind=ar.KIND_AR,
        auto_worktree=False,
    )
    ar.write_ar_state(tmp_path, meta.slug, ar.new_studio_state())
    handler = _RouteHandler()
    handler.ar_manager = _IdleArManager()

    payload, status = routes_ar._ar_action(
        handler,
        tmp_path,
        "project",
        meta.slug,
        "background",
        {"profile_id": "ada", "fit_mode": "strict"},
    )
    assert status == 200
    state = payload["state"]
    assert state["background_profile_id"] == "ada"
    assert state["background_fit_mode"] == "strict"
    assert state["background_profile_snapshot"]["summary"] == (
        "Studies efficient inference."
    )
    assert "source_files" not in state["background_profile_snapshot"]

    payload, status = routes_ar._ar_action(
        handler,
        tmp_path,
        "project",
        meta.slug,
        "background",
        {"profile_id": "", "fit_mode": "balanced"},
    )
    assert status == 200
    assert payload["state"]["background_profile_id"] == ""
    assert payload["state"]["background_profile_snapshot"] == {}


def test_path_override_crud_permissions_and_additive_schema(isolated_profiles_root):
    assert profiles.profiles_root() == isolated_profiles_root
    assert _mode(isolated_profiles_root) == 0o700
    assert profiles.list_profiles() == []

    created = profiles.create_profile(
        {
            "id": "ada",
            "name": " Ada Lovelace ",
            "fit_mode": "strict",
            "notes": "Prefer small experiments",
            "topics": "model efficiency",
            "future_field": {"kept": True},
        }
    )
    profile_dir = isolated_profiles_root / "ada"
    assert created["id"] == "ada"
    assert created["name"] == "Ada Lovelace"
    assert created["status"] == "draft"
    assert created["topics"] == ["model efficiency"]
    assert created["future_field"] == {"kept": True}
    assert _mode(profile_dir) == 0o700
    assert _mode(profile_dir / "sources") == 0o700
    assert _mode(profile_dir / "profile.json") == 0o600

    updated = profiles.update_profile(
        "ada",
        {
            "methods": [" Quantization ", "quantization", "distillation"],
            "fit_mode": "not-a-mode",
            "affiliation": "Analytical Engine Lab",
        },
        notes="User-authored note",
    )
    assert updated["methods"] == ["Quantization", "distillation"]
    assert updated["fit_mode"] == "balanced"
    assert updated["notes"] == "User-authored note"
    assert updated["affiliation"] == "Analytical Engine Lab"
    assert [item["id"] for item in profiles.list_profiles()] == ["ada"]

    assert profiles.read_profile("missing") == {}
    assert profiles.delete_profile("ada") is True
    assert profiles.delete_profile("ada") is False


@pytest.mark.parametrize(
    "bad_id",
    ["", ".", "..", "../ada", "ada/other", "Ada", "a.b", "a" * 65],
)
def test_profile_ids_reject_traversal_and_unsafe_forms(bad_id):
    with pytest.raises(ValueError):
        profiles.read_profile(bad_id)


@pytest.mark.parametrize(
    ("filename", "body"),
    [
        ("cv.pdf", b"not a pdf"),
        ("plot.png", b"not a png"),
        ("photo.jpg", b"not a jpeg"),
        ("photo.jpeg", b"GIF89a"),
        ("figure.webp", b"RIFF\x00\x00\x00\x00NOPE"),
        ("notes.txt", b"\xff\xfe"),
        ("notes.md", b"okay\x00not-text"),
        ("empty.txt", b""),
        ("payload.exe", b"MZ"),
    ],
)
def test_source_type_magic_and_utf8_are_verified(filename, body):
    profiles.create_profile("Ada", profile_id="ada")
    with pytest.raises(ValueError):
        profiles.save_source("ada", filename, body)


@pytest.mark.parametrize(
    ("filename", "body"),
    [
        ("paper.pdf", b"%PDF-1.7\n"),
        ("plot.png", b"\x89PNG\r\n\x1a\nrest"),
        ("photo.jpg", b"\xff\xd8\xff\xe0rest"),
        ("photo.jpeg", b"\xff\xd8\xff\xe1rest"),
        ("figure.webp", b"RIFF\x04\x00\x00\x00WEBPrest"),
        ("notes.txt", "研究方向".encode()),
        ("notes.md", b"# Research\n"),
    ],
)
def test_allowed_source_types_accept_matching_content(filename, body):
    profiles.create_profile("Ada", profile_id="ada")
    saved = profiles.save_source("ada", filename, body)
    metadata = saved["source_files"][0]
    assert metadata["filename"] == filename
    assert metadata["sha256"] == hashlib.sha256(body).hexdigest()


@pytest.mark.parametrize(
    "filename",
    ["../cv.pdf", "nested/cv.pdf", r"..\cv.pdf", "/tmp/cv.pdf", " cv.pdf", "."],
)
def test_source_filenames_reject_traversal(filename):
    profiles.create_profile("Ada", profile_id="ada")
    with pytest.raises(ValueError):
        profiles.save_source("ada", filename, b"%PDF-1.7\n")


def test_declared_content_type_must_match_extension_and_magic():
    profiles.create_profile("Ada", profile_id="ada")
    with pytest.raises(ValueError, match="declared content type"):
        profiles.save_source(
            "ada", "paper.pdf", b"%PDF-1.7\n", content_type="image/png"
        )
    saved = profiles.save_source(
        "ada",
        "notes.md",
        b"# Notes\n",
        content_type="text/markdown; charset=utf-8",
    )
    assert saved["source_files"][0]["media_type"] == "text/markdown"


def test_source_permissions_hash_and_size_limits(
    isolated_profiles_root, monkeypatch
):
    profiles.create_profile("Ada", profile_id="ada")
    body = b"private notes"
    saved = profiles.save_source("ada", "notes.txt", body)
    metadata = saved["source_files"][0]
    source = isolated_profiles_root / "ada" / "sources" / "notes.txt"
    assert source.read_bytes() == body
    assert _mode(source) == 0o600
    assert metadata["sha256"] == hashlib.sha256(body).hexdigest()
    assert profiles.read_profile("ada")["source_files"] == [metadata]

    monkeypatch.setattr(profiles, "MAX_SOURCE_BYTES", 8)
    with pytest.raises(ValueError, match="exceeds"):
        profiles.save_source("ada", "large.md", b"123456789")

    monkeypatch.setattr(profiles, "MAX_SOURCE_BYTES", 100)
    monkeypatch.setattr(profiles, "MAX_PROFILE_SOURCE_BYTES", len(body) + 5)
    with pytest.raises(ValueError, match="profile sources exceed"):
        profiles.save_source("ada", "second.md", b"123456")
    # Replacing a file subtracts the old copy from the aggregate.
    replacement = profiles.save_source("ada", "notes.txt", b"tiny")
    assert replacement["source_files"][0]["size"] == 4


def test_replace_all_sources_keeps_only_new_pdf(isolated_profiles_root):
    profiles.create_profile("Ada", profile_id="ada")
    profiles.save_source("ada", "old.md", b"# Old profile")
    profiles.save_source("ada", "old.pdf", _pdf())

    replaced = profiles.save_source(
        "ada",
        "google-scholar.pdf",
        _pdf(),
        content_type="application/pdf",
        replace_all=True,
    )
    assert [item["filename"] for item in replaced["source_files"]] == [
        "google-scholar.pdf"
    ]
    source_names = sorted(
        path.name
        for path in (isolated_profiles_root / "ada" / "sources").iterdir()
    )
    assert source_names == ["google-scholar.pdf"]


def test_uploaded_pdf_extraction_can_activate_automatically():
    profiles.create_profile(
        "Google Scholar export",
        profile_id="scholar-export",
        notes="Prefer one-GPU projects.",
    )
    profiles.save_source(
        "scholar-export",
        "google-scholar.pdf",
        _pdf(),
        content_type="application/pdf",
        replace_all=True,
    )
    extracted = profiles.extract_profile(
        "scholar-export",
        runner=lambda *args, **kwargs: {
            "name": "Ada Researcher",
            "summary": "Studies efficient inference.",
            "methods": ["quantization"],
        },
        activate_on_success=True,
    )
    assert extracted["status"] == "active"
    assert extracted["extraction_status"] == "succeeded"
    assert extracted["name"] == "Ada Researcher"


def test_automatic_activation_rejects_unstructured_failure_summary():
    profiles.create_profile("Google Scholar export", profile_id="scholar-export")
    profiles.save_source(
        "scholar-export",
        "google-scholar.pdf",
        _pdf(),
        content_type="application/pdf",
    )
    extracted = profiles.extract_profile(
        "scholar-export",
        runner=lambda *args, **kwargs: {
            "summary": "No research background could be established.",
        },
        activate_on_success=True,
    )
    assert extracted["status"] == "draft"
    assert extracted["extraction_status"] == "failed"
    assert "structured research evidence" in extracted["extraction_error"]


def test_activation_snapshot_and_fit_mode_prompts():
    profiles.create_profile("Ada", profile_id="ada", notes="One GPU")
    with pytest.raises(ValueError, match="extraction must succeed"):
        profiles.activate_profile("ada")
    with pytest.raises(ValueError, match="active"):
        profiles.profile_snapshot("ada")

    profiles.update_profile(
        "ada",
        summary="Works on efficient language models.",
        strengths=["quantization"],
        resources=["one GPU"],
        interests=["KV cache"],
        avoid=["large pretraining runs"],
    )
    with pytest.raises(ValueError, match="extraction must succeed"):
        profiles.activate_profile("ada")
    profiles.save_source("ada", "bio.md", b"# Research background")
    extracted = profiles.extract_profile(
        "ada",
        runner=lambda *args, **kwargs: {
            "summary": "Works on efficient language models.",
            "strengths": ["quantization"],
            "resources": ["one GPU"],
            "interests": ["KV cache"],
            "avoid": ["large pretraining runs"],
        },
    )
    assert extracted["extraction_status"] == "succeeded"
    active = profiles.activate_profile("ada")
    assert active["status"] == "active"

    for mode in ("strict", "balanced", "exploratory"):
        snapshot = profiles.profile_snapshot("ada", fit_mode=mode)
        assert snapshot["fit_mode"] == mode
        assert "sources" not in snapshot
        assert "extraction_error" not in snapshot
        block = profiles.background_prompt_block(snapshot)
        assert mode.upper() in block
        assert "UNTRUSTED DATA" in block
        assert "one GPU" in block


def test_legacy_and_no_profile_helpers(isolated_profiles_root):
    profiles.profiles_root()
    legacy_dir = isolated_profiles_root / "legacy"
    legacy_dir.mkdir(mode=0o755)
    path = legacy_dir / "profile.json"
    path.write_text(
        json.dumps(
            {
                "id": "legacy",
                "name": "Legacy Researcher",
                "summary": "Old schema summary",
                "topics": "systems",
            }
        ),
        encoding="utf-8",
    )
    path.chmod(0o644)

    legacy = profiles.read_profile("legacy")
    assert legacy["schema_version"] == profiles.SCHEMA_VERSION
    assert legacy["status"] == "draft"
    assert legacy["topics"] == ["systems"]
    assert _mode(legacy_dir) == 0o700
    assert _mode(path) == 0o600
    assert profiles.profile_snapshot(None) == {}
    assert profiles.profile_snapshot("not-created") == {}
    assert profiles.background_prompt_block({}) == ""
    # Status-less snapshots from pre-profile tasks remain usable.
    block = profiles.background_prompt_block(
        {"name": "Legacy", "summary": "systems", "fit_mode": "strict"}
    )
    assert "STRICT" in block


def test_successful_mocked_extraction_is_isolated_and_stays_draft(
    isolated_profiles_root, monkeypatch
):
    monkeypatch.setenv(profiles.EXTRACTION_MODEL_ENV, "test-model")
    profiles.create_profile(
        "Placeholder",
        profile_id="ada",
        fit_mode="exploratory",
        notes="This user note must survive.",
        private_extension={"preserve": True},
    )
    profiles.save_source("ada", "bio.md", b"# Ada\nWorks on quantization.\n")
    profiles.save_source("ada", "slides.pdf", _pdf())
    before_sources = profiles.read_profile("ada")["source_files"]
    seen: dict[str, object] = {}

    def fake_runner(prompt, model, workspace, *, timeout):
        seen.update(
            {
                "prompt": prompt,
                "model": model,
                "workspace": workspace,
                "timeout": timeout,
            }
        )
        assert workspace != isolated_profiles_root / "ada"
        assert (workspace / "sources" / "bio.md").read_text().startswith("# Ada")
        assert (workspace / "sources" / "slides.pdf").read_bytes().startswith(b"%PDF")
        manifest = json.loads((workspace / "source-manifest.json").read_text())
        assert {item["filename"] for item in manifest["sources"]} == {
            "bio.md",
            "slides.pdf",
        }
        assert "UNTRUSTED DATA" in prompt
        assert "ORIGINAL files" in prompt
        return json.dumps(
            {
                "name": "Ada Researcher",
                "summary": "Builds efficient language-model inference methods.",
                "topics": [" model efficiency ", "model efficiency"],
                "methods": ["quantization"],
                "domains": ["NLP"],
                "datasets": [],
                "tools": ["PyTorch"],
                "strengths": ["systems measurement"],
                "resources": ["one GPU"],
                "interests": ["KV caches"],
                "avoid": ["large training runs"],
                "evidence": [
                    {
                        "claim": "Quantization experience",
                        "source": "bio.md",
                        "detail": "Explicitly stated",
                    }
                ],
                "notes": "model must not overwrite this",
                "status": "active",
                "sources": [],
            }
        )

    extracted = profiles.extract_profile("ada", timeout=17, runner=fake_runner)
    assert extracted["extraction_status"] == "succeeded"
    assert extracted["status"] == "draft"
    assert extracted["activated_at"] == ""
    assert extracted["name"] == "Ada Researcher"
    assert extracted["notes"] == "This user note must survive."
    assert extracted["source_files"] == before_sources
    assert extracted["sources"] == before_sources
    assert extracted["topics"] == ["model efficiency"]
    assert extracted["private_extension"] == {"preserve": True}
    assert seen["model"] == "test-model"
    assert seen["timeout"] == 17
    assert not Path(seen["workspace"]).exists()

    activated = profiles.activate_profile("ada")
    assert activated["status"] == "active"


def test_text_description_can_be_extracted_without_uploaded_files():
    profiles.create_profile(
        "Ada",
        profile_id="ada",
        notes="I study efficient inference and can use one GPU.",
    )

    def fake_runner(prompt, model, workspace, *, timeout):
        assert not list((workspace / "sources").iterdir())
        assert (workspace / "extra-note.txt").read_text() == (
            "I study efficient inference and can use one GPU."
        )
        manifest = json.loads((workspace / "source-manifest.json").read_text())
        assert manifest["sources"] == []
        assert manifest["profile_inputs"] == {"notes": "extra-note.txt"}
        return {
            "summary": "Studies efficient inference.",
            "resources": ["one GPU"],
        }

    extracted = profiles.extract_profile("ada", runner=fake_runner)
    assert extracted["extraction_status"] == "succeeded"
    assert extracted["summary"] == "Studies efficient inference."
    assert extracted["notes"].startswith("I study efficient inference")


def test_two_field_generation_extracts_and_activates_automatically(monkeypatch):
    # Keep the test hermetic: the profile names a live URL, so stub the
    # server-side fetch instead of hitting the network.
    monkeypatch.setattr(
        profiles, "_fetch_public_url", lambda url: _SCHOLAR_FIXTURE
    )
    seen = {}

    def fake_runner(prompt, model, workspace, *, timeout):
        assert "fetched_profile_pages" in prompt
        seen["research_profile"] = (
            workspace / "research-profile.txt"
        ).read_text()
        seen["notes"] = (workspace / "extra-note.txt").read_text()
        manifest = json.loads((workspace / "source-manifest.json").read_text())
        assert manifest["profile_inputs"] == {
            "research_profile": "research-profile.txt",
            "notes": "extra-note.txt",
        }
        return {
            "name": "Ada Researcher",
            "summary": "Studies efficient machine learning.",
            "methods": ["quantization"],
            "resources": ["one GPU"],
        }

    started = profiles.generate_profile(
        "https://scholar.google.com/citations?user=public-example",
        notes="Focus on projects that fit one GPU.",
        runner=fake_runner,
    )
    assert started["extraction_status"] == "running"
    finished = _wait_for_extraction(started["id"])
    assert finished["status"] == "active"
    assert finished["extraction_status"] == "succeeded"
    assert finished["name"] == "Ada Researcher"
    assert seen == {
        "research_profile": (
            "https://scholar.google.com/citations?user=public-example"
        ),
        "notes": "Focus on projects that fit one GPU.",
    }


@pytest.mark.parametrize(
    "research_profile",
    [
        "http://127.0.0.1/profile",
        "http://localhost/profile",
        "https://user:password@example.com/profile",
        "https://example.com:8443/profile",
    ],
)
def test_two_field_generation_rejects_non_public_profile_urls(
    research_profile,
):
    with pytest.raises(ValueError, match="public|standard"):
        profiles.generate_profile(research_profile)


def test_extraction_failure_is_persisted_without_losing_private_fields():
    profiles.create_profile(
        "Ada", profile_id="ada", notes="keep", summary="keep prior summary"
    )
    saved = profiles.save_source("ada", "bio.txt", b"research profile")
    source = saved["source_files"][0]

    def failing_runner(prompt, model, workspace, *, timeout):
        raise RuntimeError("synthetic extraction failure")

    failed = profiles.extract_profile("ada", runner=failing_runner)
    assert failed["status"] == "draft"
    assert failed["extraction_status"] == "failed"
    assert "synthetic extraction failure" in failed["extraction_error"]
    assert failed["extraction_completed_at"]
    assert failed["notes"] == "keep"
    assert failed["summary"] == "keep prior summary"
    assert failed["source_files"] == [source]


def test_background_extraction_is_daemonized_and_rejects_duplicates():
    profiles.create_profile("Ada", profile_id="ada")
    profiles.save_source("ada", "bio.md", b"# Background")
    entered = threading.Event()
    release = threading.Event()

    def blocking_runner(prompt, model, workspace, *, timeout):
        entered.set()
        assert release.wait(2)
        return {
            "summary": "Research systems background",
            "topics": ["systems"],
        }

    try:
        started = profiles.start_extraction("ada", runner=blocking_runner)
        assert started["extraction_status"] == "running"
        assert entered.wait(2)
        assert profiles._EXTRACTION_JOBS["ada"].daemon is True
        with pytest.raises(ValueError, match="already running"):
            profiles.start_extraction("ada", runner=blocking_runner)
        with pytest.raises(ValueError, match="while extraction is running"):
            profiles.update_profile("ada", notes="changed")
        with pytest.raises(ValueError, match="while extraction is running"):
            profiles.save_source("ada", "new.md", b"# changed")
    finally:
        release.set()
    finished = _wait_for_extraction("ada")
    assert finished["extraction_status"] == "succeeded"


def test_orphaned_running_extraction_becomes_retryable():
    created = profiles.create_profile(
        "Ada", profile_id="ada", notes="Research systems."
    )
    created["extraction_status"] = "running"
    created["extraction"] = {"status": "running"}
    profiles._write_profile_unlocked(created)

    recovered = profiles.read_profile("ada")
    assert recovered["extraction_status"] == "failed"
    assert "interrupted" in recovered["extraction_error"]


def test_cursor_runner_uses_read_only_print_mode_without_leaking_stderr(
    tmp_path, monkeypatch
):
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps({"result": '{"summary":"ok"}'}),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = profiles._run_cursor_agent(
        "JSON only", "gpt-test", tmp_path, timeout=23
    )
    command = captured["command"]
    assert command[:2] == ["agent", "--print"]
    assert command[command.index("--workspace") + 1] == str(tmp_path)
    assert command[command.index("--mode") + 1] == "ask"
    assert "--trust" in command and "--force" not in command
    assert command[command.index("--model") + 1] == "gpt-test"
    assert captured["kwargs"]["stdin"] is subprocess.DEVNULL
    assert result == '{"summary":"ok"}'

    def failed_run(command, **kwargs):
        return subprocess.CompletedProcess(
            command, 2, stdout="", stderr="TOP-SECRET profile body"
        )

    monkeypatch.setattr(subprocess, "run", failed_run)
    with pytest.raises(RuntimeError) as error:
        profiles._run_cursor_agent("JSON only", "gpt-test", tmp_path)
    assert "TOP-SECRET" not in str(error.value)


# --- Direct profile-URL import (server-side fetch → source → extraction) -----

_SCHOLAR_FIXTURE = (
    "<html><head><title>‪Ada Lovelace‬ - ‪Google Scholar‬"
    "</title></head><body>"
    '<a class="gsc_prf_inta gs_ibl">Machine learning</a>'
    '<a class="gsc_prf_inta gs_ibl">Analytical engines</a>'
    '<td class="gsc_rsb_std">4096</td><td class="gsc_rsb_std">2048</td>'
    '<td class="gsc_rsb_std">21</td><td class="gsc_rsb_std">15</td>'
    '<td class="gsc_rsb_std">18</td><td class="gsc_rsb_std">12</td>'
    '<a href="x" class="gsc_a_at">Notes on the Analytical Engine</a>'
    '<div class="gs_gray">A Lovelace, C Babbage</div>'
    '<div class="gs_gray">Memoirs</div>'
    '<span class="gsc_a_h gsc_a_hc gs_ibl">1843</span>'
    "</body></html>"
)


def test_scholar_html_parses_name_interests_and_papers():
    text = profiles._scholar_html_to_text(_SCHOLAR_FIXTURE)
    assert "Researcher: Ada Lovelace" in text  # bidi format marks stripped
    assert "Machine learning" in text and "Analytical engines" in text
    assert "Total citations: 4096" in text
    assert "h-index 21" in text and "i10-index 18" in text
    assert "Notes on the Analytical Engine (1843)" in text
    assert "A Lovelace, C Babbage" in text


@pytest.mark.parametrize(
    "host,public",
    [
        ("8.8.8.8", True),  # public IP literal - no DNS needed
        ("localhost", False),
        ("127.0.0.1", False),
        ("10.0.0.1", False),
        ("169.254.169.254", False),  # cloud metadata endpoint
        ("service.internal", False),
    ],
)
def test_host_public_guard(host, public):
    assert profiles._host_is_public(host) is public


def test_html_to_text_strips_markup_and_scripts():
    page = (
        "<html><head><style>.x{color:red}</style>"
        "<script>steal()</script></head><body>"
        "<h1>Jane Q. Researcher</h1><p>Works on &amp; studies systems.</p>"
        "</body></html>"
    )
    text = profiles._html_to_text(page)
    assert "Jane Q. Researcher" in text
    assert "Works on & studies systems." in text
    assert "steal()" not in text and "color:red" not in text


def test_url_only_profile_fetches_page_then_extracts(monkeypatch):
    # The extraction agent cannot browse, so Loom fetches the page itself and
    # feeds it as workspace evidence. Mock the fetch; assert the page reaches
    # the agent and yields an active profile - no PDF involved.
    monkeypatch.setattr(profiles, "_fetch_public_url", lambda url: _SCHOLAR_FIXTURE)
    profiles.create_profile(
        "Research profile",
        profile_id="url-profile",
        research_profile="https://scholar.google.com/citations?user=TEST",
    )
    seen: dict[str, object] = {}

    def runner(prompt, model, workspace, timeout=0):
        fetched = sorted((Path(workspace) / "extracted-text").glob("fetched-url-*.txt"))
        seen["files"] = [p.name for p in fetched]
        seen["text"] = "\n".join(p.read_text(encoding="utf-8") for p in fetched)
        return {
            "name": "Ada Lovelace",
            "summary": "Foundational work on analytical engines.",
            "methods": ["mechanical computation"],
        }

    extracted = profiles.extract_profile(
        "url-profile", runner=runner, activate_on_success=True
    )
    assert seen["files"], "no profile page was fetched into the workspace"
    assert "Notes on the Analytical Engine" in seen["text"]
    assert "Source URL: https://scholar.google.com" in seen["text"]
    assert extracted["status"] == "active"
    assert extracted["extraction_status"] == "succeeded"
    assert extracted["name"] == "Ada Lovelace"
