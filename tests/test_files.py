"""File tools: edit uniqueness, glob, grep, path guard."""
from __future__ import annotations

import pytest

from tpagent.tools import files


def test_edit_file_requires_unique_match(workdir):
    f = workdir / "x.py"
    f.write_text("a = 1\nb = 1\n")
    assert "occurs 2 times" in files.edit_file("x.py", "= 1", "= 2")
    assert f.read_text() == "a = 1\nb = 1\n"
    assert "not found" in files.edit_file("x.py", "zzz", "y")
    assert files.edit_file("x.py", "a = 1", "a = 3").startswith("Edited")
    assert f.read_text() == "a = 3\nb = 1\n"
    assert "replaced 1" in files.edit_file("x.py", "= 1", "= 9", replace_all=True)


def test_read_file_offset_limit_and_line_numbers(workdir):
    (workdir / "f.txt").write_text("\n".join(f"L{i}" for i in range(1, 11)))
    out = files.read_file("f.txt", offset=3, limit=2)
    assert out.splitlines()[0].strip().startswith("3\tL3")
    assert "more lines, use offset=5" in out


def test_write_creates_parents(workdir):
    assert files.write_file("sub/dir/n.txt", "hi").startswith("Created")
    assert (workdir / "sub/dir/n.txt").read_text() == "hi"


def test_glob_and_grep(workdir):
    (workdir / "pkg").mkdir()
    (workdir / "pkg/a.py").write_text("def alpha():\n    return 1\n")
    (workdir / "pkg/b.py").write_text("def beta():\n    return alpha()\n")
    (workdir / "notes.md").write_text("alpha in docs")
    globbed = files.glob_files("**/*.py")
    assert "pkg/a.py" in globbed and "pkg/b.py" in globbed and "notes.md" not in globbed
    hits = files.grep_files("alpha", glob="*.py")
    assert "a.py:1:" in hits and "b.py:2:" in hits and "notes.md" not in hits
    assert files.grep_files("nomatch_zzz") == "No matches."
    assert "notes.md" in files.grep_files("ALPHA", ignore_case=True)


def test_python_grep_fallback_matches_rg(workdir):
    (workdir / "c.txt").write_text("foo\nbar foo\n")
    lines = files._python_grep(workdir, "foo", None, False)
    assert len(lines) == 2 and lines[1].endswith(":2:bar foo")


def test_list_dir(workdir):
    (workdir / "d").mkdir()
    (workdir / "d/inner.txt").write_text("")
    (workdir / "top.txt").write_text("")
    out = files.list_dir(".", depth=2)
    assert "d/" in out and "top.txt" in out and "inner.txt" in out


def test_outside_cwd_refused(workdir):
    files.allow_outside_cwd(False)
    with pytest.raises(PermissionError):
        files.resolve("/etc/passwd")
    files.allow_outside_cwd(True)
    try:
        assert files.resolve("/etc/passwd").as_posix() == "/etc/passwd"
    finally:
        files.allow_outside_cwd(False)
