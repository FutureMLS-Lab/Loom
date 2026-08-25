"""Prompt-side helpers of the web layer."""

def test_skills_shelf_is_a_menu_not_a_paste(tmp_path):
    """The shelf generalises the AR figure menu: name + pitch + path, with
    already-injected skills marked and pipeline-internal ar/ skills absent."""
    from loom import web as w
    from loom.rud_task import bundled_skills_path

    shelf = w._skills_shelf_text(bundled_skills_path(), str(bundled_skills_path()))
    assert "[already injected above]" in shelf          # the selected skill is marked
    assert "remote_control.md" in shelf                 # real skills listed by path
    assert "AR-AUTHOR" not in shelf                     # ar/ stays pipeline-internal
    assert "DEFAULT_PROMPT" not in shelf                # always-on is never a choice
    # It is a menu: no skill body sneaks in (bodies are thousands of chars).
    assert all(len(line) < 200 for line in shelf.splitlines())


def test_skill_summary_prefers_frontmatter_description(tmp_path):
    from loom import web as w

    doc = tmp_path / "SKILL.md"
    doc.write_text(
        "---\nname: x\ndescription: Restarts the thing safely\n---\n# Title\nBody.",
        encoding="utf-8",
    )
    assert w._skill_summary(doc) == "Restarts the thing safely"
    plain = tmp_path / "plain.md"
    plain.write_text("# Heading\n\nFirst real line here.", encoding="utf-8")
    assert w._skill_summary(plain) == "Heading"


def test_skills_index_is_fresh():
    """SKILLS.md is generated; this fails when a skill was added or its
    description changed without rerunning scripts/gen_skills_index.py."""
    import importlib.util
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "gen_skills_index", repo / "scripts" / "gen_skills_index.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    on_disk = (repo / "loom" / "skills" / "SKILLS.md").read_text(encoding="utf-8")
    assert on_disk == mod.render(), (
        "loom/skills/SKILLS.md is stale - run: python3 scripts/gen_skills_index.py"
    )
