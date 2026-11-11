"""配布物の検査（tools/export.py の inspect_names と payload_matches）のテスト。Pyxelは回さない。

ビルドを通した検査は `python3 tools/export.py` が見る。ここでは、ビルドでは作りにくい形
（外のパス、入口が無い、データが1バイト違う）を、検査の関数に直に与える。
"""
import base64

import pytest

import export

GOOD = ["clipping_point/main.py", "clipping_point/cp_core/sim.py", "clipping_point/.pyxapp_startup_script"]


def kinds(names) -> list:
    return sorted({kind for kind, _ in export.inspect_names(names)})


def html_with(data: bytes) -> str:
    return '<script>launchPyxel({ command: "play", base64: "' + base64.b64encode(data).decode("ascii") + '" });</script>'


def test_export_clean_archive_has_no_problems():
    assert export.inspect_names(GOOD) == []


def test_export_missing_entry_script_is_reported():
    assert kinds(["clipping_point/cp_core/sim.py"]) == ["missing"]


def test_export_path_outside_the_app_directory_is_reported():
    assert kinds(GOOD + ["other/readme.py"]) == ["outside"]


@pytest.mark.parametrize("name", [
    "clipping_point/tests/test_zz.py",
    "clipping_point/cp_core/test_sim.py",
    "clipping_point/cp_core/conftest.py",
    "clipping_point/README.md",
    "clipping_point/tools/check.py",
    "clipping_point/cp_core/__pycache__/sim.cpython-313.pyc",
])
def test_export_forbidden_files_are_reported(name):
    assert kinds(GOOD + [name]) == ["forbidden"]


def test_export_unknown_file_type_is_reported():
    assert kinds(GOOD + ["clipping_point/data/notes.txt"]) == ["unknown_type"]


def test_export_every_reported_kind_is_listed():
    seen = kinds(["other/x.py", "clipping_point/README.md", "clipping_point/data/notes.txt"])
    assert seen == ["forbidden", "missing", "outside", "unknown_type"]
    assert set(seen) <= set(export.KINDS)
    assert {"payload", "size"} <= set(export.KINDS)


def test_export_payload_matches_the_same_bytes():
    assert export.payload_matches(html_with(b"PK\x03\x04abc"), b"PK\x03\x04abc")


def test_export_payload_one_byte_off_is_rejected():
    assert not export.payload_matches(html_with(b"PK\x03\x04abc"), b"PK\x03\x04abd")


def test_export_payload_not_found_is_rejected():
    assert not export.payload_matches("<html></html>", b"abc")
