"""ブラウザ版の煙テストの判定（tools/web_smoke.py）と、ランタイムの写しの照合（tools/web/fetch_runtime.py）のテスト。

ブラウザは開かない。実行役（tools/web/webrun.js）が書く結果の形を、判定の関数に直に与える。
実物のブラウザを通した確かめは、道具 web-smoke と selftest-break が見る。
"""
import hashlib
import json

import pytest

import web_smoke
from conftest import ROOT
from cp_app import web_bridge

fetch_runtime = web_smoke.fetch_runtime  # tools/web/ の中。web_smoke が読み込んだものを使う
SHA = "a" * 64
BUDGETS = json.loads((ROOT / "tools" / "budgets.json").read_text(encoding="utf-8"))
TICKS, WARMUP = 660, 60


def page(**changes) -> dict:
    """問題の無い、実行役の結果。"""
    base = {
        "htmlSha256": SHA,
        "failures": [],
        "console": [],
        "clickedAt": 3500,
        "untilAt": None,
        "state": {"overlayText": None, "hasFatalError": False, "initialized": True},
        "canvas": {"ink": 35000, "pixels": 691200},
    }
    return {**base, **changes}


def result(**changes) -> dict:
    """問題の無い、アプリがコンソールへ出す結果。"""
    base = {
        "ticks": TICKS,
        "renders": 330,
        "sim": {"tick": TICKS},
        "warmup_ticks": WARMUP,
        "platform": "emscripten",
        "python": "3.14.2",
        "pyxel": "3.0.1",
        "perf": {"updates": 600, "renders": 300, "span_s": 9.983, "updates_per_s": 60.0, "renders_per_s": 30.05, "update_ms_p95": 0.1, "render_ms_p95": 0.2},
    }
    return {**base, **changes}


def with_perf(**changes) -> dict:
    return result(perf={**result()["perf"], **changes})


def failed(checks) -> list:
    return [name for name, ok, _ in checks if not ok]


def probe_failed(res, sim=None, a_page=None) -> list:
    desktop_sim = {"tick": TICKS} if sim is None else sim
    return failed(web_smoke.judge_probe(a_page or page(untilAt=14000), SHA, res, desktop_sim, TICKS, WARMUP, BUDGETS))


def console_page(*lines, done=True) -> dict:
    return page(untilAt=14000 if done else None, console=[{"t": 1, "type": "log", "text": line} for line in lines])


# --- 何も渡さずに開く筋書き ---
def test_web_smoke_clean_shipped_page_passes():
    assert failed(web_smoke.judge_shipped(page(), SHA)) == []


def test_web_smoke_blank_canvas_fails():
    assert failed(web_smoke.judge_shipped(page(canvas={"ink": 0}), SHA)) == ["canvas_ink"]
    assert failed(web_smoke.judge_shipped(page(canvas=None), SHA)) == ["canvas_ink"]


def test_web_smoke_page_that_never_started_fails():
    assert "started" in failed(web_smoke.judge_shipped(page(clickedAt=None), SHA))


@pytest.mark.parametrize("kind", list(web_smoke.FAILURE_KINDS))
def test_web_smoke_each_failure_kind_fails_under_its_own_name(kind):
    bad = page(failures=[{"t": 5, "kind": kind, "detail": "Traceback (most recent call last):\nRuntimeError: planted"}])
    assert failed(web_smoke.judge_shipped(bad, SHA)) == [kind]


def test_web_smoke_unknown_failure_kind_is_not_ignored():
    bad = page(failures=[{"t": 5, "kind": "something_new", "detail": "x"}])
    assert failed(web_smoke.judge_shipped(bad, SHA)) == ["other_failure"]


def test_web_smoke_other_html_bytes_fail():
    assert failed(web_smoke.judge_shipped(page(htmlSha256="b" * 64), SHA)) == ["html_bytes"]


# --- 回すtick数を渡して開く筋書き ---
def test_web_smoke_clean_probe_passes():
    assert probe_failed(result()) == []


def test_web_smoke_probe_result_is_read_from_the_console():
    line = web_bridge.RESULT_MARK + " " + json.dumps(result())
    assert web_smoke.read_probe_result(console_page("Loaded pyxel", line, web_bridge.DONE_MARK)) == (result(), "")


def test_web_smoke_probe_without_done_signal_has_no_result():
    line = web_bridge.RESULT_MARK + " " + json.dumps(result())
    assert web_smoke.read_probe_result(console_page(line, done=False)) == (None, "no_done_signal")


def test_web_smoke_probe_result_line_must_be_exactly_one_and_readable():
    line = web_bridge.RESULT_MARK + " " + json.dumps(result())
    assert web_smoke.read_probe_result(console_page(web_bridge.DONE_MARK)) == (None, "result_line_count")
    assert web_smoke.read_probe_result(console_page(line, line, web_bridge.DONE_MARK)) == (None, "result_line_count")
    assert web_smoke.read_probe_result(console_page(web_bridge.RESULT_MARK + " {broken", web_bridge.DONE_MARK)) == (None, "result_unreadable")
    assert web_smoke.read_probe_result(console_page(web_bridge.RESULT_MARK + " [1]", web_bridge.DONE_MARK)) == (None, "result_unreadable")


@pytest.mark.parametrize(
    "res, name",
    [
        (result(platform="linux"), "platform"),
        (result(python="3.13.18"), "python"),
        (result(ticks=TICKS - 1), "ticks"),
        (result(sim={"tick": TICKS + 1}), "sim"),
        (result(renders=220), "renders"),
        (result(renders=660), "renders"),
        (result(renders=None), "renders"),
        (with_perf(updates=599), "measured_ticks"),
        (with_perf(updates_per_s=58.9), "updates_per_s"),
        (with_perf(updates_per_s=None), "updates_per_s"),
        (with_perf(renders_per_s=20.0), "renders_per_s"),
        (with_perf(renders_per_s=None), "renders_per_s"),
        (with_perf(update_ms_p95=4.1), "update_ms_p95"),
        (with_perf(update_ms_p95=None), "update_ms_p95"),
        (with_perf(render_ms_p95=12.1), "render_ms_p95"),
        (with_perf(render_ms_p95=True), "render_ms_p95"),
    ],
)
def test_web_smoke_probe_each_value_off_the_line_fails_under_its_own_name(res, name):
    assert probe_failed(res) == [name]


def test_web_smoke_probe_values_on_the_line_pass():
    on_the_line = with_perf(updates_per_s=59, renders_per_s=29, update_ms_p95=4, render_ms_p95=12)
    assert probe_failed(on_the_line) == []


def test_web_smoke_probe_without_perf_fails_every_timing_check():
    names = probe_failed(result(perf=None))
    assert names == ["measured_ticks", *web_smoke.TIMING_CHECKS]


def test_web_smoke_probe_summary_must_equal_the_desktop_one():
    assert probe_failed(result(), sim={"tick": TICKS, "cars": 1}) == ["sim"]


def test_web_smoke_probe_python_error_is_reported_with_the_values():
    bad = page(untilAt=14000, failures=[{"t": 9, "kind": "error_overlay", "detail": "Traceback"}])
    assert probe_failed(result(), a_page=bad) == ["error_overlay"]


# --- ランタイムの写しの照合 ---
def test_fetch_runtime_sums_list_names_every_runtime_file():
    sums = fetch_runtime.read_sums()
    assert len(sums) == 17
    assert all(len(digest) == 64 for digest in sums.values())
    wanted = fetch_runtime.mirror_wanted(sums)
    assert len(wanted) == 16  # tgz そのものは、組み立てたランタイムの写し（mirror/）に入れない
    assert "kitao.dev/pyxel/3.0.1/pyxel.js" in wanted
    assert "kitao.dev/pyxel/pyodide/v314.0.7/pyodide.asm.wasm" in wanted
    assert all(path.startswith("kitao.dev/pyxel/") for path in wanted)


def test_fetch_runtime_sources_are_only_github_and_npm():
    assert fetch_runtime.PYXEL_URL.startswith("https://raw.githubusercontent.com/kitao/pyxel/v3.0.1/wasm/")
    assert fetch_runtime.PYODIDE_URL == "https://registry.npmjs.org/pyodide/-/pyodide-314.0.7.tgz"


def test_fetch_runtime_unreadable_sums_are_an_error(tmp_path):
    path = tmp_path / "SHA256SUMS"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        fetch_runtime.read_sums(path)
    path.write_text("abc  pyxel_wasm_orig/pyxel.js\n", encoding="utf-8")
    with pytest.raises(ValueError):
        fetch_runtime.read_sums(path)
    path.write_text("a" * 64 + "  ../outside.js\n", encoding="utf-8")
    with pytest.raises(ValueError):
        fetch_runtime.read_sums(path)


def test_fetch_runtime_check_reports_missing_and_mismatched_files(tmp_path):
    (tmp_path / "good.js").write_bytes(b"good")
    (tmp_path / "changed.js").write_bytes(b"changed")
    wanted = {
        "good.js": hashlib.sha256(b"good").hexdigest(),
        "changed.js": hashlib.sha256(b"original").hexdigest(),
        "absent.js": hashlib.sha256(b"absent").hexdigest(),
    }
    assert fetch_runtime.check_files(tmp_path, wanted) == (["absent.js"], ["changed.js"])
