"""tasks / memory / skills / ask_user tools and the workspace root guard."""
from __future__ import annotations

import json

import pytest

from tpagent.tools import ask_user as AU
from tpagent.tools import files, load_tools, memory, skills, tasks
from tpagent.tools.workspace import get_workspace, set_workspace


@pytest.fixture(autouse=True)
def _fresh(workdir):
    tasks.reset()
    set_workspace(None)
    yield
    tasks.reset()
    set_workspace(None)


def test_core_modules_registered():
    names = {t.name for t in load_tools()}
    assert {"task_create", "task_update", "task_list", "memory_read", "memory_write", "memory_append",
            "use_skill", "ask_user"} <= names


# --- tasks -------------------------------------------------------------------
def test_tasks_lifecycle_and_mirror(workdir):
    assert tasks.task_list() == "(no tasks)"
    out = tasks.task_create("Write tests", "pytest for tasks")
    assert out.startswith("Created task #1") and "[ ] #1 Write tests - pytest for tasks" in out
    tasks.task_create("Ship")
    assert "#2 -> in_progress" in tasks.task_update(2, "in_progress")
    assert "[~] #2 Ship" in tasks.task_list() and "(0/2 completed)" in tasks.task_list()
    tasks.task_update(1, "completed")
    tasks.task_update(2, "deleted")
    listing = tasks.task_list()
    assert "[x] #1" in listing and "#2" not in listing and "(1/1 completed)" in listing
    assert "status must be" in tasks.task_update(1, "bogus") and "no task #9" in tasks.task_update(9, "pending")
    mirror = json.loads((workdir / ".tpagent" / "tasks.json").read_text())
    assert [t["status"] for t in mirror] == ["completed", "deleted"]
    tasks.reset()  # a new process reloads from the mirror
    assert "[x] #1 Write tests" in tasks.task_list()
    assert tasks.task_create("Next").startswith("Created task #3")


# --- memory ------------------------------------------------------------------
def test_memory_write_append_read_and_limit(workdir):
    assert memory.memory_read() == "(memory is empty)" and memory.load_memory() == ""
    assert memory.memory_append("user prefers Vietnamese").startswith("Appended")
    assert memory.memory_append("- run tests with pytest").startswith("Appended")
    assert memory.memory_read() == "- user prefers Vietnamese\n- run tests with pytest\n"
    assert memory.memory_write("# Project\n- uses uv").startswith("Memory saved")
    assert (workdir / ".tpagent" / "MEMORY.md").read_text() == "# Project\n- uses uv\n"
    assert "limit is" in memory.memory_write("x" * (memory.MAX_CHARS + 1))
    memory.memory_write("y" * (memory.MAX_CHARS - 5))
    assert "memory full" in memory.memory_append("one more line that does not fit")
    assert "empty line" in memory.memory_append("   ")


# --- skills ------------------------------------------------------------------
def _write_skill(root, name: str, description: str, body: str = "do it") -> None:
    d = root / "skills" / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {description}\n---\n{body}\n", encoding="utf-8")


def test_skills_loader_precedence_and_use_skill(workdir):
    _write_skill(workdir, "deploy", "Deploy the app", "# Deploy\n1. build\n2. push")
    _write_skill(workdir / ".tpagent", "code-task", "local override of the bundled skill", "mine")
    names = {s.name: s for s in skills.load_skills()}
    assert "deploy" in names and names["deploy"].description == "Deploy the app"
    assert names["code-task"].description == "local override of the bundled skill"  # ~/.tpagent beats bundled
    assert {"video-ad-vn", "web-research"} <= set(names)  # bundled skills are found
    out = skills.use_skill("deploy")
    assert out.startswith("# Skill: deploy") and "1. build" in out and "---" not in out
    assert "unknown skill" in skills.use_skill("nope") and "deploy" in skills.use_skill("nope")
    assert "- deploy: Deploy the app" in skills.skills_summary()


def test_skill_without_frontmatter_uses_folder_name(workdir):
    d = workdir / "skills" / "bare"
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text("just a body")
    s = skills.parse_skill(d / "SKILL.md")
    assert s and s.name == "bare" and s.description == "" and s.body() == "just a body"


# --- ask_user ----------------------------------------------------------------
async def test_ask_user_without_hook_tells_model_to_decide():
    assert await AU.ask_user("Which one?", ["a", "b"]) == AU.NO_USER
    res = await AU.TOOLS[0].call(question="Which one?")
    assert res.text == AU.NO_USER and not res.is_error


async def test_ask_user_with_hook_passes_options_and_returns_answer():
    seen = {}

    async def hook(question, options):
        seen.update(question=question, options=options)
        return "  b  "

    token = AU.CURRENT_ASK.set(hook)
    try:
        assert await AU.ask_user(" Which one? ", ["a", "b"]) == "b"
        assert seen == {"question": "Which one?", "options": ["a", "b"]}
        assert await AU.ask_user("free text") == "b" and seen["options"] is None
    finally:
        AU.CURRENT_ASK.reset(token)


# --- workspace root ----------------------------------------------------------
def test_workspace_root_guards_files_and_shell(workdir, tmp_path_factory):
    other = tmp_path_factory.mktemp("ws")
    (other / "in.txt").write_text("inside")
    (workdir / "out.txt").write_text("outside")
    assert get_workspace() == workdir.resolve()
    assert set_workspace(other) == other.resolve()
    assert files.read_file("in.txt").strip().endswith("inside")  # relative paths resolve against the workspace
    with pytest.raises(PermissionError):
        files.resolve(str(workdir / "out.txt"))  # cwd is now outside the workspace
    assert files.write_file("sub/new.txt", "x").startswith("Created") and (other / "sub" / "new.txt").exists()
    assert (other / ".tpagent").exists() is False
    memory.memory_append("note")
    assert (other / ".tpagent" / "MEMORY.md").exists()


async def test_bash_runs_in_workspace(workdir, tmp_path_factory):
    from tpagent.tools.shell import bash

    other = tmp_path_factory.mktemp("ws2")
    set_workspace(other)
    assert (await bash("pwd")).text == str(other.resolve())
    assert (await bash("pwd", cwd=str(workdir))).text == str(workdir.resolve())
