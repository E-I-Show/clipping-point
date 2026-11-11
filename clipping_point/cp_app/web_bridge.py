"""ブラウザ連携。外から渡された値を読む所と、結果をコンソールへ出す所。

ブラウザの機能（js のモジュール）は引数で受ける。テストから偽の実装を渡して確かめるため。
このモジュールは pyxel を読み込まない。js を読み込むのは browser_js() の中だけ（ブラウザ版でだけ通る）。

外から渡す値（ブラウザ版の煙テストが、ページを開く前に差し込むスクリプトで置く）：
  window.CP_PROBE = {ticks: 660, warmup_ticks: 60, script: {…}, trace_max: 400}
    ticks         回すtick数。この数の更新の後に、結果の1行と完了の合図をコンソールへ出す
    warmup_ticks  慣らし。頭の、処理時間と回数の線の判定に入れないtick数（省けば0）
    script        台本（辞書。形は cp_core/input_script.py）。省くか null なら、入力アダプタから読む
    trace_max     入力の跡を取る件数の上限（0以上の整数。省けば0）。1以上なら、入力の跡を取り、
                  更新のたびに window.CP_PROBE_TICK へ、回した更新の数を置く（偽のコントローラーが、これを見て予定を進める）
値が無ければ None を返し、アプリは普通に起動する。出荷するHTMLは、この値を自分では置かない。
値の形が違えば ValueError。黙って普通に起動すると、煙テストが完了の合図を待ち続けるため。
ブラウザ版では、結果を出した後も終了しない（sys.exit と pyxel.quit を呼ぶと、メインループが止まり戻れない）。
"""
import json
from dataclasses import dataclass

from cp_core import input_script

WEB_PLATFORM = "emscripten"  # ブラウザ版の sys.platform
PROBE_NAME = "CP_PROBE"  # window に置く値の名前
PROBE_KEYS = ("ticks", "warmup_ticks", "script", "trace_max")
TICK_NAME = "CP_PROBE_TICK"  # window に置く、tick の印の名前。値は、回した更新の数
RESULT_MARK = "CP_PROBE_RESULT"  # 結果の1行の頭。後ろにJSONが続く
DONE_MARK = "CP_PROBE_DONE"  # 完了の合図


@dataclass(frozen=True)
class Probe:
    """外から渡された、回すtick数などの指定。"""

    ticks: int
    warmup_ticks: int
    script: input_script.InputScript | None = None  # 台本。無ければ、入力アダプタから読む
    trace_max: int = 0  # 入力の跡を取る件数の上限。0なら取らない


def browser_js(platform: str):
    """ブラウザ版なら js のモジュールを返す。デスクトップ版では None。"""
    if platform != WEB_PLATFORM:
        return None
    import js  # Pyodideが用意するモジュール。デスクトップ版には無い

    return js


def read_probe(js) -> Probe | None:
    """window.CP_PROBE を読む。js が None（デスクトップ版）か、値が無ければ None。形が違えば ValueError。"""
    if js is None:
        return None
    # 値はJSONの文字列にしてから受け取る。JavaScriptの値を、そのままPythonへ持ち込まない
    # （無い値は undefined、空の値は null で、Pyodideでは別々の物になる）。
    text = js.JSON.stringify(getattr(js, PROBE_NAME, None))
    if not isinstance(text, str):
        return None  # 値が置かれていない（undefined）
    value = json.loads(text)
    if value is None:
        return None  # null は「無い」と読む
    if not isinstance(value, dict):
        raise ValueError(f"{PROBE_NAME} must be an object, got {text[:80]}")
    unknown = sorted(set(value) - set(PROBE_KEYS))
    if unknown:
        raise ValueError(f"{PROBE_NAME} has unknown keys: {unknown}")
    ticks = value.get("ticks")
    warmup_ticks = value.get("warmup_ticks", 0)
    trace_max = value.get("trace_max", 0)
    for name, number in (("ticks", ticks), ("warmup_ticks", warmup_ticks), ("trace_max", trace_max)):
        if type(number) is not int:  # bool と小数を受けない
            raise ValueError(f"{PROBE_NAME}.{name} must be an integer, got {number!r}")
    if ticks < 1:
        raise ValueError(f"{PROBE_NAME}.ticks must be >= 1, got {ticks}")
    if not 0 <= warmup_ticks < ticks:
        raise ValueError(f"{PROBE_NAME}.warmup_ticks must be >= 0 and < ticks, got {warmup_ticks}")
    if trace_max < 0:
        raise ValueError(f"{PROBE_NAME}.trace_max must be >= 0, got {trace_max}")
    script = value.get("script")
    try:
        parsed = None if script is None else input_script.parse(script)  # null は「無い」と読む
    except ValueError as exc:
        raise ValueError(f"{PROBE_NAME}.script: {exc}") from exc
    return Probe(ticks, warmup_ticks, parsed, trace_max)


def mark_tick(js, ticks: int) -> None:
    """tick の印を置く。window.CP_PROBE_TICK に、回した更新の数を書く。入力の跡を頼まれたときだけ、更新のたびに呼ぶ。"""
    setattr(js, TICK_NAME, ticks)


def emit_result(js, result: dict) -> None:
    """結果の1行（JSON）と完了の合図を、ブラウザのコンソールへ出す。全tickの後に1度だけ呼ぶ。"""
    js.console.log(f"{RESULT_MARK} {json.dumps(result, sort_keys=True)}")
    js.console.log(DONE_MARK)
