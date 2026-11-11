"""ブラウザ版の煙テストの判定（tools/web_smoke.py）と、ランタイムの写しの取得と照合（tools/web/fetch_runtime.py）のテスト。

ブラウザは開かない。ブラウザの実行役（tools/web/webrun.js）が書く結果の形を、判定の関数に直に与える。
ネットワークも使わない。取得の道は、一時の置き場（tmp_path）と偽の取得の関数で通す。
実物のブラウザを通した確かめは、道具 web-smoke と selftest-break が見る。
"""
import hashlib
import http.client
import io
import json
import sys
import tarfile
import urllib.error

import pytest

import web_smoke
from conftest import ROOT
from cp_app import web_bridge

fetch_runtime = web_smoke.fetch_runtime  # tools/web/ の中。web_smoke が読み込んだものを使う
SHA = "a" * 64
BUDGETS = json.loads((ROOT / "tools" / "budgets.json").read_text(encoding="utf-8"))
TOLERANCE = BUDGETS["web_renders_tolerance"]
TICKS, WARMUP = 660, 60
RENDERS, MEASURED_RENDERS = TICKS // 2, (TICKS - WARMUP) // 2


def page(**changes) -> dict:
    """問題の無い、ブラウザの実行役の結果。"""
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


def last_line(capsys) -> str:
    return capsys.readouterr().out.strip().splitlines()[-1]


# --- 何も渡さずに開く筋書き ---
def test_web_smoke_clean_shipped_page_passes():
    assert failed(web_smoke.judge_shipped(page(), SHA)) == []


def test_web_smoke_blank_canvas_fails():
    assert failed(web_smoke.judge_shipped(page(canvas={"ink": 0}), SHA)) == ["canvas_ink"]
    assert failed(web_smoke.judge_shipped(page(canvas=None), SHA)) == ["canvas_ink"]


def test_web_smoke_page_that_never_started_fails():
    assert "started" in failed(web_smoke.judge_shipped(page(clickedAt=None), SHA))
    not_initialized = {"overlayText": None, "hasFatalError": False, "initialized": False}
    assert failed(web_smoke.judge_shipped(page(state=not_initialized), SHA)) == ["started"]
    assert failed(web_smoke.judge_shipped(page(state=None), SHA)) == ["started"]  # 状態を読めなかった


@pytest.mark.parametrize("kind", list(web_smoke.FAILURE_KINDS))
def test_web_smoke_each_failure_kind_fails_under_its_own_name(kind):
    bad = page(failures=[{"t": 5, "kind": kind, "detail": "Traceback (most recent call last):\nRuntimeError: planted"}])
    assert failed(web_smoke.judge_shipped(bad, SHA)) == [kind]


def test_web_smoke_unresponsive_page_is_a_failure_kind():
    assert "unresponsive" in web_smoke.FAILURE_KINDS


def test_web_smoke_unknown_failure_kind_is_not_ignored():
    bad = page(failures=[{"t": 5, "kind": "something_new", "detail": "x"}])
    assert failed(web_smoke.judge_shipped(bad, SHA)) == ["other_failure"]


def test_web_smoke_other_html_bytes_fail():
    assert failed(web_smoke.judge_shipped(page(htmlSha256="b" * 64), SHA)) == ["html_bytes"]


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
