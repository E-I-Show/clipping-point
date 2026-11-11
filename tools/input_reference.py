"""台本から、世界の要約と、tickごとの入力フレームを量子化した値を、純Pythonで計算する（参照）。

tools/run.py と tools/web_smoke.py が使う。同じ計算を2か所に書かない。pyxel は読み込まない（cp_core だけを読む）。
アプリ（cp_app）が、入力フレームを順のまま、欠かさずに世界へ渡していれば、アプリの世界の要約は、ここの値と同じになる。
道具が使う台本は tools/input_script_smoke.json（SMOKE_SCRIPT）。合計は100 tick以内。舵、アクセル、ブレーキのアナログ値と
デジタル値、10個のボタンのどれも、1度は0でない値になる。アナログ値に 1.0 と -1.0 を1か所ずつ持つ（ブラウザへ渡すと整数で届く）。
同じボタンを、間を空けて2度押す区間を持つ。この中身は tests/test_input_script.py が見張る。
"""
import json
import sys
from pathlib import Path

from _common import APP, TOOLS

if str(APP) not in sys.path:
    sys.path.append(str(APP))  # cp_core を読む。後ろに足す（標準ライブラリの名前を隠さないように）

from cp_core import input_script  # noqa: E402
from cp_core.input_frame import DIGEST_START, NEUTRAL, fold, quantize  # noqa: E402
from cp_core.sim import Sim  # noqa: E402

SMOKE_SCRIPT = TOOLS / "input_script_smoke.json"  # 道具が使う台本


def load_script(path) -> tuple:
    """台本のファイルを読む。返すのは (台本の辞書, 検査済みの台本)。読めない、JSONでない、形が違う、は ValueError。"""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path}: {type(exc).__name__}: {exc}") from exc
    return value, input_script.parse(value)


def frame_at(script, tick: int):
    """tick の入力フレーム。script が None（台本なし）なら、何も押していない入力フレーム。"""
    return NEUTRAL if script is None else script.frame_at(tick)


def sim_summary(script, ticks: int, seed: int = 0) -> dict:
    """世界（種は seed。アプリの世界の種は、いまは0）に、台本の入力フレームを tick 0 から順に ticks 回流したときの、世界の要約。"""
    sim = Sim(seed)
    for tick in range(ticks):
        sim.step(frame_at(script, tick))
    return sim.summary()


def quantized_rows(script, ticks: int) -> list:
    """tick 0 から ticks−1 までの、入力フレームを量子化した値の組の列。"""
    return [quantize(frame_at(script, tick)) for tick in range(ticks)]


def digest_of(rows) -> int:
    """量子化した値の組の列から、入力の要約値を計算し直す。"""
    digest = DIGEST_START
    for row in rows:
        digest = fold(digest, row)
    return digest
