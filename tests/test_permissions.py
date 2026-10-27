"""PermissionManager: approver hook, allow-list, non-interactive deny, sync compat."""
from __future__ import annotations

from tpagent.core.permissions import PermissionManager
from tpagent.tools import load_tools

TOOLS = {t.name: t for t in load_tools()}
BASH, READ = TOOLS["bash"], TOOLS["read_file"]


async def test_approver_is_consulted_only_for_dangerous_calls():
    seen: list[tuple[str, dict]] = []

    async def approver(tool, args):
        seen.append((tool.name, args))
        return args.get("command") == "rm -rf build"

    pm = PermissionManager(approver=approver, interactive=False)
    assert await pm.check_async(READ, {"path": "x"}) is True
    assert await pm.check_async(BASH, {"command": "echo hi"}) is True  # safe command, no prompt
    assert await pm.check_async(BASH, {"command": "rm -rf build"}) is True
    assert await pm.check_async(BASH, {"command": "sudo rm -rf /"}) is False
    assert [s[0] for s in seen] == ["bash", "bash"]
    assert pm.denied_log == ["bash:sudo rm -rf /"]


async def test_allow_list_and_auto_approve_skip_approver():
    async def approver(tool, args):
        raise AssertionError("approver must not be called")

    pm = PermissionManager(approver=approver, interactive=False)
    pm.allow("bash:git push*")
    assert await pm.check_async(BASH, {"command": "git push --force"}) is True
    pm2 = PermissionManager(auto_approve=True, approver=approver)
    assert await pm2.check_async(BASH, {"command": "sudo reboot"}) is True


async def test_no_approver_non_interactive_denies_and_tty_prompt_runs_in_thread():
    pm = PermissionManager(interactive=False)
    assert await pm.check_async(BASH, {"command": "rm -rf x"}) is False
    answers = iter(["a"])
    pm = PermissionManager(interactive=True, ask_fn=lambda prompt: next(answers))
    assert await pm.check_async(BASH, {"command": "rm -rf x"}) is True
    assert pm.allowed_patterns == ["bash:*"]
    assert await pm.check_async(BASH, {"command": "rm -rf y"}) is True  # remembered, no further prompt


def test_sync_check_still_works():
    pm = PermissionManager(interactive=True, ask_fn=lambda prompt: "n")
    assert pm.check(BASH, {"command": "rm -rf x"}) is False and pm.denied_log
    assert pm.check(READ, {"path": "a"}) is True
