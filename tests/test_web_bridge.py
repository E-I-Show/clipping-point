"""ブラウザとの橋（cp_app.web_bridge）のテスト。ブラウザの機能（js）の代わりに、偽の実装を渡す。

実物のブラウザで値が渡ることは、道具 web-smoke（`python3 tools/web_smoke.py`）の筋書き probe が見る。
"""
import json
import sys

import pytest

from cp_app import web_bridge

JS_NULL = object()  # JavaScriptの null の代わり。Pyodideでは None と別の物になる


class FakeJSON:
    """js.JSON の代わり。undefined（Pythonから見ると None）には、undefined を返す。"""

    @staticmethod
    def stringify(value):
        if value is None:
            return None
        return "null" if value is JS_NULL else json.dumps(value)


class FakeConsole:
    def __init__(self) -> None:
        self.lines = []

    def log(self, text):
        self.lines.append(text)


class FakeJs:
    """js のモジュールの代わり。window に置いた値を、属性として持つ。置いていない名前は AttributeError になる。"""

    def __init__(self, **window) -> None:
        self.JSON = FakeJSON()
        self.console = FakeConsole()
        for name, value in window.items():
            setattr(self, name, value)


def test_web_bridge_reads_ticks_and_warmup():
    probe = web_bridge.read_probe(FakeJs(CP_PROBE={"ticks": 660, "warmup_ticks": 60}))
    assert probe == web_bridge.Probe(ticks=660, warmup_ticks=60)


def test_web_bridge_warmup_defaults_to_zero():
    assert web_bridge.read_probe(FakeJs(CP_PROBE={"ticks": 120})) == web_bridge.Probe(ticks=120, warmup_ticks=0)


def test_web_bridge_no_value_means_normal_start():
    # 出荷するHTMLをそのまま開いたとき。window に値が無い。
    assert web_bridge.read_probe(FakeJs()) is None


def test_web_bridge_undefined_and_null_mean_normal_start():
    assert web_bridge.read_probe(FakeJs(CP_PROBE=None)) is None
    assert web_bridge.read_probe(FakeJs(CP_PROBE=JS_NULL)) is None


@pytest.mark.parametrize(
    "value",
    [
        [600],
        "600",
        600,
        {},
        {"ticks": "600"},
        {"ticks": 600.0},
        {"ticks": True},
        {"ticks": 0},
        {"ticks": -5},
        {"ticks": 600, "warmup_ticks": 600},
        {"ticks": 600, "warmup_ticks": -1},
        {"ticks": 600, "warmup_ticks": 1.5},
        {"ticks": 600, "frames": 300},
    ],
)
def test_web_bridge_wrong_shape_is_an_error(value):
    # 黙って普通に起動しない。煙テストが完了の合図を待ち続けるため。
    with pytest.raises(ValueError):
        web_bridge.read_probe(FakeJs(CP_PROBE=value))


def test_web_bridge_desktop_has_no_js():
    assert web_bridge.browser_js("linux") is None
    assert web_bridge.browser_js(sys.platform) is None  # テストはデスクトップ版のPythonで回る
    assert web_bridge.read_probe(None) is None


def test_web_bridge_browser_js_returns_the_js_module_on_the_web(monkeypatch):
    fake = FakeJs()
    monkeypatch.setitem(sys.modules, "js", fake)
    assert web_bridge.browser_js(web_bridge.WEB_PLATFORM) is fake
    assert web_bridge.browser_js("linux") is None


def test_web_bridge_emits_one_result_line_then_the_done_mark():
    js = FakeJs()
    result = {"ticks": 660, "sim": {"tick": 660}, "perf": {"updates_per_s": 60.0}}
    web_bridge.emit_result(js, result)
    assert len(js.console.lines) == 2
    head, _, body = js.console.lines[0].partition(" ")
    assert head == web_bridge.RESULT_MARK
    assert json.loads(body) == result
    assert js.console.lines[1] == web_bridge.DONE_MARK


def test_web_bridge_names_are_plain_ascii_words():
    # 名前は、道具（tools/web_smoke.py）がスクリプトと正規表現に、そのまま埋め込む。
    for name in (web_bridge.PROBE_NAME, web_bridge.RESULT_MARK, web_bridge.DONE_MARK):
        assert name.isascii() and name.replace("_", "").isalnum()
