"""The agent must never be able to read held-out cases (evaluation protocol)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_no_agent_code_reads_the_heldout_folder():
    offenders = []
    for path in (ROOT / "socratic_tutor").rglob("*.py"):
        if path.name == "config.py":  # defines the path for the eval harness only
            continue
        text = path.read_text(encoding="utf-8")
        if "eval_heldout" in text or "EVAL_HELDOUT" in text:
            offenders.append(str(path.relative_to(ROOT)))
    assert not offenders, f"Agent code references held-out data: {offenders}"


def test_reflexion_and_prompts_do_not_touch_heldout():
    for path in list((ROOT / "prompts").glob("*.md")) + [ROOT / "socratic_tutor" / "reflexion.py", ROOT / "scripts" / "run_reflexion.py"]:
        assert "eval_heldout" not in path.read_text(encoding="utf-8"), path


def test_app_image_excludes_heldout():
    assert "eval_heldout/" in (ROOT / ".dockerignore").read_text().splitlines()


def test_only_the_eval_service_mounts_heldout():
    import yaml

    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text())
    mounting = [name for name, svc in compose["services"].items() if any("eval_heldout" in str(v) for v in svc.get("volumes", []))]
    assert mounting == ["eval"]
