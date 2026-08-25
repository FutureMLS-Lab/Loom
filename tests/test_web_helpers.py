"""Prompt-side helpers of the web layer."""

def test_default_prompt_lists_every_skill():
    """The skills map lives inside DEFAULT_PROMPT.md now - one always-on
    text that names the picker tier AND the AR pipeline tier, menu-style."""
    from loom.paths import default_prompt_path

    doc = default_prompt_path().read_text(encoding="utf-8")
    assert "remote_control" in doc                      # picker tier listed
    assert "AR-AUTHOR" in doc                           # AR tier listed
    assert "teaser-figure-3" in doc                     # figure menu listed
    assert "loom/skills/ar/AR-AUTHOR.md" in doc         # paths included
    # It is a menu: no skill body sneaks in wholesale.
    assert len(doc) < 20000


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
    """The generated section of DEFAULT_PROMPT.md matches a fresh render;
    fails when a skill was added without rerunning gen_skills_index.py."""
    import importlib.util
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "gen_skills_index", repo / "scripts" / "gen_skills_index.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    on_disk = (repo / "loom" / "skills" / "DEFAULT_PROMPT.md").read_text(encoding="utf-8")
    assert on_disk == mod.render_document(), (
        "DEFAULT_PROMPT.md skills section is stale - run: "
        "python3 scripts/gen_skills_index.py"
    )
