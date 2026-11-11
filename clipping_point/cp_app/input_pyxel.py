"""入力アダプタ。Pyxelの入力を読んで、入力フレームを作る（cp_app の中だけで使う）。

このモジュールは pyxel をimportしない。Pyxel（のモジュール）は引数で受ける。テストから偽の実装で確かめるため。
値の範囲をそろえるだけにする。遊びの除去と応答カーブは入れない（操作補正に置く）。
読み方は、ボタンとキーが btn（押している）と btnp（押した瞬間。引数は付けない）、軸が btnv。
取り違えると、Pyxelの中で落ちる（軸のキーを btn で読む、ボタンのキーを btnv で読む）。
舵は左が正。Pyxelの左スティックの軸は右が正なので、ここで符号を反転する。
「押した瞬間」は btnp で読む。前のtickとの差からは作らない（1回の更新の中で押して離す、短い押しを落とさないため）。
割り当ては、Pyxelの定数の名前（文字列）の表で持つ。作るとき（起動時）に、全部の名前を引く。無い名前は、そこで落ちる。
割り当ての元は、正本の「操作・HUD・サウンド」の操作の表。Esc（ポーズと戻る）とメニュー操作は、設計と細目で足した分。
ペダルの割り当ての切り替え（BUTTON、R-STICK）は、まだ無い。いまは TRIGGER の形だけ（読み方は段1 区切り4で足す）。
"""
from cp_core.input_frame import InputFrame

AXIS_MAX = 32767  # Pyxelが渡す軸の値の最大（スティックは −32768〜32767、トリガーは 0〜32767）

# 軸のキー。btnv で読む。
STEER_AXIS = "GAMEPAD1_AXIS_LEFTX"  # 右が正で届く
THROTTLE_AXIS = "GAMEPAD1_AXIS_TRIGGERRIGHT"
BRAKE_AXIS = "GAMEPAD1_AXIS_TRIGGERLEFT"
# ボタンとキー。btn と btnp で読む。同じキーが2つの値に入る所がある（矢印の左右は舵とメニュー、Z はアクセルと決定）。
STEER_LEFT_KEYS = ("KEY_LEFT", "GAMEPAD1_BUTTON_DPAD_LEFT")
STEER_RIGHT_KEYS = ("KEY_RIGHT", "GAMEPAD1_BUTTON_DPAD_RIGHT")
THROTTLE_KEYS = ("KEY_Z", "GAMEPAD1_BUTTON_A")
BRAKE_KEYS = ("KEY_X", "GAMEPAD1_BUTTON_B")
# 入力フレームのボタンの名 → キー。どれか1つでも押していれば、押している。
BUTTON_KEYS = {
    "shift_up": ("KEY_S", "GAMEPAD1_BUTTON_X"),
    "shift_down": ("KEY_A", "GAMEPAD1_BUTTON_Y"),
    "view": ("KEY_C", "GAMEPAD1_BUTTON_BACK"),
    "pause": ("KEY_RETURN", "KEY_ESCAPE", "GAMEPAD1_BUTTON_START"),
    "up": ("KEY_UP", "GAMEPAD1_BUTTON_DPAD_UP"),
    "down": ("KEY_DOWN", "GAMEPAD1_BUTTON_DPAD_DOWN"),
    "left": ("KEY_LEFT", "GAMEPAD1_BUTTON_DPAD_LEFT"),
    "right": ("KEY_RIGHT", "GAMEPAD1_BUTTON_DPAD_RIGHT"),
    "confirm": ("KEY_Z", "KEY_RETURN", "GAMEPAD1_BUTTON_A", "GAMEPAD1_BUTTON_START"),
    "back": ("KEY_X", "KEY_ESCAPE", "GAMEPAD1_BUTTON_B"),
}


def _clamp(value: float, low: float, high: float) -> float:
    return low if value < low else high if value > high else value


class PyxelInput:
    """Pyxelから入力フレームを作る。pyxel は、Pyxelのモジュール（テストでは偽の実装）。"""

    def __init__(self, pyxel) -> None:
        self._btn, self._btnp, self._btnv = pyxel.btn, pyxel.btnp, pyxel.btnv

        def codes(names: tuple) -> tuple:
            return tuple(getattr(pyxel, name) for name in names)  # 無い名前は、ここ（起動時）で AttributeError

        self._steer_axis, self._throttle_axis, self._brake_axis = codes((STEER_AXIS, THROTTLE_AXIS, BRAKE_AXIS))
        self._steer_left, self._steer_right = codes(STEER_LEFT_KEYS), codes(STEER_RIGHT_KEYS)
        self._throttle, self._brake = codes(THROTTLE_KEYS), codes(BRAKE_KEYS)
        self._buttons = tuple((name, codes(keys)) for name, keys in BUTTON_KEYS.items())
        groups = (self._steer_left, self._steer_right, self._throttle, self._brake, *(keys for _, keys in self._buttons))
        # 1 tickに、同じキーを2度読まない。読むキーを、重なりを除いて並べておく。
        self._keys = tuple(dict.fromkeys(code for group in groups for code in group))
        self.reads = 0  # read() を呼んだ回数。検証が、1 tickに1度だけ呼ばれていることを見るのに使う

    def read(self, is_web: bool, direct) -> InputFrame:
        """入力フレームを1つ作る。1 tickに1度だけ呼ぶ。

        is_web は、ブラウザ版かどうか。direct は、直読みの結果（左トリガー, 右トリガー）。直読みができなければ None。
        トリガーの読み方は3通り。
          デスクトップ版：Pyxelの軸の値を 0〜1 に直して、アナログ値に入れる。
          ブラウザ版で、直読みができた：直読みの値（左がブレーキ、右がアクセル）を 0〜1 に丸めて、アナログ値に入れる。
            Pyxel経由のトリガーは読まない（2値で届く。デジタル値へ入れると、アナログで踏んでいるのに、デジタル操作と見なされる）。
          ブラウザ版で、直読みができない：Pyxel経由のトリガーが0より大きければ、デジタル値を1にする。アナログ値は0のまま。
        """
        if direct is not None and not is_web:
            raise ValueError("direct trigger values are read only in the browser")
        self.reads += 1
        btn, btnp, btnv = self._btn, self._btnp, self._btnv
        down = {code: btn(code) for code in self._keys}
        hit = {code: btnp(code) for code in self._keys}

        def any_down(keys: tuple) -> bool:
            return any(down[code] for code in keys)

        throttle_digital, brake_digital = int(any_down(self._throttle)), int(any_down(self._brake))
        if direct is not None:
            left, right = direct
            throttle_analog, brake_analog = _clamp(float(right), 0.0, 1.0), _clamp(float(left), 0.0, 1.0)
        elif is_web:
            throttle_analog = brake_analog = 0.0
            throttle_digital = 1 if throttle_digital or btnv(self._throttle_axis) > 0 else 0
            brake_digital = 1 if brake_digital or btnv(self._brake_axis) > 0 else 0
        else:
            throttle_analog = _clamp(btnv(self._throttle_axis) / AXIS_MAX, 0.0, 1.0)
            brake_analog = _clamp(btnv(self._brake_axis) / AXIS_MAX, 0.0, 1.0)
        return InputFrame(
            steer_analog=_clamp(-btnv(self._steer_axis) / AXIS_MAX, -1.0, 1.0),  # 左が正に直す
            steer_digital=int(any_down(self._steer_left)) - int(any_down(self._steer_right)),  # 両方なら0
            throttle_analog=throttle_analog,
            throttle_digital=throttle_digital,
            brake_analog=brake_analog,
            brake_digital=brake_digital,
            held=frozenset(name for name, keys in self._buttons if any_down(keys)),
            pressed=frozenset(name for name, keys in self._buttons if any(hit[code] for code in keys)),
        )
