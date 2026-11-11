"""直読み。ブラウザ版で、Pyxelをはさまずに、ブラウザのGamepad APIからトリガーの値を読む（cp_app の中だけで使う）。

Pyxel経由では、ブラウザ版のトリガーが0か最大かの2値でしか届かない。標準の並びのコントローラーでだけ、ここで読む。
このモジュールは js をimportしない。ブラウザの機能（js のモジュール）は引数で受ける。js が None（デスクトップ版）なら、いつも None。
見るのは、コントローラーの枠（navigator.getGamepads() が返す並び）を先頭から見て、最初の空でない所だけ。
Pyxelの「ゲームパッド1」と同じコントローラーを見るため。そこが標準の並びでなければ、直読みしない。

ふつうに起きること（未接続、途中の切断、標準でない並び、ボタンの不足、value が数でないボタン）は、None を返すだけ。警告も出さない。
読めない場合（getGamepads が無い、呼ぶと例外になる、値を読む途中で例外になる）は、呼び出しから値の読み取りまでをまとめて
捕まえて None を返し、最初の1度だけ、印（WARN_MARK）の付いた警告をコンソールへ出す。
捕まえる範囲が広いので、読み方の誤りは「未接続」と同じ見え方になる。煙テストは、この警告が0件であることを見る。

空のコントローラーの枠は、ブラウザ版のPythonからは None ではなく jsnull（型の名が JsNull）に見える（Pyodide 314.0.7 での実測。
JavaScriptの null が jsnull、undefined が None）。属性を読むと AttributeError になる。
空かどうかは is_empty_slot() だけで決め、空でないと見た所は、属性をそのまま読む（getattr の既定や hasattr で包まない）。
見分けを誤ると、属性を読む所で例外になり、上の警告が出る。黙って「未接続」に見える形にしない。
"""
import math

WARN_MARK = "CP_INPUT_WARN"  # 警告の行の頭の印。道具（tools/web_smoke.py）も、ここから読む
STANDARD_MAPPING = "standard"  # 標準の並び（Gamepad APIの mapping）
TRIGGER_LEFT, TRIGGER_RIGHT = 6, 7  # 標準の並びでの、左トリガーと右トリガーのボタンの番号
MIN_BUTTONS = 8  # 直読みに要る、ボタンの数
JS_NULL_TYPE_NAME = "JsNull"  # JavaScriptの null が、ブラウザ版のPythonで見える物の、型の名


def is_empty_slot(pad) -> bool:
    """コントローラーの枠が空か。undefined（None）か、null（jsnull）。"""
    return pad is None or type(pad).__name__ == JS_NULL_TYPE_NAME


def _number(value):
    """数なら小数にして返す。数でなければ None。bool、NaN、無限大は、数に入れない。"""
    if type(value) not in (int, float):  # JavaScriptの 1.0 は、整数の 1 で届く
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def read_triggers(js):
    """(左トリガー, 右トリガー) の値を返す。直読みができなければ None。例外は捕まえない（捕まえるのは TriggerReader）。"""
    pads = js.navigator.getGamepads()
    for index in range(pads.length):
        pad = pads[index]
        if is_empty_slot(pad):
            continue
        # 最初の空でない所だけを見る。後ろの枠は見ない。
        if pad.mapping != STANDARD_MAPPING:
            return None
        buttons = pad.buttons
        if buttons.length < MIN_BUTTONS:
            return None
        left, right = _number(buttons[TRIGGER_LEFT].value), _number(buttons[TRIGGER_RIGHT].value)
        if left is None or right is None:
            return None
        return left, right
    return None  # 未接続（コントローラーの枠が全部空か、0個）


class TriggerReader:
    """直読みの口。read() を、1 tickに1度だけ呼ぶ。"""

    def __init__(self, js) -> None:
        self._js = js  # ブラウザの機能（js のモジュール）。デスクトップ版では None
        self.warned = False  # 警告を出したか。出すのは、最初の1度だけ
        # read() を呼んだ回数。デスクトップ版でも数える。検証が、1 tickに1度だけ呼ばれていること
        # （台本のときは呼ばれていないこと）を見るのに使う。
        self.reads = 0

    def read(self):
        """(左トリガー, 右トリガー) か None。例外にしない。"""
        self.reads += 1
        if self._js is None:
            return None
        try:
            return read_triggers(self._js)
        except Exception as exc:  # noqa: BLE001 - 埋め込み先が入力を許していない、など。遊べる状態を保つ
            if not self.warned:
                self.warned = True
                self._js.console.warn(f"{WARN_MARK} direct trigger read failed: {type(exc).__name__}: {exc}")
            return None
