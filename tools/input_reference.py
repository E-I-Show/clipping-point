"""台本から、世界の要約と、tickごとの入力フレームを量子化した値を、純Pythonで計算する（参照）。

tools/run.py、tools/web_smoke.py、tools/fingerprint.py が使う。同じ計算を2か所に書かない。pyxel は読み込まない（cp_core と、cp_app の、
pyxel を読み込まないモジュールだけを読む）。
アプリ（cp_app）が、入力フレームを順のまま、欠かさずに世界へ渡していれば、アプリの世界の要約は、ここの値と同じになる。
世界は、アプリと同じ読み方（cp_app/data_files.py と cp_core/datadefs.py）で読んだ定義データから作る（load_data、make_sim）。
試験用データを重ねた回の参照は、同じ試験用データを重ねて作る（pack）。
車とコースの id の既定は、ここの1か所（CAR_ID、TRACK_ID）に置く。指紋の筋書きも、筋書きに当たらない回の参照も、ここから引く。
アプリの定数（cp_app/app.py の CAR_ID、TRACK_ID）と同じであることは、道具 run が、アプリの要約の id で照らす（world_ids_problem）。
道具が使う台本：
  tools/input_script_smoke.json（SMOKE_SCRIPT）  入力の跡の確かめ用。合計は100 tick以内。舵、アクセル、ブレーキのアナログ値とデジタル値、
      10個のボタンのどれも、1度は0でない値になる。アナログ値に 1.0 と -1.0 を1か所ずつ持つ（ブラウザへ渡すと整数で届く）。
      同じボタンを、間を空けて2度押す区間を持つ。この中身は tests/test_input_script.py が見張る。
  tools/input_script_drive.json（DRIVE_SCRIPT）  走る台本。900 tick。発進、加速、変速、コーナー。
  tools/input_script_wall.json（WALL_SCRIPT）    壁の台本。壁に当たって、止まり、後退して、向きを変えて、前進へ戻る。
  走る台本と壁の台本は、入力だけを持つ。作ったのは、作業の補助（tools/claude/make_drive_scripts.py）。道具とテストは、補助を読まない。
デスクトップ版とブラウザ版の突き合わせ（summary_differences）も、ここに置く。項目ごとの比べ方は、世界（cp_core/sim.py の
summary_compare()）から引く。比べ方の表に無い項目が、要約にあれば ValueError（道具は、2にする。見ずに通さない）。
"""
import functools
import json
import sys
from pathlib import Path

from _common import APP, TOOLS

if str(APP) not in sys.path:
    sys.path.append(str(APP))  # cp_core と cp_app を読む。後ろに足す（標準ライブラリの名前を隠さないように）

from cp_app import data_files  # noqa: E402 - pyxel を読み込まないモジュール
from cp_core import input_script  # noqa: E402
from cp_core import sim as world  # noqa: E402
from cp_core.input_frame import DIGEST_START, NEUTRAL, fold, quantize  # noqa: E402
from cp_core.sim import Sim  # noqa: E402

SMOKE_SCRIPT = TOOLS / "input_script_smoke.json"  # 道具が使う台本（入力の跡の確かめ用）
DRIVE_SCRIPT = TOOLS / "input_script_drive.json"  # 走る台本
WALL_SCRIPT = TOOLS / "input_script_wall.json"  # 壁の台本
# 車とコースの id の既定。道具が世界を作るときは、ここから引く（アプリの定数と同じ値。違えば、道具 run が落ちる）。
CAR_ID = "kazane"
TRACK_ID = "test_loop"


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


@functools.lru_cache(maxsize=None)
def load_data(pack=None):
    """定義データを、アプリと同じ読み方で読む（読み込み検査つき）。pack は、重ねる試験用データの名（無ければ None）。

    問題があれば datadefs.DataError、試験用データが無ければ ValueError（どちらも ValueError の仲間）。
    読み込んだ定義は、引くたびに複製を渡すので、覚えておいて、いくつの世界へ渡してもよい。
    """
    return data_files.load({} if pack is None else {data_files.PACK_ENV: pack}, None)


def make_sim(seed: int = 0, pack=None, car_id: str = CAR_ID, track_id: str = TRACK_ID) -> Sim:
    """世界を作る。種は seed（アプリの世界の種は、いまは0）。車とコースの id の既定は、道具の既定。"""
    return Sim(seed, load_data(pack), car_id, track_id)


def sim_summary(script, ticks: int, seed: int = 0, pack=None, car_id: str = CAR_ID, track_id: str = TRACK_ID) -> dict:
    """世界に、台本の入力フレームを tick 0 から順に ticks 回流したときの、世界の要約。pack は、重ねる試験用データの名。"""
    sim = make_sim(seed, pack, car_id, track_id)
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


# --- アプリの要約の、車とコースの id ---
def world_ids_problem(summary, car_id: str = CAR_ID, track_id: str = TRACK_ID) -> str:
    """アプリの世界の要約の、車とコースの id が、道具の既定と同じか。返すのは、違うときの文（同じなら、空の文字列）。"""
    seen = (summary.get("car"), summary.get("track")) if isinstance(summary, dict) else (None, None)
    if seen == (car_id, track_id):
        return ""
    return f"世界の車とコースの id が {seen[0]!r} と {seen[1]!r}（道具の既定は {car_id!r} と {track_id!r}。アプリの定数と、tools/input_reference.py を合わせる）"


# --- デスクトップ版とブラウザ版の突き合わせ ---
def summary_periods(pack=None) -> dict:
    """折り返して比べる項目の、1周の長さ（量子化した整数）。道具の既定の車とコースの世界から引く。"""
    return make_sim(0, pack).summary_periods()


def unknown_summary_fields(*summaries) -> list:
    """要約（辞書でないものは飛ばす）の項目のうち、比べ方の表（cp_core/sim.py）に無い名。整列した順。"""
    rules = world.summary_compare()
    return sorted({str(name) for summary in summaries if isinstance(summary, dict) for name in summary if name not in rules})


def _whole(value) -> bool:
    return type(value) is int


def summary_gap(got, want, periods: dict):
    """2つの世界の要約の、量子化する項目（許容差つき、折り返した差）の差の、いちばん大きい値（量子化の刻みで数える）。

    許容差の余裕を見るための値（道具の最後の1行に出す。判定には使わない）。比べられない（辞書でない、片方に無い、整数でない、
    1周の長さが無い）項目があれば None。
    """
    if not isinstance(got, dict) or not isinstance(want, dict):
        return None
    worst = 0
    for name, kind in world.summary_compare().items():
        if kind == world.COMPARE_EXACT:
            continue
        a, b = got.get(name), want.get(name)
        if not (_whole(a) and _whole(b)) or (kind == world.COMPARE_WRAP and name not in periods):
            return None
        gap = a - b if a >= b else b - a
        if kind == world.COMPARE_WRAP:
            gap %= periods[name]
            gap = min(gap, periods[name] - gap)
        worst = max(worst, gap)
    return worst


def summary_differences(got, want, tolerance: int, periods: dict) -> list:
    """2つの世界の要約（デスクトップ版とブラウザ版）を、項目ごとの比べ方で比べる。返すのは、違いの文の一覧（同じなら空）。

    比べ方は、世界の表（cp_core/sim.py の summary_compare()）から引く。
      完全一致            値と型が同じ（1 と true を、同じに見ない）
      許容差つき          どちらも整数で、量子化の刻みで数えた差が tolerance 以下
      折り返した差        どちらも整数で、1周（periods の、その項目の長さ）で折り返した差が tolerance 以下
    片方にしか無い項目は、違い。要約が辞書でなければ、違い。
    比べ方の表に無い項目、1周の長さが無い項目があれば ValueError（見ずに通さない。道具は、2にする）。
    """
    if not isinstance(got, dict) or not isinstance(want, dict):
        return [f"世界の要約が、辞書でない（{type(got).__name__} と {type(want).__name__}）"]
    unknown = unknown_summary_fields(got, want)
    if unknown:
        raise ValueError(f"要約に、比べ方の表（cp_core/sim.py の SUMMARY_FIELDS）に無い項目がある：{unknown}")
    rules = world.summary_compare()
    lines = []
    for name in sorted(set(got) | set(want)):
        if name not in got or name not in want:
            lines.append(f"{name}: 片方にしか無い（{got.get(name)!r} と {want.get(name)!r}）")
            continue
        a, b, kind = got[name], want[name], rules[name]
        if kind == world.COMPARE_EXACT:
            if a != b or type(a) is not type(b):
                lines.append(f"{name}: {a!r} と {b!r}（完全一致のはず）")
            continue
        if not (_whole(a) and _whole(b)):
            lines.append(f"{name}: {a!r} と {b!r}（どちらも整数のはず）")
            continue
        gap = a - b if a >= b else b - a
        if kind == world.COMPARE_WRAP:
            if name not in periods:
                raise ValueError(f"折り返して比べる項目 {name} の、1周の長さが無い")
            gap %= periods[name]
            gap = min(gap, periods[name] - gap)
        if gap > tolerance:
            lines.append(f"{name}: {a!r} と {b!r}（差が、量子化の刻みで {gap}。許容差は {tolerance}）")
    return lines
