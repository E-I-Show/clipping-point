"""ブラウザ版の煙テストの判定（tools/web_smoke.py）と、ランタイムの写しの取得と照合（tools/web/fetch_runtime.py）のテスト。

ブラウザは開かない。ブラウザの実行役（tools/web/webrun.js）が書く結果の形を、判定の関数に直に与える。
ネットワークも使わない。取得の道は、一時の置き場（tmp_path）と偽の取得の関数で通す。
実物のブラウザを通した確かめは、道具 web-smoke と selftest-break が見る。
"""
import argparse
import base64
import hashlib
import http.client
import io
import json
import sys
import tarfile
import urllib.error

import pytest

import input_reference
import web_smoke
from conftest import ROOT
from cp_app import input_web, storage_select, storage_web, web_bridge
from cp_app.input_trace import InputTrace
from cp_core import profile, storage
from cp_core.input_frame import BUTTONS, QUANTIZED_FIELDS, button_bits

fetch_runtime = web_smoke.fetch_runtime  # tools/web/ の中。web_smoke が読み込んだものを使う
SHA = "a" * 64
BUDGETS = json.loads((ROOT / "tools" / "budgets.json").read_text(encoding="utf-8"))
TOLERANCE = BUDGETS["web_renders_tolerance"]
TICKS, WARMUP = 660, 60
RENDERS, MEASURED_RENDERS = TICKS // 2, (TICKS - WARMUP) // 2
# 台本を渡す筋書きと、偽のコントローラーの筋書きの値。
SCRIPT_VALUE, SCRIPT = input_reference.load_script(input_reference.SMOKE_SCRIPT)
SCRIPT_TICKS = BUDGETS["web_script_ticks"]
STAGE, SETTLE = BUDGETS["web_pad_stage_ticks"], BUDGETS["web_pad_settle_ticks"]
PAD_TICKS = web_smoke.pad_ticks(STAGE)
FIELD = {name: index for index, name in enumerate(QUANTIZED_FIELDS)}
WARN_LINE = {"t": 5, "type": "warning", "text": input_web.WARN_MARK + " direct trigger read failed: AttributeError: mapping"}
# 保存の往復が、ブラウザの localStorage に残す値（base64 の文字列）と、その鍵。
SELFCHECK_KEY = "clippingpoint/selfcheck.settings"
SELFCHECK_BLOB = storage.wrap(profile.encode(profile.SELFCHECK_SETTINGS), profile.SETTINGS_VERSION)
# 道具が、定義データのファイルを自分で読んで数えた、表ごとの項目の数（実物）。probe の筋書きが、結果の data と照らす。
DATA_TABLES = web_smoke.data_reference.expected_tables()[0]


def stored(blob: bytes = SELFCHECK_BLOB) -> str:
    return base64.b64encode(blob).decode("ascii")


def page(**changes) -> dict:
    """問題の無い、ブラウザの実行役の結果。localStorage は、頼まなければ読まない（null）。"""
    base = {
        "htmlSha256": SHA,
        "failures": [],
        "console": [],
        "clickedAt": 3500,
        "untilAt": None,
        "state": {"overlayText": None, "hasFatalError": False, "initialized": True},
        "canvas": {"ink": 35000, "pixels": 691200},
        "localStorage": None,
    }
    return {**base, **changes}


def local_storage(entries=None, error=None) -> dict:
    """ブラウザの実行役が読んだ、localStorage の中身。既定は、保存の往復が残した値だけ。"""
    entries = {SELFCHECK_KEY: stored()} if entries is None and error is None else entries
    return {"prefix": storage_web.PREFIX, "entries": entries, "error": error}


def probe_page(**changes) -> dict:
    """問題の無い、probe の筋書きの、ブラウザの実行役の結果。完了の合図が出ていて、localStorage を読んである。"""
    return page(**{"untilAt": 14000, "localStorage": local_storage(), **changes})


def shipped_page(**changes) -> dict:
    """問題の無い、shipped の筋書きの、ブラウザの実行役の結果。localStorage を読んであり、このアプリの鍵は1つも無い。"""
    return page(**{"localStorage": local_storage({}), **changes})


def result(**changes) -> dict:
    """問題の無い、アプリがコンソールへ出す結果。"""
    measured = {"updates": 600, "renders": MEASURED_RENDERS, "span_s": 9.983, "updates_per_s": 60.0, "renders_per_s": 30.05, "update_ms_p95": 0.1, "render_ms_p95": 0.2}
    whole = {"updates": TICKS, "renders": RENDERS, "span_s": 10.983, "updates_per_s": 60.0, "renders_per_s": 30.04, "update_ms_p95": 0.1, "render_ms_p95": 0.3}
    base = {
        "ticks": TICKS,
        "renders": RENDERS,
        "sim": {"tick": TICKS},
        "warmup_ticks": WARMUP,
        "platform": "emscripten",
        "python": "3.14.2",
        "pyxel": "3.0.1",
        "perf": {**measured, "with_warmup": whole},
        # 台本を渡さない筋書き。入力アダプタと直読みを、1 tickに1度ずつ呼んでいる。
        "input_source": "adapter",
        "adapter_reads": TICKS,
        "direct_reads": TICKS,
        # 保存先は localStorage。保存の往復が通っていて、知らせは無い。
        "storage": {"backend": "localstorage", "ok": True, "notice": "", "detail": ""},
        # 定義データ。警告は無く、試験用データを重ねていない（ブラウザ版は重ねない）。設定を読んだ保存の口の名前空間は main。
        "data": {"tables": dict(DATA_TABLES), "warnings": 0, "pack": None, "namespace": "main"},
    }
    return {**base, **changes}


def with_perf(**changes) -> dict:
    return result(perf={**result()["perf"], **changes})


def with_storage(**changes) -> dict:
    return result(storage={**result()["storage"], **changes})


def with_data(**changes) -> dict:
    return result(data={**result()["data"], **changes})


def failed(checks) -> list:
    return [name for name, ok, _ in checks if not ok]


def probe_failed(res, sim=None, a_page=None) -> list:
    desktop_sim = {"tick": TICKS} if sim is None else sim
    return failed(web_smoke.judge_probe(a_page or probe_page(), SHA, res, desktop_sim, TICKS, WARMUP, BUDGETS, DATA_TABLES))


def console_page(*lines, done=True) -> dict:
    return page(untilAt=14000 if done else None, console=[{"t": 1, "type": "log", "text": line} for line in lines])


def last_line(capsys) -> str:
    return capsys.readouterr().out.strip().splitlines()[-1]


# --- 何も渡さずに開く筋書き ---
def test_web_smoke_clean_shipped_page_passes():
    assert failed(web_smoke.judge_shipped(shipped_page(), SHA)) == []


def test_web_smoke_blank_canvas_fails():
    assert failed(web_smoke.judge_shipped(shipped_page(canvas={"ink": 0}), SHA)) == ["canvas_ink"]
    assert failed(web_smoke.judge_shipped(shipped_page(canvas=None), SHA)) == ["canvas_ink"]


def test_web_smoke_page_that_never_started_fails():
    assert "started" in failed(web_smoke.judge_shipped(shipped_page(clickedAt=None), SHA))
    not_initialized = {"overlayText": None, "hasFatalError": False, "initialized": False}
    assert failed(web_smoke.judge_shipped(shipped_page(state=not_initialized), SHA)) == ["started"]
    assert failed(web_smoke.judge_shipped(shipped_page(state=None), SHA)) == ["started"]  # 状態を読めなかった


@pytest.mark.parametrize("kind", list(web_smoke.FAILURE_KINDS))
def test_web_smoke_each_failure_kind_fails_under_its_own_name(kind):
    bad = shipped_page(failures=[{"t": 5, "kind": kind, "detail": "Traceback (most recent call last):\nRuntimeError: planted"}])
    assert failed(web_smoke.judge_shipped(bad, SHA)) == [kind]


def test_web_smoke_unresponsive_page_is_a_failure_kind():
    assert "unresponsive" in web_smoke.FAILURE_KINDS


def test_web_smoke_unknown_failure_kind_is_not_ignored():
    bad = shipped_page(failures=[{"t": 5, "kind": "something_new", "detail": "x"}])
    assert failed(web_smoke.judge_shipped(bad, SHA)) == ["other_failure"]


def test_web_smoke_other_html_bytes_fail():
    assert failed(web_smoke.judge_shipped(shipped_page(htmlSha256="b" * 64), SHA)) == ["html_bytes"]


# --- 保存（shipped の筋書き）：ふつうの起動の後の localStorage に、このアプリの鍵が1つも無い ---
def test_web_smoke_shipped_storage_check_comes_last_and_only_once():
    names = [name for name, _, _ in web_smoke.judge_shipped(shipped_page(), SHA)]
    assert names[-3:] == ["started", "canvas_ink", "storage_empty"] and names.count("storage_empty") == 1
    assert web_smoke.nothing_stored_check(shipped_page())[:2] == ("storage_empty", True)


@pytest.mark.parametrize(
    "entries",
    [
        {SELFCHECK_KEY: stored()},  # 検証の口でないのに、保存の往復を回した
        {storage_web.PREFIX + storage_web.PROBE_KEY: storage_web.PROBE_VALUE},  # 試し書きの鍵を、消していない
        {"clippingpoint/main.settings": stored()},  # 何も操作していないのに、設定を書いた
        {"clippingpoint/main.settings.bad": "x"},
        {"clippingpoint/": ""},
        {SELFCHECK_KEY: stored(), "clippingpoint/storage-probe": "cp", "clippingpoint/main.settings": stored()},
    ],
)
def test_web_smoke_shipped_any_key_of_the_app_left_in_local_storage_fails(entries):
    checks = web_smoke.judge_shipped(shipped_page(localStorage=local_storage(entries)), SHA)
    assert failed(checks) == ["storage_empty"]
    message = next(text for name, _, text in checks if name == "storage_empty")
    assert all(key in message for key in entries)  # 残っている鍵の名を出す


@pytest.mark.parametrize(
    "seen",
    [
        None,  # 頼んでいない（ブラウザの実行役へ --local-storage を渡していない）
        {},
        "entries",
        local_storage(error="SecurityError: Access is denied"),  # 触れると例外
        {"prefix": storage_web.PREFIX, "entries": [], "error": None},
        {"prefix": "someone_else/", "entries": {}, "error": None},  # 別の頭の鍵を読んだ。空でも、何も見ていない
        {"entries": {}, "error": None},
    ],
)
def test_web_smoke_shipped_local_storage_that_was_not_read_is_not_a_pass(seen):
    # 鍵が0件で通す確かめなので、読めていないことと、鍵が無いことを、取り違えない。
    assert failed(web_smoke.judge_shipped(shipped_page(localStorage=seen), SHA)) == ["storage_empty"]
    assert failed(web_smoke.judge_shipped(page(), SHA)) == ["storage_empty"]


def test_web_smoke_shipped_keys_of_other_pages_are_not_counted():
    # ブラウザの実行役は、鍵の頭で絞って読む。絞り漏れがあっても、このアプリの鍵でなければ数えない。
    entries = {"someone_else": "x", "clippingpoint": "y", "other/clippingpoint/main.settings": "z"}
    assert failed(web_smoke.judge_shipped(shipped_page(localStorage=local_storage(entries)), SHA)) == []


def test_web_smoke_shipped_scenario_asks_the_browser_runner_for_the_local_storage(monkeypatch):
    asked = []

    def fake_open_page(name, timeout_s, extra):
        asked.append((name, timeout_s, [str(part) for part in extra]))
        return shipped_page()

    monkeypatch.setattr(web_smoke, "open_page", fake_open_page)
    args = argparse.Namespace(timeout=7.0)
    checks, facts, reason = web_smoke.scenario_shipped(args, BUDGETS, SHA, {})
    assert failed(checks) == [] and reason == "" and facts == ["canvas_ink=35000"]
    (name, timeout_s, extra), = asked
    assert (name, timeout_s) == ("shipped", 7.0)
    at = extra.index("--local-storage")
    assert extra[at + 1] == storage_web.PREFIX == "clippingpoint/"
    assert extra[extra.index("--watch-ms") + 1] == str(int(BUDGETS["web_shipped_watch_s"] * 1000))
    # ブラウザの実行役の結果が無ければ、回り切れない。
    monkeypatch.setattr(web_smoke, "open_page", lambda name, timeout_s, extra: None)
    assert web_smoke.scenario_shipped(args, BUDGETS, SHA, {}) == (None, [], "no_runner_result")


def test_web_smoke_without_node_is_2_before_anything_is_touched(monkeypatch, capsys):
    def must_not_run(*args, **kwargs):
        pytest.fail("node が無いのに、先へ進んだ")

    monkeypatch.setattr(web_smoke.shutil, "which", lambda name: None)
    monkeypatch.setattr(web_smoke.shutil, "rmtree", must_not_run)  # out/ に触れる前に戻ること
    monkeypatch.setattr(web_smoke, "run", must_not_run)
    monkeypatch.setattr(sys, "argv", ["web_smoke.py"])
    assert web_smoke.main() == 2
    assert "reason=no_node" in last_line(capsys)


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
        (result(ticks=TICKS + 1), "ticks"),
        (result(input_source="script"), "input_source"),
        (result(input_source="none"), "input_source"),
        (result(input_source=None), "input_source"),
        (result(adapter_reads=0), "adapter_reads"),
        (result(adapter_reads=2 * TICKS), "adapter_reads"),
        (result(adapter_reads=None), "adapter_reads"),
        (result(direct_reads=0), "direct_reads"),
        (result(direct_reads=2 * TICKS), "direct_reads"),
        (result(direct_reads=None), "direct_reads"),
        (result(sim={"tick": TICKS + 1}), "sim"),
        (result(renders=220), "renders"),
        (result(renders=660), "renders"),
        (result(renders=RENDERS + TOLERANCE + 1), "renders"),
        (result(renders=RENDERS - TOLERANCE - 1), "renders"),
        (result(renders=None), "renders"),
        (with_perf(updates=599), "measured_ticks"),
        (with_perf(renders=MEASURED_RENDERS + TOLERANCE + 1), "perf_renders"),
        (with_perf(renders=MEASURED_RENDERS - TOLERANCE - 1), "perf_renders"),
        (with_perf(renders=2 * MEASURED_RENDERS), "perf_renders"),
        (with_perf(renders=0), "perf_renders"),
        (with_perf(renders=None), "perf_renders"),
        (with_perf(updates_per_s=58.9), "updates_per_s"),
        (with_perf(updates_per_s=None), "updates_per_s"),
        (with_perf(renders_per_s=28.9), "renders_per_s"),
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


@pytest.mark.parametrize("sign", [1, -1])
def test_web_smoke_probe_values_on_the_line_pass(sign):
    on_the_line = result(
        renders=RENDERS + sign * TOLERANCE,
        perf={**result()["perf"], "renders": MEASURED_RENDERS + sign * TOLERANCE, "updates_per_s": 59, "renders_per_s": 29, "update_ms_p95": 4, "render_ms_p95": 12},
    )
    assert probe_failed(on_the_line) == []


def test_web_smoke_probe_judges_the_measured_values_not_the_ones_with_the_warmup():
    # 慣らしを入れた値は、出すだけ。線の判定には使わない。
    slow_start = with_perf(with_warmup={**result()["perf"]["with_warmup"], "update_ms_p95": 50.0, "updates_per_s": 40.0})
    assert probe_failed(slow_start) == []


def test_web_smoke_probe_without_perf_fails_every_timing_check():
    names = probe_failed(result(perf=None))
    assert names == ["measured_ticks", "perf_renders", *web_smoke.TIMING_CHECKS]


def test_web_smoke_probe_summary_must_equal_the_desktop_one():
    assert probe_failed(result(), sim={"tick": TICKS, "cars": 1}) == ["sim"]


def test_web_smoke_probe_measures_updates_that_read_the_input():
    # 通過条件の時間の線を見るのは、この筋書きだけ。入力アダプタも直読みも呼ばない更新で測った結果は、
    # 世界の要約も時間の線も通ってしまう（どちらも、何も押していない入力）。出どころと回数で落とす。
    no_input = result(input_source="none", adapter_reads=0, direct_reads=0)
    assert probe_failed(no_input) == ["input_source", "adapter_reads", "direct_reads"]
    old_shape = {key: value for key, value in result().items() if key not in ("input_source", "adapter_reads", "direct_reads")}
    assert probe_failed(old_shape) == ["input_source", "adapter_reads", "direct_reads"]


def test_web_smoke_probe_input_checks_come_right_after_the_ticks_check():
    # 回したtickが足りないときの、最後の1行の語（failed=probe.ticks,…）が変わらないように、ticks の後ろに置く。
    names = [name for name, _, _ in web_smoke.judge_probe(probe_page(), SHA, result(), {"tick": TICKS}, TICKS, WARMUP, BUDGETS, DATA_TABLES)]
    at = names.index("ticks")
    assert names[at:at + 5] == ["ticks", "input_source", "adapter_reads", "direct_reads", "measured_ticks"]
    assert names.count("platform") == 1 and names.count("ticks") == 1  # 二重に見ない
    short = result(ticks=TICKS - 1, adapter_reads=TICKS - 1, direct_reads=TICKS - 1)
    assert probe_failed(short)[0] == "ticks"


def test_web_smoke_probe_python_error_is_reported_with_the_values():
    bad = probe_page(failures=[{"t": 9, "kind": "error_overlay", "detail": "Traceback"}])
    assert probe_failed(result(), a_page=bad) == ["error_overlay"]


# --- 保存（probe の筋書き）：アプリの申告と、道具が自分で読んだ localStorage の値 ---
STORAGE_CHECKS = ["storage_backend", "storage_ok", "storage_notice", "storage_value", "storage_main"]


def test_web_smoke_probe_storage_checks_come_right_after_the_summary_check():
    names = [name for name, _, _ in web_smoke.judge_probe(probe_page(), SHA, result(), {"tick": TICKS}, TICKS, WARMUP, BUDGETS, DATA_TABLES)]
    at = names.index("sim")
    assert names[at + 1:at + 6] == STORAGE_CHECKS
    assert all(names.count(name) == 1 for name in STORAGE_CHECKS)


@pytest.mark.parametrize(
    "res, names",
    [
        (with_storage(backend="memory"), ["storage_backend"]),  # 試し書きが通らずに、切り替えた
        (with_storage(backend="file"), ["storage_backend"]),
        (with_storage(backend=None), ["storage_backend"]),
        (with_storage(ok=False, detail="CorruptError: checksum mismatch"), ["storage_ok"]),
        (with_storage(ok=None), ["storage_ok"]),
        (with_storage(ok=1), ["storage_ok"]),  # 真偽の値でなければ、通っていない
        (with_storage(notice=storage.NOTICE_UNREADABLE), ["storage_notice"]),
        (with_storage(notice=None), ["storage_notice"]),
        (result(storage=None), ["storage_backend", "storage_ok", "storage_notice"]),
        ({key: value for key, value in result().items() if key != "storage"}, ["storage_backend", "storage_ok", "storage_notice"]),  # 古い形の結果
    ],
)
def test_web_smoke_probe_each_storage_deviation_fails_under_its_own_name(res, names):
    assert probe_failed(res) == names


def blob_of(settings=profile.SELFCHECK_SETTINGS, version: int = profile.SETTINGS_VERSION) -> bytes:
    return storage.wrap(profile.encode(settings), version)


@pytest.mark.parametrize(
    "entries, names",
    [
        ({}, ["storage_value"]),  # 保存の往復の鍵が無い
        ({"clippingpoint/other.settings": stored()}, ["storage_value"]),
        ({SELFCHECK_KEY: None}, ["storage_value"]),
        ({SELFCHECK_KEY: "not base64 at all!"}, ["storage_value"]),
        ({SELFCHECK_KEY: stored(SELFCHECK_BLOB[:-1])}, ["storage_value"]),  # 最後の1バイトが欠けた封筒
        ({SELFCHECK_KEY: stored(b"not an envelope")}, ["storage_value"]),
        ({SELFCHECK_KEY: stored(blob_of(profile.Settings()))}, ["storage_value"]),  # 往復の見本でない設定（既定値）
        ({SELFCHECK_KEY: stored(blob_of(version=profile.SETTINGS_VERSION + 1))}, ["storage_value"]),  # 形式バージョンが違う
        ({SELFCHECK_KEY: stored(), "clippingpoint/main.settings": stored()}, ["storage_main"]),  # ふつうの鍵に触れている
        ({"clippingpoint/main.settings": stored()}, ["storage_value", "storage_main"]),  # 往復を、名前空間 main で回した
    ],
)
def test_web_smoke_probe_checks_the_stored_value_it_read_itself(entries, names):
    # アプリの申告（往復が通った）は合っている。道具が、ブラウザの localStorage を自分で読んだ値で落とす。
    assert probe_failed(result(), a_page=probe_page(localStorage=local_storage(entries))) == names


def test_web_smoke_probe_other_keys_under_the_prefix_do_not_fail():
    # 退避の鍵や、後の段で足す鍵があっても、落とさない。見るのは、保存の往復の鍵と、ふつうの保存（名前空間 main）の鍵だけ。
    entries = {SELFCHECK_KEY: stored(), "clippingpoint/selfcheck.settings.bad": "x", "clippingpoint/pack.settings": "y"}
    assert probe_failed(result(), a_page=probe_page(localStorage=local_storage(entries))) == []


@pytest.mark.parametrize("seen", [None, {}, "entries", local_storage(error="SecurityError: Access is denied"), {"entries": [SELFCHECK_KEY]}])
def test_web_smoke_probe_local_storage_that_was_not_read_fails_both_value_checks(seen):
    # ブラウザの実行役が、localStorage を読めていない（頼んでいない、触れると例外）。何も見ずに通さない。
    assert probe_failed(result(), a_page=probe_page(localStorage=seen)) == ["storage_value", "storage_main"]


def test_web_smoke_reads_the_stored_settings_from_base64_and_the_envelope():
    assert web_smoke.read_stored_settings({SELFCHECK_KEY: stored()})[0] is True
    assert web_smoke.SELFCHECK_STORAGE_KEY == SELFCHECK_KEY
    assert web_smoke.MAIN_STORAGE_PREFIX == "clippingpoint/main."
    ok, message = web_smoke.read_stored_settings({SELFCHECK_KEY: stored(blob_of(profile.Settings()))})
    assert ok is False and "往復の見本と違う" in message
    for entries in (None, [], {}, {SELFCHECK_KEY: 5}):
        assert web_smoke.read_stored_settings(entries)[0] is False


# --- 定義データ（probe の筋書き）：結果の data を、道具が自分で数えた件数と照らす ---
DATA_CHECKS = ["data_tables", "data_warnings", "data_pack", "data_namespace"]


def test_web_smoke_probe_data_checks_come_right_after_the_storage_checks():
    names = [name for name, _, _ in web_smoke.judge_probe(probe_page(), SHA, result(), {"tick": TICKS}, TICKS, WARMUP, BUDGETS, DATA_TABLES)]
    at = names.index("storage_main")
    assert names[at + 1:at + 5] == DATA_CHECKS == list(web_smoke.data_reference.DATA_CHECKS)
    assert all(names.count(name) == 1 for name in DATA_CHECKS)
    assert DATA_TABLES == {"cars": 1, "tracks": 1, "assists": 1}  # 実物の定義データを、道具が自分で数えた件数


@pytest.mark.parametrize(
    "res, names",
    [
        (with_data(tables={"cars": 2, "tracks": 1}), ["data_tables"]),
        (with_data(tables={"cars": 0, "tracks": 0}), ["data_tables"]),  # 定義データを読まずに、空の定義で起動した
        (with_data(tables=None), ["data_tables"]),
        (with_data(warnings=1), ["data_warnings"]),
        (with_data(warnings=None), ["data_warnings"]),
        (with_data(pack="extreme"), ["data_pack"]),  # ブラウザ版は、試験用データを重ねない
        (with_data(namespace="pack_extreme"), ["data_namespace"]),
        (with_data(namespace=None), ["data_namespace"]),
        (with_data(pack="extreme", namespace="pack_extreme", tables={"cars": 2, "tracks": 2}), ["data_tables", "data_pack", "data_namespace"]),
        (result(data=None), DATA_CHECKS),
        ({key: value for key, value in result().items() if key != "data"}, DATA_CHECKS),  # 古い形の結果
    ],
)
def test_web_smoke_probe_each_data_deviation_fails_under_its_own_name(res, names):
    assert probe_failed(res) == names


def test_web_smoke_probe_data_that_the_tool_could_not_count_does_not_pass():
    # 道具が、定義データのファイルを数えられなかった（読めない）。アプリの申告だけで通さない。
    checks = web_smoke.judge_probe(probe_page(), SHA, result(), {"tick": TICKS}, TICKS, WARMUP, BUDGETS, None, "cars.json: ValueError")
    assert failed(checks) == ["data_tables"]
    assert "cars.json: ValueError" in next(message for name, _, message in checks if name == "data_tables")


# --- 保存先に触れると例外になるようにして開く筋書き ---
BLOCKED_TICKS = BUDGETS["web_blocked_ticks"]


def blocked_result(**changes) -> dict:
    """問題の無い、保存先に触れると例外になる筋書きの結果。保存先はメモリへ切り替わり、知らせが出ている。"""
    base = {
        "ticks": BLOCKED_TICKS,
        "renders": BLOCKED_TICKS // 2,
        "sim": input_reference.sim_summary(None, BLOCKED_TICKS),
        "warmup_ticks": 0,
        "platform": "emscripten",
        "python": "3.14.2",
        "pyxel": "3.0.1",
        "input_source": "adapter",
        "adapter_reads": BLOCKED_TICKS,
        "direct_reads": BLOCKED_TICKS,
        "storage": {"backend": "memory", "ok": True, "notice": storage.NOTICE_MEMORY_FALLBACK, "detail": ""},
    }
    return {**base, **changes}


def blocked_failed(res, a_page=None) -> list:
    return failed(web_smoke.judge_storage_blocked(a_page or page(untilAt=6000), SHA, res, BLOCKED_TICKS))


def blocked_storage(**changes) -> dict:
    return blocked_result(storage={**blocked_result()["storage"], **changes})


def test_web_smoke_clean_storage_blocked_scenario_passes():
    assert blocked_failed(blocked_result()) == []
    assert storage_select.BACKEND_MEMORY == "memory"


@pytest.mark.parametrize(
    "res, names",
    [
        (blocked_storage(backend="localstorage"), ["storage_backend"]),  # 試し書きをせずに、localStorage を使っている
        (blocked_storage(notice=""), ["storage_notice"]),  # 切り替えたのに、知らせが出ていない（表示用の値へ渡っていない）
        (blocked_storage(notice=storage.NOTICE_UNREADABLE), ["storage_notice"]),  # 別の文
        (blocked_storage(notice=None), ["storage_notice"]),
        (blocked_storage(ok=False, detail="StorageError: localStorage is missing"), ["storage_ok"]),
        (blocked_storage(backend="localstorage", ok=False, notice=storage.NOTICE_BACKEND_UNREADABLE), ["storage_backend", "storage_ok", "storage_notice"]),
        (blocked_result(storage=None), ["storage_backend", "storage_ok", "storage_notice"]),
        (blocked_result(platform="linux"), ["platform"]),
        (blocked_result(ticks=BLOCKED_TICKS - 1), ["ticks"]),
        (blocked_result(input_source="script"), ["input_source"]),
        (blocked_result(adapter_reads=0), ["adapter_reads"]),
        (blocked_result(direct_reads=2 * BLOCKED_TICKS), ["direct_reads"]),
    ],
)
def test_web_smoke_storage_blocked_each_deviation_fails_under_its_own_name(res, names):
    assert blocked_failed(res) == names


def test_web_smoke_storage_blocked_python_error_and_input_warning_are_reported():
    # 切り替えの判定を誤って、例外が外へ出た形。
    bad = page(untilAt=6000, failures=[{"t": 9, "kind": "error_overlay", "detail": "Traceback\nJsException: SecurityError"}])
    assert blocked_failed(blocked_result(), a_page=bad) == ["error_overlay"]
    assert blocked_failed(blocked_result(), a_page=page(untilAt=6000, console=[WARN_LINE])) == ["input_warn"]


def test_web_smoke_storage_blocked_does_not_look_at_the_timing_lines_or_the_stored_value():
    names = [name for name, _, _ in web_smoke.judge_storage_blocked(page(untilAt=6000), SHA, blocked_result(), BLOCKED_TICKS)]
    assert not set(names) & set(web_smoke.TIMING_CHECKS)
    assert "storage_value" not in names and "storage_main" not in names  # localStorage は読めない。メモリの中は、道具から見えない
    assert names[-3:] == ["storage_backend", "storage_ok", "storage_notice"]


def test_web_smoke_blocked_init_script_is_the_block_script_then_the_probe_line():
    script = web_smoke.blocked_init_script(BLOCKED_TICKS)
    lines = script.splitlines()
    assert lines[-1] == f"window.{web_bridge.PROBE_NAME} = " + json.dumps({"ticks": BLOCKED_TICKS}) + ";"
    assert web_smoke.BLOCK_STORAGE_JS.read_text(encoding="utf-8").strip() in script
    assert script.index("localStorage") < script.index(web_bridge.PROBE_NAME)  # 保存先を止めてから、値を置く
    assert BLOCKED_TICKS >= 2  # 知らせを入れた表示用の値が、1度は組み立てられる長さ


def test_web_smoke_block_storage_script_makes_touching_local_storage_throw():
    source = web_smoke.BLOCK_STORAGE_JS.read_text(encoding="utf-8")
    assert web_smoke.BLOCK_STORAGE_JS.name == "block_storage.js"
    assert 'Object.defineProperty(window, "localStorage"' in source and "get()" in source and "throw error;" in source
    assert 'new DOMException(MESSAGE, "SecurityError")' in source
    # ブラウザが自分で投げる例外と同じく、stack を持たせる（無いと、Pythonから見える例外の名が変わる。実測）。
    assert 'Object.defineProperty(error, "stack"' in source


def test_web_smoke_browser_runner_reads_local_storage_only_when_asked_and_through_the_guarded_call():
    source = web_smoke.WEBRUN.read_text(encoding="utf-8")
    assert '"--local-storage": "localStorage"' in source
    assert "if (opt.localStorage) {" in source
    # ページへの問い合わせは、時間切れつきの口（ask）を通す。
    block = source[source.index("if (opt.localStorage) {"):source.index("async function main()")]
    assert "result.localStorage = await ask(" in block and "page.evaluate(" not in block
    assert "window.localStorage.getItem(key)" in block and "key.startsWith(prefix)" in block


# --- 筋書きの並びと、直読みの警告（どの筋書きでも見る） ---
def test_web_smoke_scenarios_come_in_the_fixed_order():
    assert web_smoke.SCENARIOS == ("shipped", "probe", "script", "gamepad", "storage_blocked")
    assert tuple(web_smoke.RUNNERS) == web_smoke.SCENARIOS


def test_web_smoke_input_warning_fails_the_shipped_and_the_probe_scenario():
    # 直読みは、読めないときに「未接続」と同じ値を返す。読み方の誤りは、警告の行でしか拾えない。
    assert failed(web_smoke.judge_shipped(shipped_page(console=[WARN_LINE]), SHA)) == ["input_warn"]
    assert probe_failed(result(), a_page=probe_page(console=[WARN_LINE])) == ["input_warn"]


def test_web_smoke_other_console_lines_are_not_input_warnings():
    lines = [{"t": 1, "type": "warning", "text": "some other warning"}, {"t": 2, "type": "log", "text": "CP_PROBE_DONE"}]
    assert failed(web_smoke.judge_shipped(shipped_page(console=lines), SHA)) == []


# --- 台本を渡して開く筋書き ---
def trace_report(rows, max_changes: int = 100000) -> dict:
    """tickごとの値の列から、アプリが出す形の入力の跡を作る。"""
    trace = InputTrace(max_changes)
    for tick, row in enumerate(rows):
        trace.on_tick(tick, row)
    return trace.report()


def script_rows() -> list:
    return input_reference.quantized_rows(SCRIPT, SCRIPT_TICKS)


def script_result(**changes) -> dict:
    """問題の無い、台本を渡した筋書きの結果。"""
    base = {
        "ticks": SCRIPT_TICKS,
        "renders": SCRIPT_TICKS // 2,
        "sim": input_reference.sim_summary(SCRIPT, SCRIPT_TICKS),
        "warmup_ticks": 0,
        "platform": "emscripten",
        "python": "3.14.2",
        "pyxel": "3.0.1",
        "input_source": "script",
        "adapter_reads": 0,
        "direct_reads": 0,  # 台本のときは、入力アダプタも直読みも呼ばない
        "inputs": trace_report(script_rows()),
    }
    return {**base, **changes}


def script_failed(res, desktop_sim=None, a_page=None) -> list:
    sim = input_reference.sim_summary(SCRIPT, SCRIPT_TICKS) if desktop_sim is None else desktop_sim
    return failed(web_smoke.judge_script(a_page or page(untilAt=6000), SHA, res, sim, SCRIPT, SCRIPT_TICKS))


def changed_row(rows: list, tick: int, **values) -> list:
    """rows の tick の値を、名前で書き換えた列。"""
    row = list(rows[tick])
    for name, value in values.items():
        row[FIELD[name]] = value
    return [*rows[:tick], tuple(row), *rows[tick + 1:]]


def test_web_smoke_clean_script_scenario_passes():
    assert script_failed(script_result()) == []


def test_web_smoke_script_scenario_runs_past_the_end_of_the_script():
    assert SCRIPT_TICKS > SCRIPT.total_ticks  # 台本を過ぎた後の、何も押していない入力も通す
    assert BUDGETS["web_input_trace_max"] > len(trace_report(script_rows())["changes"])  # 打ち切りにならない


@pytest.mark.parametrize(
    "res, names",
    [
        (script_result(platform="linux"), ["platform"]),
        (script_result(ticks=SCRIPT_TICKS - 1), ["ticks"]),
        (script_result(input_source="adapter"), ["input_source"]),
        (script_result(input_source="mixed"), ["input_source"]),
        (script_result(input_source=None), ["input_source"]),
        (script_result(adapter_reads=SCRIPT_TICKS), ["adapter_reads"]),
        (script_result(adapter_reads=None), ["adapter_reads"]),
        (script_result(direct_reads=SCRIPT_TICKS), ["direct_reads"]),  # 台本のときも、直読みを呼んでいる
        (script_result(direct_reads=1), ["direct_reads"]),
        (script_result(direct_reads=None), ["direct_reads"]),
        (script_result(sim={"tick": SCRIPT_TICKS, "input_digest": 1}), ["sim", "sim_reference"]),
        (script_result(sim=None), ["sim", "sim_reference"]),
        (script_result(inputs=None), ["trace_complete", "trace"]),
        (script_result(inputs=trace_report(script_rows(), max_changes=5)), ["trace_complete", "trace"]),
        (script_result(inputs={**trace_report(script_rows()), "truncated": True}), ["trace_complete", "trace"]),
        (script_result(inputs=trace_report(changed_row(script_rows(), 40, steer_digital=0))), ["trace"]),
        (script_result(inputs=trace_report(changed_row(script_rows(), SCRIPT_TICKS - 1, held=1))), ["trace"]),
        (script_result(inputs=trace_report([script_rows()[0], *script_rows()[:-1]])), ["trace"]),  # 1 tick遅れ
        (script_result(inputs=trace_report([(0,) * 8] * SCRIPT_TICKS)), ["trace"]),  # 入力アダプタから読んだ（何も押していない）
    ],
)
def test_web_smoke_script_each_deviation_fails_under_its_own_name(res, names):
    assert script_failed(res) == names


def test_web_smoke_script_summary_must_equal_the_desktop_one_and_the_reference():
    # デスクトップ版だけが違う（ブラウザ版は参照と同じ）なら、sim だけが落ちる。
    assert script_failed(script_result(), desktop_sim={"tick": SCRIPT_TICKS, "input_digest": 1}) == ["sim"]
    # 何も押していない入力で回した世界の要約は、台本の参照と違う。
    neutral = input_reference.sim_summary(None, SCRIPT_TICKS)
    assert script_failed(script_result(sim=neutral), desktop_sim=neutral) == ["sim_reference"]


def test_web_smoke_script_python_error_and_input_warning_are_reported():
    bad = page(untilAt=6000, failures=[{"t": 9, "kind": "error_overlay", "detail": "Traceback"}])
    assert script_failed(script_result(), a_page=bad) == ["error_overlay"]
    assert script_failed(script_result(), a_page=page(untilAt=6000, console=[WARN_LINE])) == ["input_warn"]


def test_web_smoke_first_difference_names_the_first_tick_that_differs():
    rows = script_rows()
    assert web_smoke.first_difference(rows, list(rows)) is None
    assert web_smoke.first_difference(changed_row(rows, 17, brake_digital=1), rows) == 17
    assert web_smoke.first_difference(rows[:50], rows) == 50  # 長さが違う


def test_web_smoke_probe_script_line_sets_the_window_value():
    line = web_smoke.probe_script({"ticks": SCRIPT_TICKS, "script": SCRIPT_VALUE, "trace_max": 400})
    head = f"window.{web_bridge.PROBE_NAME} = "
    assert line.startswith(head) and line.endswith(";")
    assert json.loads(line[len(head):-1]) == {"ticks": SCRIPT_TICKS, "script": SCRIPT_VALUE, "trace_max": 400}


# --- 偽のコントローラーを差し込んで開く筋書き ---
def pad_rows(lag: int = 1) -> list:
    """予定どおりに見えたときの、tickごとの値。予定の区間の値は、境目から lag tick遅れて見える。押した瞬間は、見えた最初のtickだけ。"""
    rows, previous = [], (0,) * len(QUANTIZED_FIELDS)
    for stage in web_smoke.PAD_STAGES:
        want = web_smoke.pad_expected_row(stage)
        rows += [previous] * lag + [want] * (STAGE - lag)
        previous = want
    press_tick = web_smoke.PAD_PRESS_STAGE * STAGE + lag
    return changed_row(rows, press_tick, pressed=rows[press_tick][FIELD["held"]])


def pad_log(entries=None) -> list:
    entries = [(index + 1, index * STAGE) for index in range(len(web_smoke.PAD_STAGES))] if entries is None else entries
    return [{"t": 1, "type": "log", "text": f"CP_FAKE_PAD stage={stage} tick={tick}"} for stage, tick in entries]


def pad_page(**changes) -> dict:
    return page(**{"untilAt": 9000, "console": pad_log(), **changes})


def pad_sim(rows: list, ticks: int = PAD_TICKS) -> dict:
    """世界の要約の見本。形は世界（Sim）に作らせる（ここで手で組まない）。入力の要約値だけを、渡した列から計算した値にする。"""
    return {**input_reference.sim_summary(None, ticks), "input_digest": input_reference.digest_of(rows)}


def pad_result(rows=None, **changes) -> dict:
    """問題の無い、偽のコントローラーの筋書きの結果。世界の要約は、渡した列から計算する。"""
    rows = pad_rows() if rows is None else rows
    base = {
        "ticks": PAD_TICKS,
        "renders": PAD_TICKS // 2,
        "sim": pad_sim(rows),
        "warmup_ticks": 0,
        "platform": "emscripten",
        "python": "3.14.2",
        "pyxel": "3.0.1",
        "input_source": "adapter",
        "adapter_reads": PAD_TICKS,
        "direct_reads": PAD_TICKS,  # 入力アダプタと同じく、1 tickに1度
        "inputs": trace_report(rows),
    }
    return {**base, **changes}


def pad_failed(res, a_page=None, settle: int = SETTLE) -> list:
    return failed(web_smoke.judge_gamepad(a_page or pad_page(), SHA, res, STAGE, settle))


def stage_names(*numbers) -> list:
    return [f"pad_stage_{number}" for number in numbers]


ALL_STAGES = stage_names(*range(1, len(web_smoke.PAD_STAGES) + 1))


def test_web_smoke_pad_plan_is_the_nine_stages_of_the_request():
    stages = web_smoke.PAD_STAGES
    assert len(stages) == 9 and PAD_TICKS == 9 * STAGE
    assert [stage.pad is None for stage in stages] == [True, False, False, False, False, True, False, False, True]
    assert [stage.pad["mapping"] for stage in stages if stage.pad] == ["standard"] * 4 + [""] * 2
    # 接続するときは、全部0で接続する。値は次の区間で変える。
    for index in (1, 6):
        assert stages[index].pad["buttons"] == {} and stages[index].pad["axes"] == [0, 0, 0, 0]
    assert stages[2].pad["buttons"] == {"7": 0.3}
    assert stages[3].pad["buttons"] == {"7": 1.0, "6": 0.6}
    assert stages[4].pad["buttons"] == {"0": 1.0, "12": 1.0} and stages[4].pad["axes"] == [-1.0, 0, 0, 0]
    assert stages[7].pad["buttons"] == {"6": 0.6, "7": 1.0}


def test_web_smoke_pad_plan_nudges_the_stick_before_it_is_moved():
    # ブラウザ版のランタイムは、接続の後の最初の軸の変化を、Pyxelへ届けない（実測）。先に、わずかに動かしておく。
    stages = web_smoke.PAD_STAGES
    assert 0 < web_smoke.AXIS_NUDGE <= 0.01
    assert stages[2].pad["axes"][0] == web_smoke.AXIS_NUDGE and stages[3].pad["axes"][0] == web_smoke.AXIS_NUDGE
    assert "steer_analog" not in stages[2].expect and "steer_analog" not in stages[3].expect  # この値そのものは、見えない


def test_web_smoke_pad_stages_expect_the_values_of_the_request():
    rows = [web_smoke.pad_expected_row(stage) for stage in web_smoke.PAD_STAGES]
    zero = (0,) * 8
    assert rows[0] == rows[1] == zero  # 区間1、2：全部0
    assert rows[2] == (0, 0, 300, 0, 0, 0, 0, 0)  # 区間3：アクセルのアナログ値が300。アクセルのデジタル値も0
    assert rows[3] == (0, 0, 1000, 0, 600, 0, 0, 0)  # 区間4：アクセルが1000、ブレーキが600
    assert rows[4] == (1000, 0, 0, 1, 0, 0, button_bits(("up", "confirm")), 0)  # 区間5：舵が+1000（左が正）、Aボタン、十字キーの上
    assert rows[5] == rows[6] == rows[8] == zero  # 区間6、9：押したまま切断すると、全部0へ戻る（実測）。区間7：標準でない並びで接続
    assert rows[7] == (0, 0, 0, 1, 0, 1, 0, 0)  # 区間8：標準でない並びのトリガーは、デジタル値へ入る。アナログ値は0


def test_web_smoke_pad_plan_for_the_fake_gamepad_is_plain_json():
    plan = web_smoke.pad_plan(STAGE)
    assert json.loads(json.dumps(plan)) == plan
    assert [entry["until"] for entry in plan] == [STAGE * (index + 1) for index in range(9)]
    assert [entry["pad"] for entry in plan] == [stage.pad for stage in web_smoke.PAD_STAGES]


def test_web_smoke_pad_init_script_is_the_plan_line_then_the_fake_gamepad_then_the_probe_line():
    script = web_smoke.pad_init_script(STAGE, 400)
    lines = script.splitlines()
    assert lines[0] == f"window.{web_smoke.PAD_PLAN_NAME} = {json.dumps(web_smoke.pad_plan(STAGE))};"
    assert lines[-1] == f"window.{web_bridge.PROBE_NAME} = " + json.dumps({"ticks": PAD_TICKS, "trace_max": 400}) + ";"
    assert web_smoke.FAKE_PAD_JS.read_text(encoding="utf-8").strip() in script
    assert "script" not in json.loads(lines[-1].split(" = ", 1)[1].rstrip(";"))  # 台本は渡さない


def test_web_smoke_fake_gamepad_uses_the_names_the_tool_and_the_app_use():
    source = web_smoke.FAKE_PAD_JS.read_text(encoding="utf-8")
    assert f"window.{web_smoke.PAD_PLAN_NAME}" in source  # 予定を置く名前
    assert f"window.{web_bridge.TICK_NAME}" in source  # アプリが置く tick の印
    assert 'const LOG_MARK = "CP_FAKE_PAD";' in source and "${LOG_MARK} stage=${index + 1} tick=${tick}" in source
    assert web_smoke.PAD_LOG.fullmatch("CP_FAKE_PAD stage=3 tick=60").groups() == ("3", "60")
    assert "navigator.getGamepads = " in source
    assert "gamepadconnected" in source and "gamepaddisconnected" in source and "setTimeout" in source


@pytest.mark.parametrize("lag", [0, 1, 2, SETTLE - 1])
def test_web_smoke_clean_gamepad_scenario_passes_with_a_lag_inside_the_settle_ticks(lag):
    assert pad_failed(pad_result(pad_rows(lag))) == []
    assert web_smoke.pad_lag(pad_rows(lag), STAGE) == lag


def test_web_smoke_gamepad_values_that_arrive_after_the_settle_ticks_fail():
    # 判定する最初のtickに、ちょうど見えた形。値は間に合うが、押した瞬間が、区間の頭の外になる。
    assert pad_failed(pad_result(pad_rows(SETTLE))) == [*stage_names(5), "pad_pressed_once"]
    # さらに1 tick遅れると、値が変わる区間（3、4、5、6、8、9）が落ちる。
    assert pad_failed(pad_result(pad_rows(SETTLE + 1))) == [*stage_names(3, 4, 5, 6, 8, 9), "pad_pressed_once"]


@pytest.mark.parametrize("number", range(1, 10))
def test_web_smoke_gamepad_wrong_value_in_a_stage_fails_under_that_stage(number):
    start = (number - 1) * STAGE
    for tick in (start + SETTLE, start + STAGE - 1):  # 判定する最初のtickと、最後のtick
        assert pad_failed(pad_result(changed_row(pad_rows(), tick, steer_digital=-1))) == stage_names(number)


@pytest.mark.parametrize("number", range(1, 10))
def test_web_smoke_gamepad_head_of_each_stage_is_not_judged(number):
    tick = (number - 1) * STAGE + SETTLE - 1  # 判定しない最後のtick
    assert pad_failed(pad_result(changed_row(pad_rows(), tick, steer_digital=-1))) == []


def all_ticks(rows: list, number: int, **values) -> list:
    """予定の区間 number（1始まり）の全tickの値を、名前で書き換えた列。"""
    for tick in range((number - 1) * STAGE, number * STAGE):
        rows = changed_row(rows, tick, **values)
    return rows


def test_web_smoke_gamepad_steer_with_the_wrong_sign_fails_stage_5():
    assert pad_failed(pad_result(all_ticks(pad_rows(), 5, steer_analog=-1000))) == stage_names(5)


def test_web_smoke_gamepad_swapped_triggers_fail_stages_3_and_4():
    rows = all_ticks(pad_rows(), 3, throttle_analog=0, brake_analog=300)
    rows = all_ticks(rows, 4, throttle_analog=600, brake_analog=1000)
    assert pad_failed(pad_result(rows)) == stage_names(3, 4)


def test_web_smoke_gamepad_pyxel_trigger_in_the_digital_value_during_a_direct_read_fails():
    # 直読みができたtickに、Pyxel経由の2値のトリガーがデジタル値へ入った形。
    rows = all_ticks(pad_rows(), 3, throttle_digital=1)
    rows = all_ticks(rows, 4, throttle_digital=1, brake_digital=1)
    assert pad_failed(pad_result(rows)) == stage_names(3, 4)


def test_web_smoke_gamepad_direct_read_that_never_works_fails_stages_3_and_4():
    # 直読みが、いつも「未接続」を返す形（空の枠の見分けの誤りなど）。Pyxel経由の2値のトリガーが、デジタル値へ入る。
    rows = all_ticks(pad_rows(), 3, throttle_analog=0, throttle_digital=1)
    rows = all_ticks(rows, 4, throttle_analog=0, brake_analog=0, throttle_digital=1, brake_digital=1)
    assert pad_failed(pad_result(rows)) == stage_names(3, 4)


def test_web_smoke_gamepad_values_left_after_the_unplug_fail_stages_6_and_9():
    rows = all_ticks(pad_rows(), 6, steer_analog=1000, throttle_digital=1)
    rows = all_ticks(rows, 9, throttle_digital=1, brake_digital=1)
    assert pad_failed(pad_result(rows)) == stage_names(6, 9)


def test_web_smoke_gamepad_pressed_must_stay_empty_in_stages_2_to_4():
    for number in (2, 3, 4):
        in_head = (number - 1) * STAGE + 1  # 区間の頭の、判定しないtickでも見る
        assert pad_failed(pad_result(changed_row(pad_rows(), in_head, pressed=button_bits(("confirm",))))) == ["pad_pressed_quiet"]
    # 区間1と、区間6より後は、見ない（区間の頭の中なら）。
    for number in (1, 6, 7, 8, 9):
        in_head = (number - 1) * STAGE + 1
        assert pad_failed(pad_result(changed_row(pad_rows(), in_head, pressed=button_bits(("confirm",))))) == []


def test_web_smoke_gamepad_confirm_must_be_pressed_on_exactly_one_tick_in_the_head_of_stage_5():
    start = 4 * STAGE
    press = button_bits(("up", "confirm"))
    twice = changed_row(pad_rows(), start + 3, pressed=press)
    assert pad_failed(pad_result(twice)) == ["pad_pressed_once"]
    never = changed_row(pad_rows(), start + 1, pressed=0)
    assert pad_failed(pad_result(never)) == ["pad_pressed_once"]
    only_up = changed_row(pad_rows(), start + 1, pressed=button_bits(("up",)))
    assert pad_failed(pad_result(only_up)) == ["pad_pressed_once"]
    late = changed_row(never, start + SETTLE, pressed=press)  # 区間の頭の外
    assert pad_failed(pad_result(late)) == [*stage_names(5), "pad_pressed_once"]


def test_web_smoke_gamepad_truncated_or_missing_trace_fails_everything_that_needs_it():
    needs_trace = ["trace_complete", "sim_from_trace", *ALL_STAGES, "pad_pressed_quiet", "pad_pressed_once"]
    assert pad_failed(pad_result(inputs=trace_report(pad_rows(), max_changes=4))) == needs_trace
    assert pad_failed(pad_result(inputs=None)) == needs_trace
    assert pad_failed(pad_result(inputs={"changes": [], "truncated": False})) == needs_trace


def test_web_smoke_gamepad_world_must_have_received_the_frames_of_the_trace():
    # 入力の跡から計算し直した入力の要約値が、世界の要約と同じこと。比べるのは、世界の要約の tick と入力の要約値の2項目。
    summary = pad_sim(pad_rows())
    assert pad_failed(pad_result(sim={**summary, "input_digest": 1})) == ["sim_from_trace"]
    assert pad_failed(pad_result(sim={**summary, "tick": PAD_TICKS - 1})) == ["sim_from_trace"]
    # 1 tick分だけ違う入力（判定しないtickの中）を世界が受けていたら、入力の要約値が合わない。
    other = pad_sim(changed_row(pad_rows(), 3, steer_digital=1))
    assert pad_failed(pad_result(sim=other)) == ["sim_from_trace"]


def test_web_smoke_gamepad_world_summary_may_grow_new_items():
    # 世界の要約に項目が足されても、この確かめは落ちない。要約の形を、道具が手で組んで辞書ごと比べない。
    grown = {**pad_sim(pad_rows()), "cars": 1, "fingerprint": "abc"}
    assert pad_failed(pad_result(sim=grown)) == []


@pytest.mark.parametrize("bad", [None, [], "sim", 0, {}, {"tick": PAD_TICKS}, {"input_digest": 1}, [PAD_TICKS, 1]])
def test_web_smoke_gamepad_world_summary_of_another_shape_fails_without_an_error(bad):
    # 世界の要約が辞書でない、2項目が欠けている。例外にせず、この確かめだけが落ちる。
    assert pad_failed(pad_result(sim=bad)) == ["sim_from_trace"]


@pytest.mark.parametrize(
    "changes, names",
    [
        ({"platform": "linux"}, ["platform"]),
        ({"ticks": PAD_TICKS + 1}, ["ticks"]),
        ({"input_source": "script"}, ["input_source"]),
        ({"input_source": None}, ["input_source"]),
        ({"adapter_reads": 2 * PAD_TICKS}, ["adapter_reads"]),
        ({"adapter_reads": 0}, ["adapter_reads"]),
        ({"adapter_reads": None}, ["adapter_reads"]),
        ({"direct_reads": 2 * PAD_TICKS}, ["direct_reads"]),  # 直読みを、1 tickに2度呼んでいる
        ({"direct_reads": 0}, ["direct_reads"]),
        ({"direct_reads": None}, ["direct_reads"]),
    ],
)
def test_web_smoke_gamepad_each_other_deviation_fails_under_its_own_name(changes, names):
    assert pad_failed(pad_result(**changes)) == names


@pytest.mark.parametrize(
    "entries",
    [
        [],
        [(1, 0)],
        [(index + 1, index * STAGE) for index in range(8)],  # 最後の区間へ入っていない
        [(index + 1, index * STAGE + (1 if index == 4 else 0)) for index in range(9)],  # 区間5へ、境目の1 tick後に入った
        [(index + 1, 0) for index in range(9)],  # 全部の区間へ、tick 0で入った（境目のtickが違う）
    ],
)
def test_web_smoke_gamepad_fake_pad_must_enter_every_stage_at_its_boundary(entries):
    assert pad_failed(pad_result(), a_page=pad_page(console=pad_log(entries))) == ["pad_plan"]


def test_web_smoke_gamepad_input_warning_and_python_error_are_reported():
    assert pad_failed(pad_result(), a_page=pad_page(console=[*pad_log(), WARN_LINE])) == ["input_warn"]
    bad = pad_page(failures=[{"t": 9, "kind": "error_overlay", "detail": "Traceback"}])
    assert pad_failed(pad_result(), a_page=bad) == ["error_overlay"]


def test_web_smoke_pad_lag_is_none_when_a_stage_never_shows_its_values():
    assert web_smoke.pad_lag(all_ticks(pad_rows(), 5, steer_analog=-1000), STAGE) is None
    assert web_smoke.pad_lag(pad_rows(0), STAGE) == 0


def test_web_smoke_pad_stage_with_an_unknown_value_name_is_an_error():
    typo = web_smoke.PadStage("typo", None, {"throttle": 300})
    with pytest.raises(ValueError):
        web_smoke.pad_expected_row(typo)


def test_web_smoke_pad_budgets_leave_ticks_to_judge_and_room_in_the_trace():
    assert 0 <= SETTLE < STAGE
    assert BUDGETS["web_input_trace_max"] > len(trace_report(pad_rows())["changes"])
    assert web_smoke.PAD_PRESS_BUTTON in BUTTONS


# --- 回す前の守り。何も開かずに2 ---
def guarded_main(monkeypatch, capsys, argv: list, **budget_changes) -> tuple:
    """道具の値を差し替えて main() を回す。何かを回そうとしたら失敗にする。返すのは (終了コード, 最後の1行)。"""

    def must_not_run(*args, **kwargs):
        pytest.fail("守りを通り抜けて、先へ進んだ")

    monkeypatch.setattr(web_smoke, "load_budgets", lambda: {**BUDGETS, **budget_changes})
    monkeypatch.setattr(web_smoke.shutil, "which", must_not_run)
    monkeypatch.setattr(web_smoke.shutil, "rmtree", must_not_run)
    monkeypatch.setattr(web_smoke, "run", must_not_run)
    monkeypatch.setattr(sys, "argv", ["web_smoke.py", *argv])
    return web_smoke.main(), last_line(capsys)


@pytest.mark.parametrize("settle", [STAGE, STAGE + 5, -1])
def test_web_smoke_pad_stage_without_a_tick_to_judge_is_2_before_anything_is_opened(monkeypatch, capsys, settle):
    # 予定の区間の頭で判定しないtick数が、区間の長さ以上。どの区間も、何も見ずに通ってしまう。
    for argv in (["--only", "gamepad"], []):
        code, line = guarded_main(monkeypatch, capsys, argv, web_pad_settle_ticks=settle)
        assert code == 2 and "reason=pad_stage_too_short" in line and "scenarios=0" in line


def test_web_smoke_missing_fake_gamepad_script_is_2_before_anything_is_opened(monkeypatch, capsys, tmp_path):
    # 偽のコントローラーのスクリプトが無い、読めない。例外で終わらせず（終了コード1）、回り切れない（2）にする。
    monkeypatch.setattr(web_smoke, "FAKE_PAD_JS", tmp_path / "no_such_fake_gamepad.js")
    for argv in (["--only", "gamepad"], []):
        code, line = guarded_main(monkeypatch, capsys, argv)
        assert code == 2 and "reason=no_fake_gamepad" in line and "scenarios=0" in line
    not_text = tmp_path / "fake_gamepad.js"
    not_text.write_bytes(b"\xff\xfe\x00navigator")  # UTF-8として読めない
    monkeypatch.setattr(web_smoke, "FAKE_PAD_JS", not_text)
    code, line = guarded_main(monkeypatch, capsys, ["--only", "gamepad"])
    assert code == 2 and "reason=no_fake_gamepad" in line


def test_web_smoke_missing_fake_gamepad_script_does_not_stop_the_other_scenarios(monkeypatch, capsys, tmp_path):
    # 偽のコントローラーを使わない筋書きだけを回すときは、止まらない（次の確かめの、node があるかまで進む）。
    monkeypatch.setattr(web_smoke, "FAKE_PAD_JS", tmp_path / "no_such_fake_gamepad.js")
    monkeypatch.setattr(web_smoke.shutil, "which", lambda name: None)
    monkeypatch.setattr(sys, "argv", ["web_smoke.py", "--only", "script"])
    assert web_smoke.main() == 2
    assert "reason=no_node" in last_line(capsys)


def test_web_smoke_missing_block_storage_script_is_2_before_anything_is_opened(monkeypatch, capsys, tmp_path):
    # 保存先に触れると例外にするスクリプトが無い、読めない。保存先を止めずに開いて、別の理由で落とさない。回り切れない（2）にする。
    monkeypatch.setattr(web_smoke, "BLOCK_STORAGE_JS", tmp_path / "no_such_block_storage.js")
    for argv in (["--only", "storage_blocked"], []):
        code, line = guarded_main(monkeypatch, capsys, argv)
        assert code == 2 and "reason=no_block_storage" in line and "scenarios=0" in line
    not_text = tmp_path / "block_storage.js"
    not_text.write_bytes(b"\xff\xfe\x00window")  # UTF-8として読めない
    monkeypatch.setattr(web_smoke, "BLOCK_STORAGE_JS", not_text)
    code, line = guarded_main(monkeypatch, capsys, ["--only", "storage_blocked"])
    assert code == 2 and "reason=no_block_storage" in line


def test_web_smoke_missing_block_storage_script_does_not_stop_the_other_scenarios(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(web_smoke, "BLOCK_STORAGE_JS", tmp_path / "no_such_block_storage.js")
    monkeypatch.setattr(web_smoke.shutil, "which", lambda name: None)
    monkeypatch.setattr(sys, "argv", ["web_smoke.py", "--only", "probe"])
    assert web_smoke.main() == 2
    assert "reason=no_node" in last_line(capsys)


def test_web_smoke_script_ticks_shorter_than_the_script_is_2_before_anything_is_opened(monkeypatch, capsys):
    for argv in (["--only", "script"], []):
        code, line = guarded_main(monkeypatch, capsys, argv, web_script_ticks=SCRIPT.total_ticks - 1)
        assert code == 2 and "reason=ticks_shorter_than_script" in line and "scenarios=0" in line


def test_web_smoke_unreadable_script_is_2_before_anything_is_opened(monkeypatch, capsys, tmp_path):
    broken = tmp_path / "script.json"
    broken.write_text('{"segments": []}', encoding="utf-8")
    monkeypatch.setattr(input_reference, "SMOKE_SCRIPT", broken)
    code, line = guarded_main(monkeypatch, capsys, ["--only", "script"])
    assert code == 2 and "reason=script_unreadable" in line


def test_web_smoke_guards_of_one_scenario_do_not_stop_the_others(monkeypatch, capsys):
    # 回さない筋書きの守りでは止まらない。ここでは、次の確かめ（node があるか）まで進むことを見る。
    monkeypatch.setattr(web_smoke, "load_budgets", lambda: {**BUDGETS, "web_pad_settle_ticks": STAGE, "web_script_ticks": 1})
    monkeypatch.setattr(web_smoke.shutil, "which", lambda name: None)
    monkeypatch.setattr(sys, "argv", ["web_smoke.py", "--only", "probe"])
    assert web_smoke.main() == 2
    assert "reason=no_node" in last_line(capsys)


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


def test_fetch_runtime_source_constants_are_github_and_npm():
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


# --- ランタイムの写しの取得（一時の置き場と、偽の取得の関数で通す） ---
PYXEL_FILES = {"pyxel.js": b"pyxel-js", "images/logo.png": b"png-bytes"}
PACKAGE_FILES = {"pyodide.js": b"pyodide-js", "pyodide.asm.wasm": b"wasm-bytes"}


def make_tgz(members: dict) -> bytes:
    """npmのtgzと同じ並び（package/ の下）の、小さなtgz。"""
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo("package/" + name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class FakeSource:
    """取得の関数の代わり。呼ばれたURLを覚え、決めたバイト列を返す。知らないURLは、取得できない扱いにする。"""

    def __init__(self, served: dict) -> None:
        self.served = dict(served)
        self.calls = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        if url not in self.served:
            raise fetch_runtime.FetchError(f"{url}: not served")
        return self.served[url]


class Runtime:
    """小さな偽のランタイム。照合用の一覧、置き場、取得元を、tmp_path の下に持つ。"""

    def __init__(self, tmp_path) -> None:
        self.tgz = make_tgz(PACKAGE_FILES)
        self.sums_path = tmp_path / "SHA256SUMS"
        self.vendor = tmp_path / "cache" / "vendor"
        self.mirror = tmp_path / "cache" / "mirror"
        lines = [f"{hashlib.sha256(data).hexdigest()}  {fetch_runtime.PYXEL_DIR}{name}" for name, data in PYXEL_FILES.items()]
        lines.append(f"{hashlib.sha256(self.tgz).hexdigest()}  {fetch_runtime.PYODIDE_TGZ}")
        lines += [f"{hashlib.sha256(data).hexdigest()}  {fetch_runtime.PYODIDE_DIR}{name}" for name, data in PACKAGE_FILES.items()]
        self.sums_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.served = {fetch_runtime.PYXEL_URL + name: data for name, data in PYXEL_FILES.items()}
        self.served[fetch_runtime.PYODIDE_URL] = self.tgz

    def main(self, source, *argv) -> int:
        return fetch_runtime.main(list(argv), sums_path=self.sums_path, vendor=self.vendor, mirror=self.mirror, downloader=source)


def test_fetch_runtime_fetches_from_the_two_sources_only_and_builds_the_mirror(tmp_path, capsys):
    runtime = Runtime(tmp_path)
    source = FakeSource(runtime.served)
    assert runtime.main(source) == 0
    assert "fetched=3 " in last_line(capsys)
    assert len(source.calls) == 3  # Pyxelの側の2ファイルと、Pyodideのtgz
    assert all(url.startswith(fetch_runtime.PYXEL_URL) or url == fetch_runtime.PYODIDE_URL for url in source.calls)
    assert (runtime.mirror / "kitao.dev/pyxel/3.0.1/pyxel.js").read_bytes() == b"pyxel-js"
    assert (runtime.mirror / "kitao.dev/pyxel/3.0.1/images/logo.png").read_bytes() == b"png-bytes"
    assert (runtime.mirror / "kitao.dev/pyxel/pyodide/v314.0.7/pyodide.asm.wasm").read_bytes() == b"wasm-bytes"


def test_fetch_runtime_does_not_fetch_again_when_everything_matches(tmp_path, capsys):
    runtime = Runtime(tmp_path)
    assert runtime.main(FakeSource(runtime.served)) == 0
    again = FakeSource(runtime.served)
    assert runtime.main(again) == 0
    assert again.calls == []
    assert "fetched=0 " in last_line(capsys)


def test_fetch_runtime_rebuilds_what_it_can_without_the_network(tmp_path, capsys):
    runtime = Runtime(tmp_path)
    assert runtime.main(FakeSource(runtime.served)) == 0
    (runtime.mirror / "kitao.dev/pyxel/3.0.1/pyxel.js").unlink()  # 組み立てた側が欠けた
    (runtime.vendor / fetch_runtime.PYODIDE_DIR / "pyodide.js").unlink()  # tgzから取り出した側が欠けた
    offline = FakeSource({})
    assert runtime.main(offline) == 0
    assert offline.calls == []
    assert (runtime.mirror / "kitao.dev/pyxel/3.0.1/pyxel.js").read_bytes() == b"pyxel-js"
    capsys.readouterr()


def test_fetch_runtime_fetch_failure_is_2(tmp_path, capsys):
    runtime = Runtime(tmp_path)
    without_tgz = {url: data for url, data in runtime.served.items() if url != fetch_runtime.PYODIDE_URL}
    assert runtime.main(FakeSource(without_tgz)) == 2
    assert "reason=fetch_failed" in last_line(capsys)
    assert not runtime.mirror.exists()


def test_fetch_runtime_cut_off_tgz_is_2_not_a_traceback(tmp_path, capsys):
    runtime = Runtime(tmp_path)
    cut = {**runtime.served, fetch_runtime.PYODIDE_URL: runtime.tgz[: len(runtime.tgz) // 2]}
    assert runtime.main(FakeSource(cut)) == 2
    assert "reason=fetch_failed" in last_line(capsys)


def test_fetch_runtime_wrong_bytes_after_the_fetch_are_1(tmp_path, capsys):
    runtime = Runtime(tmp_path)
    wrong = {**runtime.served, fetch_runtime.PYXEL_URL + "pyxel.js": b"tampered"}
    assert runtime.main(FakeSource(wrong)) == 1
    line = last_line(capsys)
    assert "reason=checksum_mismatch" in line and "mismatched=1 " in line
    assert not runtime.mirror.exists()  # 照合が合わない物からは、組み立てない


def test_fetch_runtime_other_tgz_with_other_contents_is_1(tmp_path, capsys):
    runtime = Runtime(tmp_path)
    other = make_tgz({**PACKAGE_FILES, "pyodide.js": b"other"})
    assert runtime.main(FakeSource({**runtime.served, fetch_runtime.PYODIDE_URL: other})) == 1
    assert "reason=checksum_mismatch" in last_line(capsys)


def test_fetch_runtime_check_never_fetches(tmp_path, capsys):
    runtime = Runtime(tmp_path)
    source = FakeSource(runtime.served)
    assert runtime.main(source, "--check") == 2
    assert "reason=missing" in last_line(capsys)
    assert source.calls == [] and not runtime.vendor.exists()


def test_fetch_runtime_unwritable_cache_is_2_with_a_last_line(tmp_path, capsys):
    runtime = Runtime(tmp_path)
    runtime.vendor.parent.mkdir(parents=True)
    runtime.vendor.write_text("not a directory", encoding="utf-8")  # 置き場の名前が、ファイルでふさがっている
    assert runtime.main(FakeSource(runtime.served)) == 2
    assert "reason=io_error" in last_line(capsys)


@pytest.mark.parametrize(
    "error",
    [http.client.IncompleteRead(b"half"), urllib.error.URLError("no route"), TimeoutError("slow"), ValueError("bad url")],
)
def test_fetch_runtime_download_turns_every_network_error_into_fetch_error(monkeypatch, error):
    # 途中で切れた接続は IncompleteRead（HTTPException の子。OSError ではない）になる。
    def broken(url, timeout):
        raise error

    monkeypatch.setattr(fetch_runtime.urllib.request, "urlopen", broken)
    with pytest.raises(fetch_runtime.FetchError):
        fetch_runtime.download(fetch_runtime.PYODIDE_URL)
