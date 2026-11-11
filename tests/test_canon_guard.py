"""正本の見張り（tools/canon_guard.py）のテスト。

正本（docs/canon/planning.md）が正本の要約値の写しと一致することと、見張りそのものが1文字の違いを拾うことを確かめる。
正本は読むだけで、書き換えない。壊す確かめは、一時のディレクトリに作った見本の上で行う。
"""
import hashlib
import json

import canon_guard
from conftest import ROOT

CANON_TEXT = "# 企画書の見本\n\n本文。\n"


def make_repo(root, snapshot_files=None):
    canon = root / "docs" / "canon"
    canon.mkdir(parents=True)
    (canon / "planning.md").write_bytes(CANON_TEXT.encode("utf-8"))
    if snapshot_files is None:
        snapshot_files = {"docs/canon/planning.md": hashlib.sha256(CANON_TEXT.encode("utf-8")).hexdigest()}
    snapshot = root / "tests" / "snapshots" / "canon_digest.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(json.dumps({"_notes": "見本", "files": snapshot_files}), encoding="utf-8")
    return root


def test_canon_this_repository_matches_the_snapshot():
    examined, problems = canon_guard.check_canon(ROOT)
    assert examined >= 1
    assert problems == []


def test_canon_snapshot_lists_the_planning_document():
    recorded = canon_guard.read_snapshot(ROOT)
    assert "docs/canon/planning.md" in recorded
    assert all(len(digest) == 64 for digest in recorded.values())


def test_canon_unchanged_copy_passes(tmp_path):
    assert canon_guard.check_canon(make_repo(tmp_path)) == (1, [])


def test_canon_one_changed_character_is_reported(tmp_path):
    root = make_repo(tmp_path)
    (root / "docs" / "canon" / "planning.md").write_bytes(CANON_TEXT.replace("本文。", "本文、").encode("utf-8"))
    examined, problems = canon_guard.check_canon(root)
    assert examined == 1
    assert len(problems) == 1 and "planning.md" in problems[0]


def test_canon_trailing_newline_change_is_reported(tmp_path):
    root = make_repo(tmp_path)
    (root / "docs" / "canon" / "planning.md").write_bytes((CANON_TEXT + "\n").encode("utf-8"))
    assert len(canon_guard.check_canon(root)[1]) == 1


def test_canon_new_file_without_a_digest_is_reported(tmp_path):
    root = make_repo(tmp_path)
    (root / "docs" / "canon" / "appendix.md").write_text("付録\n", encoding="utf-8")
    examined, problems = canon_guard.check_canon(root)
    assert examined == 2
    assert len(problems) == 1 and "appendix.md" in problems[0]


def test_canon_deleted_file_is_reported(tmp_path):
    root = make_repo(tmp_path)
    (root / "docs" / "canon" / "planning.md").unlink()
    examined, problems = canon_guard.check_canon(root)
    assert examined == 1
    assert len(problems) == 1 and "planning.md" in problems[0]


def test_canon_missing_snapshot_examines_nothing(tmp_path):
    root = make_repo(tmp_path)
    (root / "tests" / "snapshots" / "canon_digest.json").unlink()
    examined, problems = canon_guard.check_canon(root)
    assert examined == 0
    assert len(problems) == 1


def test_canon_unreadable_snapshot_examines_nothing(tmp_path):
    root = make_repo(tmp_path)
    (root / "tests" / "snapshots" / "canon_digest.json").write_text("{not json", encoding="utf-8")
    assert canon_guard.check_canon(root)[0] == 0


def test_canon_check_never_rewrites_the_snapshot(tmp_path):
    # 見張りは照らすだけ。違いを見つけても、要約値の写しを合わせ直さない（取り直す口は tools/claude/canon_digest.py だけ）。
    root = make_repo(tmp_path)
    snapshot = root / "tests" / "snapshots" / "canon_digest.json"
    before = snapshot.read_bytes()
    (root / "docs" / "canon" / "planning.md").write_bytes("書き換えた正本\n".encode("utf-8"))
    assert len(canon_guard.check_canon(root)[1]) == 1
    assert snapshot.read_bytes() == before
