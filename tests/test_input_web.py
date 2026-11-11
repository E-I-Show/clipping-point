"""直読み（cp_app.input_web）のテスト。ブラウザの機能（js）の代わりに、偽の実装を渡す。

偽の js は、ブラウザ版のPythonでの見え方（Pyodide 314.0.7 での実測）に合わせてある。
  コントローラーの枠の並び：.length と添字で読む。範囲の外の添字は IndexError
  空の枠（JavaScriptの null）：型の名が JsNull の物。None ではない。属性を読むと AttributeError
  無い値（JavaScriptの undefined）：None
  数：JavaScriptの 1.0 は整数の 1、0.6 は小数で届く
実物のブラウザでの読み方は、道具 web-smoke の筋書き gamepad が、偽のコントローラーを差し込んで見る。
"""
import pytest

from cp_app import input_web
from cp_app.input_web import TriggerReader

NAN, INF = float("nan"), float("inf")


class JsNull:
    """JavaScriptの null の代わり。型の名を、実物（pyodide.ffi の JsNull）と同じにする。属性は無い。"""

    def __bool__(self) -> bool:
        return False


JS_NULL = JsNull()


class FakeArray:
    """JavaScriptの配列の代わり。"""

    def __init__(self, items) -> None:
        self._items = list(items)
        self.length = len(self._items)

    def __getitem__(self, index):
        return self._items[index]


class FakeButton:
    def __init__(self, value) -> None:
        self.value = value
        self.pressed = False


class FakePad:
    """接続中のコントローラーの代わり。buttons は、ボタン6と7の値（ほかは0）。"""

    def __init__(self, mapping="standard", left=0.0, right=0.0, count=17) -> None:
        self.mapping = mapping
        self.connected = True
        values = [0.0] * count
        if count > 6:
            values[6] = left
        if count > 7:
            values[7] = right
        self.buttons = FakeArray(FakeButton(value) for value in values)


class FakeConsole:
    def __init__(self) -> None:
        self.warnings = []

    def warn(self, text) -> None:
        self.warnings.append(text)


class FakeNavigator:
    """getGamepads が、決めた並びを返す。呼ばれた回数を覚える。"""

    def __init__(self, slots) -> None:
        self.slots = slots
        self.calls = 0

    def getGamepads(self):  # noqa: N802 - ブラウザの名前のまま
        self.calls += 1
        if isinstance(self.slots, Exception):
            raise self.slots
        return FakeArray(self.slots)


class NavigatorWithoutGamepads:
    """Gamepad APIを持たないブラウザ。"""


class FakeJs:
    def __init__(self, slots=(), navigator=None) -> None:
        self.navigator = navigator if navigator is not None else FakeNavigator(slots)
        self.console = FakeConsole()


def read(slots):
    """1度だけ読む。返すのは (結果, 警告の行の一覧)。"""
    js = FakeJs(slots)
    return TriggerReader(js).read(), js.console.warnings


EMPTY4 = [JS_NULL, JS_NULL, JS_NULL, JS_NULL]


# --- 標準の並び ---
def test_input_web_standard_pad_gives_left_and_right_trigger_values():
    assert read([FakePad(left=0.6, right=0.3), JS_NULL, JS_NULL, JS_NULL]) == ((0.6, 0.3), [])


def test_input_web_whole_numbers_arrive_as_integers_and_become_floats():
    # JavaScriptの 1.0 は、整数の 1 で届く。
    result, warnings = read([FakePad(left=0, right=1)])
    assert result == (0.0, 1.0) and warnings == []
    assert all(type(value) is float for value in result)


def test_input_web_reads_the_first_slot_that_is_not_empty():
    # Pyxelの「ゲームパッド1」と同じコントローラーを見る。空の枠は飛ばす。
    assert read([JS_NULL, FakePad(left=0.25, right=0.75), JS_NULL, JS_NULL]) == ((0.25, 0.75), [])
    assert read([None, JS_NULL, FakePad(left=0.5, right=0.5)]) == ((0.5, 0.5), [])


def test_input_web_only_the_first_pad_is_looked_at():
    # 最初の空でない所が標準の並びでなければ、後ろに標準の並びがあっても、直読みしない。
    assert read([FakePad(mapping=""), FakePad(left=0.6, right=1.0)]) == (None, [])
    assert read([FakePad(left=0.1, right=0.2), FakePad(left=0.9, right=0.9)]) == ((0.1, 0.2), [])


# --- ふつうに起きること。None を返すだけで、警告も出さない ---
@pytest.mark.parametrize("slots", [EMPTY4, [], [None], [None, JS_NULL], [JS_NULL]])
def test_input_web_no_pad_connected_is_none_without_a_warning(slots):
    assert read(slots) == (None, [])


@pytest.mark.parametrize("mapping", ["", "xr-standard", "STANDARD", None, JS_NULL])
def test_input_web_pad_that_is_not_standard_is_none_without_a_warning(mapping):
    assert read([FakePad(mapping=mapping, left=0.6, right=1.0)]) == (None, [])


@pytest.mark.parametrize("count", [0, 2, 6, 7])
def test_input_web_pad_with_too_few_buttons_is_none_without_a_warning(count):
    assert read([FakePad(count=count)]) == (None, [])


def test_input_web_pad_with_exactly_eight_buttons_is_read():
    assert read([FakePad(left=0.4, right=0.2, count=8)]) == ((0.4, 0.2), [])


@pytest.mark.parametrize("bad", ["0.5", None, JS_NULL, True, NAN, INF, -INF, [0.5]])
def test_input_web_button_value_that_is_not_a_number_is_none_without_a_warning(bad):
    assert read([FakePad(left=bad, right=0.5)]) == (None, [])
    assert read([FakePad(left=0.5, right=bad)]) == (None, [])


def test_input_web_pad_unplugged_in_the_middle_goes_back_to_none():
    js = FakeJs([FakePad(left=0.6, right=1.0), JS_NULL, JS_NULL, JS_NULL])
    reader = TriggerReader(js)
    assert reader.read() == (0.6, 1.0)
    js.navigator.slots = EMPTY4  # 押したまま切断
    assert reader.read() is None
    js.navigator.slots = [FakePad(left=0.0, right=0.3), JS_NULL, JS_NULL, JS_NULL]  # つなぎ直した
    assert reader.read() == (0.0, 0.3)
    assert js.console.warnings == []


def test_input_web_values_are_passed_as_they_are():
    # 範囲をそろえるのは入力アダプタ。ここでは、読んだ値をそのまま返す。
    assert read([FakePad(left=1.5, right=-0.25)]) == ((1.5, -0.25), [])


# --- 読めない場合。None を返し、最初の1度だけ警告を出す ---
def test_input_web_browser_without_get_gamepads_warns_once():
    js = FakeJs(navigator=NavigatorWithoutGamepads())
    reader = TriggerReader(js)
    assert [reader.read() for _ in range(5)] == [None] * 5
    assert len(js.console.warnings) == 1
    assert js.console.warnings[0].startswith(input_web.WARN_MARK + " ")
    assert "AttributeError" in js.console.warnings[0]


def test_input_web_get_gamepads_that_raises_warns_once():
    # 埋め込み先が入力を許していない。遊べる状態を保つ。
    js = FakeJs(RuntimeError("SecurityError: gamepad access is disabled"))
    reader = TriggerReader(js)
    assert [reader.read() for _ in range(3)] == [None] * 3
    assert len(js.console.warnings) == 1 and "SecurityError" in js.console.warnings[0]
    assert js.navigator.calls == 3  # 読むのは続ける。警告だけ、最初の1度


def test_input_web_error_in_the_middle_of_the_read_warns_once():
    class BrokenPad:
        mapping = "standard"

        @property
        def buttons(self):
            raise RuntimeError("lost the pad")

    js = FakeJs([BrokenPad()])
    reader = TriggerReader(js)
    assert reader.read() is None and reader.read() is None
    assert len(js.console.warnings) == 1 and "lost the pad" in js.console.warnings[0]
    assert reader.warned is True


def test_input_web_reading_recovers_after_a_failed_read():
    js = FakeJs(RuntimeError("not yet"))
    reader = TriggerReader(js)
    assert reader.read() is None
    js.navigator.slots = [FakePad(left=0.2, right=0.4)]
    assert reader.read() == (0.2, 0.4)
    assert len(js.console.warnings) == 1


def test_input_web_empty_slot_that_is_not_recognised_ends_in_a_warning_not_in_silence():
    # 空の枠の見え方が変わって、見分けられなくなった場合。黙って「未接続」に見えるのではなく、属性を読む所で例外になり、警告が出る。
    class OtherNull:
        pass

    result, warnings = read([OtherNull(), OtherNull()])
    assert result is None
    assert len(warnings) == 1 and warnings[0].startswith(input_web.WARN_MARK)


def test_input_web_empty_slot_is_told_by_none_or_the_type_name_only():
    assert input_web.is_empty_slot(None) is True
    assert input_web.is_empty_slot(JS_NULL) is True
    assert input_web.JS_NULL_TYPE_NAME == "JsNull"
    for present in (FakePad(), FakeArray([]), 0, "", False, object()):
        assert input_web.is_empty_slot(present) is False  # 偽に見える値でも、空とは見なさない


# --- デスクトップ版 ---
def test_input_web_desktop_has_no_js_and_always_gives_none():
    reader = TriggerReader(None)
    assert [reader.read() for _ in range(3)] == [None] * 3
    assert reader.warned is False


# --- 呼ぶ回数と、印 ---
def test_input_web_one_read_asks_the_browser_once():
    js = FakeJs([FakePad(left=0.6, right=0.3)])
    reader = TriggerReader(js)
    for expected in (1, 2, 3):
        reader.read()
        assert js.navigator.calls == expected


def test_input_web_counts_its_reads_whatever_the_result_is():
    # 検証が「1 tickに1度」「台本のときは呼ばない」を見るための回数。値が読めても、未接続でも、例外でも数える。
    for slots in ([FakePad(left=0.6, right=0.3)], EMPTY4, [FakePad(mapping="")], RuntimeError("no gamepad access")):
        reader = TriggerReader(FakeJs(slots))
        assert reader.reads == 0
        for expected in (1, 2, 3):
            reader.read()
            assert reader.reads == expected


def test_input_web_counts_its_reads_on_the_desktop_too():
    # デスクトップ版（js が None）は、値を返さないが、呼んだ回数は数える。道具 run が、この回数を照らす。
    reader = TriggerReader(None)
    assert reader.reads == 0
    for expected in (1, 2, 3):
        assert reader.read() is None
        assert reader.reads == expected


def test_input_web_warn_mark_is_a_plain_ascii_word():
    # 印は、道具（tools/web_smoke.py）がコンソールの行から探す。
    assert input_web.WARN_MARK == "CP_INPUT_WARN"
    assert input_web.WARN_MARK.isascii() and input_web.WARN_MARK.replace("_", "").isalnum()


def test_input_web_standard_layout_constants():
    assert (input_web.TRIGGER_LEFT, input_web.TRIGGER_RIGHT, input_web.MIN_BUTTONS) == (6, 7, 8)
    assert input_web.STANDARD_MAPPING == "standard"
