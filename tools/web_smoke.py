"""ブラウザ版の煙テスト。出荷するHTMLそのものを、ヘッドレスのChromiumで開く。

  python3 tools/web_smoke.py [--only shipped|probe|script|gamepad|storage_blocked] [--ticks N] [--timeout 秒]

開くのは、この道具が tools/export.py を回して作らせた dist/clipping_point.html そのもの（同じバイト列）。
煙テスト用に作り直したHTMLは開かない。ランタイムへの要求は、ランタイムの写し（.cache/pyxel_web/mirror/）へ差し替える。
筋書きは5本。順に、1本ずつ回す。どの筋書きでも、直読みの警告（cp_app/input_web.py の WARN_MARK の付いたコンソールの行）が0件であることを見る。
  shipped  何も渡さずに開く。見るもの：Pythonの例外が無い、エラー表示が無い、読み込みの失敗が無い、
           ランタイムの写しの外への要求が無い、開始のクリックの後の決めた秒数で画面が描かれている（背景と違う画素がある）。
           保存：終わりの localStorage を、ブラウザの実行役に読ませ、このアプリの鍵（頭が clippingpoint/）が1つも無いことを見る。
           ふつうの起動は、何も操作しなければ、localStorage に何も残さない（試し書きの鍵は消えている。保存の往復は、
           検証の口のときだけ回す。設定は、読むだけで書かない）。読めていなければ、何も見ずに通さない。
  probe    ページを開く前に差し込むスクリプトで、回すtick数（window.CP_PROBE）を置いて開く。
           アプリがコンソールへ出す結果の1行と完了の合図を待つ。見るもの：上に加えて、回したtick、
           入力の出どころが入力アダプタで、入力アダプタと直読みを呼んだ回数が回したtickと同じ（時間の線が、入力を読んだ更新の値であること）、
           世界の要約がデスクトップ版と合う（項目ごとの比べ方。下の「世界の要約の突き合わせ」）、
           実描画の回数、更新と実描画の毎秒の回数、更新1回と実描画1回の時間（95%点）、
           ブラウザ版であること（sys.platform が emscripten）、Pythonの版。線は tools/budgets.json。
           保存：保存先の名が localstorage、保存の往復が通っている、知らせの1行が空。道具が、ブラウザの localStorage の
           往復の鍵（clippingpoint/selfcheck.settings）の値を自分で読み（ブラウザの実行役が、結果に入れる）、base64 と封筒を開けて、
           往復の見本と比べる。ふつうの保存（名前空間 main）の鍵が、できていないことも見る。
           定義データ：結果の data の、表ごとの件数が、道具が定義データのファイルを自分で読んで数えた件数と同じ、警告が0件、
           試験用データを重ねていない（null）、設定を読んだ保存の口の名前空間が main。数え方と確かめは tools/data_reference.py。
  script   window.CP_PROBE に、回すtick数、道具の台本（tools/input_script_smoke.json）、入力の跡の件数の上限を置いて開く。
           見るもの：ブラウザ版であること、回したtick、入力の出どころが台本で、入力アダプタも直読みも呼んでいない、
           世界の要約がデスクトップ版（同じ台本を渡して回した）と合い、参照（tools/input_reference.py）とも合う（項目ごとの比べ方）、
           入力の跡が打ち切られていない、入力の跡が、台本を入力フレームへ直して量子化した列と、全tickで同じ。
           同じ値を渡して、もう1度開き、2回の世界の要約が、完全に同じことも見る（確かめの名は sim_repeat。同じ環境の中では、
           同じ入力から、同じ結果が出る。世界が、実時間や標準の乱数を読むと、ここで落ちる）。
  gamepad  偽のコントローラー（tools/web/fake_gamepad.js）を差し込んで開く。台本は渡さない。予定と、判定に使う値は PAD_STAGES。
           見るもの：ブラウザ版であること、回したtick、入力の出どころが入力アダプタで、入力アダプタと直読みを呼んだ回数が回したtickと同じ、
           偽のコントローラーが予定の区間を境目のtickで通った、入力の跡が打ち切られていない、
           入力の跡から計算し直した入力の要約値が世界の要約と同じ（アプリが読んだ入力フレームが、そのまま世界へ渡っている）、
           予定の区間ごとに、頭の判定しないtickを除いた全tickで、入力の跡から戻した値が PAD_STAGES のとおり、押した瞬間の立ち方。
  storage_blocked  差し込むスクリプト（tools/web/block_storage.js）で、localStorage に触れると例外になるようにして開く。
           見るもの：ブラウザ版であること、回したtick、入力の出どころ、保存先の名が memory（試し書きが通らず、切り替えた）、
           知らせの1行が、メモリへ切り替えた文と同じ（空でない）、メモリの上での保存の往復が通っている。
script、gamepad、storage_blocked は、処理時間と回数の線を見ない（見るのは probe）。慣らしは0。
世界の要約の突き合わせ（デスクトップ版とブラウザ版。probe の sim、script の sim と sim_reference の3つとも、同じ関数 summary_check で比べる）：
  浮動小数の結果は、デスクトップ版とブラウザ版で一致しない前提。項目ごとの比べ方は、世界（cp_core/sim.py の SUMMARY_FIELDS）から引く。
  完全一致（tick、入力の要約値、種、乱数の流れの状態、車とコースの id、ギア、路面の種類、回数の項目）、
  許容差つき（位置、速度、ヨーレート、実舵角、回転数、横のずれ、進行距離、最高速。量子化の刻みで、tools/budgets.json の
  web_summary_tolerance まで）、折り返した差（向きと、コースに沿った距離。1周で折り返した差が、同じ許容差まで）。
  比べ方の表に無い項目が、要約にあれば、見ずに通さない（2。incomplete=<筋書き>.summary_field_without_rule）。
  最後の1行の probe_gap= と script_gap= は、量子化する項目の、デスクトップ版との差の最大（許容差の余裕を見るための値）。
終了コード：0＝合格、1＝問題あり、2＝回り切れない（ランタイムの写しが無い・照合が合わない、node が無い、
ビルドできない、デスクトップ版の参照が取れない、道具の参照の世界を作れない、ブラウザの実行役の結果が無い、完了の合図が出ない、
台本が読めない、回すtick数が台本の合計より短い、偽のコントローラーの予定の区間に判定するtickが無い、
偽のコントローラーのスクリプトが読めない、保存先に触れると例外にするスクリプトが読めない、世界の要約に、比べ方の表に無い項目がある）。
2を合格にしない。
ページが返らない（Pythonが主スレッドを握ったまま。失敗の種類 unresponsive）は、1にする。
線の判定に使うのは、慣らし（頭の測らないtick）を除いた値。慣らしを入れた値は、最後の1行の with_warmup= に
「更新の毎秒の回数/実描画の毎秒の回数/更新1回のms/実描画1回のms」の順で出す（判定には使わない）。
最後の1行の script_changes= は、台本の筋書きの入力の跡の件数。pad_lag= は、偽のコントローラーの筋書きで、
見えるはずの値が、予定の区間の境目から何tick遅れて見えたかの最大（判定しないtick数の余裕を見るための値）。
結果は out/web_smoke/ に書く。前回の結果は、回す前に消す。
言葉：偽のコントローラーの予定の、同じ値が続くひと続きは「予定の区間」と呼ぶ（番号を付けるときは「区間3」。1始まり）。
英語の名前（PAD_STAGES、PadStage、stage_ticks、判定の名 pad_stage_N、コンソールの行の stage=）は、この予定の区間のこと。
"""
import argparse
import base64
import hashlib
import json
import re
import shutil
import sys
from dataclasses import dataclass

import data_reference
import input_reference
from _common import APP, DIST, FAIL, INCOMPLETE, OK, OUT, TOOLS, child_env, finish, load_budgets, run, show_tail

# fetch_runtime（ランタイムの写しの置き場と照合）と、cp_app の、pyxel を読み込まないモジュール（外から渡す値の名前、
# 結果の行の頭、直読みの警告の印、入力の跡の戻し方、保存先の名、localStorage での鍵の頭）を読む。
# 後ろに足す（標準ライブラリの名前を隠さないように）。
for extra_path in (str(TOOLS / "web"), str(APP)):
    if extra_path not in sys.path:
        sys.path.append(extra_path)

import fetch_runtime  # noqa: E402
from cp_app import input_trace, input_web, storage_select, storage_web, web_bridge  # noqa: E402
from cp_core import profile, storage  # noqa: E402
from cp_core.input_frame import BUTTONS, QUANTIZED_FIELDS, button_bits  # noqa: E402

WORK = OUT / "web_smoke"
HTML = DIST / f"{APP.name}.html"
WEBRUN = TOOLS / "web" / "webrun.js"
FAKE_PAD_JS = TOOLS / "web" / "fake_gamepad.js"
BLOCK_STORAGE_JS = TOOLS / "web" / "block_storage.js"  # localStorage に触れると例外になるようにする、差し込むスクリプト
SCENARIOS = ("shipped", "probe", "script", "gamepad", "storage_blocked")
# 保存の往復が残す値の、localStorage での鍵（clippingpoint/selfcheck.settings）と、ふつうの保存の鍵の頭（clippingpoint/main.）。
SELFCHECK_STORAGE_KEY = f"{storage_web.PREFIX}{profile.SELFCHECK_NAMESPACE}{storage.NAMESPACE_SEPARATOR}{profile.SETTINGS_KEY}"
MAIN_STORAGE_PREFIX = f"{storage_web.PREFIX}{storage.DEFAULT_NAMESPACE}{storage.NAMESPACE_SEPARATOR}"
MIN_MEASURED_TICKS = 60  # 慣らしの後に測るtick数の下限。これより短いと、毎秒の回数が1回の揺れで線を外れる
PAD_PLAN_NAME = "CP_FAKE_PAD_PLAN"  # 偽のコントローラーの予定を置く、window の値の名前（fake_gamepad.js と同じ）
PAD_LOG = re.compile(r"CP_FAKE_PAD stage=(\d+) tick=(\d+)")  # 偽のコントローラーが、予定の区間へ入るたびにコンソールへ出す行
STANDARD, NOT_STANDARD = "standard", ""  # Gamepad API の mapping。標準の並びと、標準でない並び
# 左スティックを、先にわずかに動かしておく値。ブラウザ版のランタイム（SDL）は、接続の後の最初の軸の変化を、その軸の
# 始まりの値として覚えるだけで、Pyxelへは届けない（実測。試作も、値を動かす前に、軸を0.01にする手順を挟んでいた）。
# 0からいきなり −1 へ動かすだけだと、Pyxel経由の値は0のままになる。この値そのものは、Pyxel経由では見えない。
AXIS_NUDGE = 0.01


@dataclass(frozen=True)
class PadStage:
    """偽のコントローラーの予定の区間の1つと、その区間で見えるはずの値。"""

    name: str
    pad: object  # 区間の頭で、偽のコントローラーが見せる状態（fake_pad() の辞書）。None は未接続（コントローラーの枠が全部空）
    expect: dict  # 入力の跡から戻した値（QUANTIZED_FIELDS の名: 値）。書いていない名は0


def fake_pad(mapping: str, axes: tuple = (0, 0, 0, 0), buttons: dict | None = None) -> dict:
    """偽のコントローラーの状態。buttons は、0でないボタンの「番号: 値」（標準の並びで、6が左トリガー、7が右トリガー）。"""
    return {"mapping": mapping, "axes": list(axes), "buttons": {str(index): value for index, value in (buttons or {}).items()}}


# 偽のコントローラーの予定（区間1〜9）と、判定に使う値。ここ1か所に持つ。
# 予定の区間の長さと、区間の頭で判定しないtick数は tools/budgets.json。
# 接続するときは、全部0で接続し、値は次の区間で変える（試作と同じ手順）。
# expect は、この環境での実測を元に置いた。区間6と区間9（押したまま切断）は、Pyxel経由の値も全部0へ戻る。
# 区間8（標準でない並び）は、直読みをせず、Pyxel経由の2値のトリガーをデジタル値へ入れる。
PAD_STAGES = (
    PadStage("unplugged", None, {}),
    PadStage("standard", fake_pad(STANDARD), {}),
    PadStage("right_trigger_0.3", fake_pad(STANDARD, (AXIS_NUDGE, 0, 0, 0), {7: 0.3}), {"throttle_analog": 300}),
    PadStage("triggers_1.0_and_0.6", fake_pad(STANDARD, (AXIS_NUDGE, 0, 0, 0), {7: 1.0, 6: 0.6}), {"throttle_analog": 1000, "brake_analog": 600}),
    PadStage(
        # トリガーは0。左スティックを左いっぱい（軸0が −1）、Aボタン（ボタン0）、十字キーの上（ボタン12）。
        "stick_left_a_up",
        fake_pad(STANDARD, (-1.0, 0, 0, 0), {0: 1.0, 12: 1.0}),
        {"steer_analog": 1000, "throttle_digital": 1, "held": button_bits(("up", "confirm"))},
    ),
    PadStage("unplugged_while_held", None, {}),
    PadStage("not_standard", fake_pad(NOT_STANDARD), {}),
    PadStage("not_standard_triggers", fake_pad(NOT_STANDARD, buttons={6: 0.6, 7: 1.0}), {"throttle_digital": 1, "brake_digital": 1}),
    PadStage("unplugged_again", None, {}),
)
PAD_QUIET_STAGES = (1, 2, 3)  # 区間2〜4（ここは0始まりの番号）。どのtickでも、押した瞬間は空
PAD_PRESS_STAGE = 4  # 区間5（ここは0始まりの番号）。頭の、判定しないtickの中の1 tickだけ、押した瞬間に PAD_PRESS_BUTTON が立つ
PAD_PRESS_BUTTON = "confirm"
PRESSED_AT = QUANTIZED_FIELDS.index("pressed")
# tools/web/webrun.js が集める失敗の種類と、その読み方。並びは、最後の1行の failed= に出す順。
FAILURE_KINDS = {
    "no_start_prompt": "開始の表示が出ない（ランタイムが読み込めていない）",
    "unresponsive": "ページが返らない（Pythonが主スレッドを握ったまま、など）",
    "error_overlay": "Pyxelのエラー表示がある（Pythonの例外）",
    "fatal_error": "ランタイムが致命的なエラーを記した",
    "console_error": "コンソールにエラーの行がある",
    "page_error": "ページの中で、捕まえられなかった例外がある",
    "outside_mirror": "ランタイムの写しの外への要求がある",
    "not_in_mirror": "ランタイムの写しに無いファイルへの要求がある",
    "request_failed": "読み込みの失敗がある",
    "http_status": "400以上の応答がある",
}
TIMING_CHECKS = ("updates_per_s", "renders_per_s", "update_ms_p95", "render_ms_p95")


def is_number(value) -> bool:
    return type(value) in (int, float)


def page_checks(page: dict, html_sha256: str) -> list:
    """どの筋書きでも見ること。返すのは [(名前, 合っているか, 合わないときの文)]。"""
    failures = page.get("failures") or []
    checks = []
    for kind, text in FAILURE_KINDS.items():
        hits = [f for f in failures if f.get("kind") == kind]
        detail = str(hits[0].get("detail", "")).strip().splitlines()[-1:] if hits else []
        checks.append((kind, not hits, f"{text}（{len(hits)}件）：{' '.join(detail)[:300]}"))
    other = sorted({str(f.get("kind")) for f in failures} - set(FAILURE_KINDS))
    checks.append(("other_failure", not other, f"知らない種類の失敗がある：{other}"))
    checks.append(("html_bytes", page.get("htmlSha256") == html_sha256, "開いたHTMLが、export が作ったHTMLと同じバイト列でない"))
    # 直読みは、読めないときに例外を捕まえて「未接続」と同じ値を返す。読み方の誤りを、警告の行で拾う。
    warns = [str(c.get("text", "")) for c in page.get("console") or [] if input_web.WARN_MARK in str(c.get("text", ""))]
    checks.append(("input_warn", not warns, f"直読みの警告がある（{len(warns)}件）：{' '.join(warns[:1])[:300]}"))
    return checks


def judge_shipped(page: dict, html_sha256: str) -> list:
    """何も渡さずに開く筋書きの確かめ。"""
    state = page.get("state") or {}
    ink = (page.get("canvas") or {}).get("ink")
    return page_checks(page, html_sha256) + [
        ("started", page.get("clickedAt") is not None and state.get("initialized") is True, "アプリが始まっていない"),
        ("canvas_ink", type(ink) is int and ink > 0, f"画面が描かれていない（背景と違う画素が {ink}）"),
        nothing_stored_check(page),
    ]


def nothing_stored_check(page: dict) -> tuple:
    """ふつうの起動（何も渡さず、何も操作しない）の後の localStorage に、このアプリの鍵が1つも無いことの確かめ。読むのは、ブラウザの実行役。

    試し書きの鍵は消えていて、保存の往復の鍵（検証の口のときだけ回す）も、ふつうの保存の鍵も無いはず。
    ブラウザの実行役が読めていない（頼んでいない、触れると例外、読んだ鍵の頭が違う）ときは、何も見ずに通さない。
    """
    seen = page.get("localStorage") if isinstance(page.get("localStorage"), dict) else {}
    entries = seen.get("entries")
    if not isinstance(entries, dict) or seen.get("prefix") != storage_web.PREFIX:
        unread = f"ブラウザの実行役が、localStorage の、頭が {storage_web.PREFIX!r} の鍵を読めていない（読んだ頭 {seen.get('prefix')!r}、理由 {seen.get('error')!r}）"
        return "storage_empty", False, unread
    keys = sorted(str(key) for key in entries if str(key).startswith(storage_web.PREFIX))
    return (
        "storage_empty",
        not keys,
        f"何も操作していないのに、localStorage に、このアプリの鍵が残っている：{keys}（ふつうの起動は、試し書きの鍵を消し、保存の往復を回さず、設定を書かない）",
    )


def read_probe_result(page: dict):
    """コンソールの行から、アプリが出した結果を読む。返すのは (結果の辞書, 理由)。読めなければ結果は None。"""
    head = web_bridge.RESULT_MARK + " "
    lines = [c.get("text", "") for c in page.get("console") or [] if str(c.get("text", "")).startswith(head)]
    if page.get("untilAt") is None:
        return None, "no_done_signal"
    if len(lines) != 1:
        return None, "result_line_count"
    try:
        data = json.loads(lines[0][len(head):])
    except ValueError:
        data = None
    return (data, "") if isinstance(data, dict) else (None, "result_unreadable")


def summary_check(name: str, got, want, tolerance: int, periods: dict, label: str) -> tuple:
    """デスクトップ版とブラウザ版の、世界の要約の突き合わせ。返すのは (名前, 合っているか, 合わないときの文)。

    got は、ブラウザ版の世界の要約。want は、比べる相手（デスクトップ版のアプリの要約か、道具の参照）。label は、相手の呼び名。
    比べ方は、項目ごと（tools/input_reference.py の summary_differences。完全一致、許容差つき、折り返した差）。
    3つの突き合わせ（probe の sim、script の sim と sim_reference）は、どれも、この関数で比べる。
    相手が取れていない（None）、比べ方の表に無い項目がある、は合っていない（表に無い項目は、筋書きの側が、先に2にする）。
    """
    if want is None:
        return name, False, f"世界の要約を比べる相手（{label}）が、取れていない"
    try:
        lines = input_reference.summary_differences(got, want, tolerance, periods)
    except ValueError as exc:
        return name, False, f"世界の要約を、{label}と比べられない：{exc}"
    return name, not lines, f"世界の要約が{label}と違う（ブラウザ版 {got}、{label} {want}）：{'。'.join(lines)}"


def summary_fields_without_rule(*summaries) -> list:
    """世界の要約の項目のうち、比べ方の表（cp_core/sim.py）に無い名。あれば、筋書きは、見ずに通さず、回り切れない（2）にする。"""
    return input_reference.unknown_summary_fields(*summaries)


def judge_probe(
    page: dict, html_sha256: str, result: dict, desktop_sim, ticks: int, warmup_ticks: int, budgets: dict, data_tables, data_why: str = "", periods=None,
) -> list:
    """回すtick数を渡して開く筋書きの確かめ。result は、アプリがコンソールへ出した結果。

    data_tables は、道具が定義データのファイルを自分で読んで数えた、表ごとの項目の数（数えられなかったら None。data_why は、その理由）。
    periods は、折り返して比べる項目の、1周の長さ（無ければ、道具の既定の世界から引く）。
    """
    periods = input_reference.summary_periods() if periods is None else periods
    perf = result.get("perf") if isinstance(result.get("perf"), dict) else {}
    renders, tolerance = result.get("renders"), budgets["web_renders_tolerance"]
    measured_renders, measured_ticks = perf.get("renders"), ticks - warmup_ticks
    python = str(result.get("python", ""))
    ups, rps = perf.get("updates_per_s"), perf.get("renders_per_s")
    update_ms, render_ms = perf.get("update_ms_p95"), perf.get("render_ms_p95")
    ups_min, rps_min = budgets["web_updates_per_s_min"], budgets["web_renders_per_s_min"]
    update_max, render_max = budgets["web_update_ms_p95_max"], budgets["web_render_ms_p95_max"]
    return page_checks(page, html_sha256) + [
        ("platform", result.get("platform") == web_bridge.WEB_PLATFORM, f"ブラウザ版でない（sys.platform が {result.get('platform')!r}）"),
        ("python", python.startswith(fetch_runtime.WEB_PYTHON + "."), f"Pythonの版が {python!r}（{fetch_runtime.WEB_PYTHON} のはず）"),
        ("ticks", result.get("ticks") == ticks, f"回したtickが {result.get('ticks')}（{ticks} のはず）"),
        # 時間の線が、入力を読んだ更新の値であること。入力アダプタと直読みを呼ばない更新で測っても、ほかの確かめは通ってしまう。
        *source_checks(result, ticks, "adapter"),
        (
            "measured_ticks",
            perf.get("updates") == ticks - warmup_ticks,
            f"測ったtickが {perf.get('updates')}（慣らしの {warmup_ticks} を除いて {ticks - warmup_ticks} のはず）",
        ),
        summary_check("sim", result.get("sim"), desktop_sim, budgets["web_summary_tolerance"], periods, "デスクトップ版"),
        # 保存。アプリの申告（保存先の名、往復が通ったか、知らせ）と、道具が自分で読んだ localStorage の値。
        *storage_checks(result, storage_select.BACKEND_WEB, ""),
        *stored_value_checks(page),
        # 定義データ。ブラウザ版は、試験用データを重ねない（名は null、保存の名前空間は main）。
        *data_reference.data_checks(result, data_tables, None, f"（数えられなかった：{data_why}）" if data_why else ""),
        (
            "renders",
            type(renders) is int and abs(renders - ticks // 2) <= tolerance,
            f"実描画が {renders} 回（{ticks // 2} 回の前後 {tolerance} 回のはず。毎秒30回）",
        ),
        (
            # 時間を測る所が、実描画のたびに1度だけ呼ばれていること（数える所の付け間違いを拾う）。
            "perf_renders",
            type(measured_renders) is int and abs(measured_renders - measured_ticks // 2) <= tolerance,
            f"時間を測った実描画が {measured_renders} 回（慣らしを除いて {measured_ticks // 2} 回の前後 {tolerance} 回のはず）",
        ),
        ("updates_per_s", is_number(ups) and ups >= ups_min, f"更新が毎秒 {ups} 回（{ups_min} 回以上のはず）"),
        ("renders_per_s", is_number(rps) and rps >= rps_min, f"実描画が毎秒 {rps} 回（{rps_min} 回以上のはず）"),
        ("update_ms_p95", is_number(update_ms) and update_ms <= update_max, f"更新1回が {update_ms} ms（95%点。{update_max} ms以内のはず）"),
        ("render_ms_p95", is_number(render_ms) and render_ms <= render_max, f"実描画1回が {render_ms} ms（95%点。{render_max} ms以内のはず）"),
    ]


def storage_checks(result: dict, backend: str, notice: str) -> list:
    """保存についての、アプリの申告の確かめ。backend は保存先の名、notice は知らせの1行（どちらも、こうなっているはずの値）。"""
    saved = result.get("storage") if isinstance(result.get("storage"), dict) else {}
    return [
        ("storage_backend", saved.get("backend") == backend, f"保存先の名が {saved.get('backend')!r}（{backend!r} のはず）"),
        ("storage_ok", saved.get("ok") is True, f"保存の往復が通っていない（通ったか {saved.get('ok')!r}、理由 {saved.get('detail')!r}）"),
        ("storage_notice", saved.get("notice") == notice, f"知らせの1行が {saved.get('notice')!r}（{notice!r} のはず。表示用の値から取った値）"),
    ]


def read_stored_settings(entries) -> tuple:
    """ブラウザの localStorage の中身（{鍵: 値}）から、保存の往復が残した値を、道具が自分で読む。返すのは (合っているか, 合わないときの文)。

    値は base64 の文字列。開けて、封筒を開けて、形式バージョンと本体を、往復の見本と比べる。
    """
    value = entries.get(SELFCHECK_STORAGE_KEY) if isinstance(entries, dict) else None
    if not isinstance(value, str):
        return False, f"localStorage に、保存の往復の鍵（{SELFCHECK_STORAGE_KEY}）が無い"
    try:
        version, payload = storage.unwrap(base64.b64decode(value, validate=True))
    except (ValueError, storage.CorruptError) as exc:
        return False, f"localStorage の、保存の往復の値が読めない（{type(exc).__name__}: {exc}）：{value[:80]!r}"
    want = (profile.SETTINGS_VERSION, profile.encode(profile.SELFCHECK_SETTINGS))
    return (version, payload) == want, f"localStorage の、保存の往復の値が、往復の見本と違う（形式バージョン {version}、本体 {payload[:120]!r}）"


def stored_value_checks(page: dict) -> list:
    """道具が、ブラウザの localStorage を自分で読んで照らす確かめ（アプリの申告だけに頼らない）。読むのは、ブラウザの実行役。"""
    seen = page.get("localStorage") if isinstance(page.get("localStorage"), dict) else {}
    entries = seen.get("entries")
    if not isinstance(entries, dict):
        unread = f"ブラウザの実行役が、localStorage を読めていない（{seen.get('error')!r}）"
        return [("storage_value", False, unread), ("storage_main", False, unread)]
    ok, message = read_stored_settings(entries)
    main_keys = sorted(str(key) for key in entries if str(key).startswith(MAIN_STORAGE_PREFIX))
    return [
        ("storage_value", ok, message),
        (
            "storage_main",
            not main_keys,
            f"ふつうの保存（名前空間 {storage.DEFAULT_NAMESPACE}）の鍵ができている：{main_keys}（保存の往復は、名前空間 {profile.SELFCHECK_NAMESPACE} で回す）",
        ),
    ]


def judge_storage_blocked(page: dict, html_sha256: str, result: dict, ticks: int) -> list:
    """localStorage に触れると例外になるようにして開く筋書きの確かめ。保存先は、メモリへ切り替わっているはず。"""
    return page_checks(page, html_sha256) + input_checks(result, ticks, "adapter") + storage_checks(
        result, storage_select.BACKEND_MEMORY, storage.NOTICE_MEMORY_FALLBACK
    )


def source_checks(result: dict, ticks: int, source: str) -> list:
    """入力の出どころと、読んだ回数の確かめ。source は "script" か "adapter"。回したtickの確かめ（ticks）の後ろに置く。

    入力アダプタと直読みは、台本なら呼ばない（0回）。入力アダプタから読むなら、どちらも1 tickに1度（回したtickと同じ）。
    """
    adapter_reads, direct_reads = result.get("adapter_reads"), result.get("direct_reads")
    want_reads = ticks if source == "adapter" else 0
    return [
        ("input_source", result.get("input_source") == source, f"入力の出どころが {result.get('input_source')!r}（{source!r} のはず）"),
        ("adapter_reads", adapter_reads == want_reads, f"入力アダプタを呼んだ回数が {adapter_reads}（{want_reads} のはず）"),
        ("direct_reads", direct_reads == want_reads, f"直読みを呼んだ回数が {direct_reads}（{want_reads} のはず）"),
    ]


def input_checks(result: dict, ticks: int, source: str) -> list:
    """入力に関わる筋書き（script、gamepad）で、どちらでも見ること。source は "script" か "adapter"。"""
    return [
        ("platform", result.get("platform") == web_bridge.WEB_PLATFORM, f"ブラウザ版でない（sys.platform が {result.get('platform')!r}）"),
        ("ticks", result.get("ticks") == ticks, f"回したtickが {result.get('ticks')}（{ticks} のはず）"),
        *source_checks(result, ticks, source),
    ]


def read_trace(result: dict, ticks: int) -> tuple:
    """結果の入力の跡を、tickごとの値の組の列に戻す。返すのは (列, 理由)。戻せなければ（打ち切り、形の違い）列は None。"""
    try:
        return input_trace.expand(result.get("inputs"), ticks), ""
    except ValueError as exc:
        return None, str(exc)


def first_difference(rows: list, want_rows: list):
    """2つの列が最初に違うtick。同じなら None。長さが違えば、短いほうの次のtick。"""
    for tick, (row, want) in enumerate(zip(rows, want_rows)):
        if row != want:
            return tick
    return None if len(rows) == len(want_rows) else min(len(rows), len(want_rows))


def repeat_check(sim, again_sim) -> tuple:
    """同じ値を渡して、もう1度開いたときの、世界の要約が、1回目と完全に同じことの確かめ（同じ環境の中では、同じ入力から、同じ結果）。"""
    same = isinstance(sim, dict) and isinstance(again_sim, dict) and sim == again_sim
    names = sorted(set(sim) | set(again_sim)) if isinstance(sim, dict) and isinstance(again_sim, dict) else []
    differing = [name for name in names if sim.get(name) != again_sim.get(name)]
    return (
        "sim_repeat", same,
        f"同じ台本を、もう1度回した世界の要約が、1回目と違う（違う項目 {differing}。1回目 {sim}、2回目 {again_sim}）。"
        "世界が、入力のほか（実時間、標準の乱数、集合を回した順）を読んでいる",
    )


def judge_script(page: dict, html_sha256: str, result: dict, desktop_sim, script, ticks: int, tolerance: int, again_sim, periods=None) -> list:
    """台本を渡して開く筋書きの確かめ。script は検査済みの台本。desktop_sim は、同じ台本を渡したデスクトップ版の世界の要約。

    tolerance は、許容差つきの項目の、量子化の刻みで数えた差の上限。again_sim は、同じ値を渡して、もう1度開いたときの、世界の要約。
    periods は、折り返して比べる項目の、1周の長さ（無ければ、道具の既定の世界から引く）。
    """
    periods = input_reference.summary_periods() if periods is None else periods
    want_sim, want_rows = input_reference.sim_summary(script, ticks), input_reference.quantized_rows(script, ticks)
    rows, why = read_trace(result, ticks)
    bad_tick = None if rows is None else first_difference(rows, want_rows)
    detail = "" if rows is None or bad_tick is None else f"tick {bad_tick} が {rows[bad_tick]}（台本は {want_rows[bad_tick]}。並びは {QUANTIZED_FIELDS}）"
    sim = result.get("sim")
    return page_checks(page, html_sha256) + input_checks(result, ticks, "script") + [
        summary_check("sim", sim, desktop_sim, tolerance, periods, "デスクトップ版"),
        summary_check("sim_reference", sim, want_sim, tolerance, periods, "参照"),
        repeat_check(sim, again_sim),
        ("trace_complete", rows is not None, f"入力の跡が使えない（{why}）"),
        ("trace", rows is not None and bad_tick is None, f"入力の跡が台本と違う：{detail or '入力の跡が使えない'}"),
    ]


def pad_plan(stage_ticks: int) -> list:
    """偽のコントローラーへ渡す予定。形は tools/web/fake_gamepad.js の頭の注。"""
    return [{"until": (index + 1) * stage_ticks, "pad": stage.pad} for index, stage in enumerate(PAD_STAGES)]


def pad_ticks(stage_ticks: int) -> int:
    """偽のコントローラーの筋書きで回すtick数。予定の最後の区間の終わりまで。"""
    return stage_ticks * len(PAD_STAGES)


def pad_expected_row(stage: PadStage) -> tuple:
    unknown = sorted(set(stage.expect) - set(QUANTIZED_FIELDS))
    if unknown:
        raise ValueError(f"PAD_STAGES の {stage.name} に、知らない名がある：{unknown}")
    return tuple(stage.expect.get(name, 0) for name in QUANTIZED_FIELDS)


def read_pad_log(page: dict) -> list:
    """偽のコントローラーが予定の区間へ入った跡。[(区間の番号（1始まり）, そのときの tick の印), …]"""
    hits = (PAD_LOG.fullmatch(str(c.get("text", ""))) for c in page.get("console") or [])
    return [(int(hit.group(1)), int(hit.group(2))) for hit in hits if hit]


def pad_lag(rows: list, stage_ticks: int):
    """見えるはずの値が、予定の区間の境目から何tick遅れて見えたかの、全部の区間での最大。どこかの区間で1度も見えなければ None。

    押した瞬間は比べない（見えた最初のtickにだけ立つので、入れると、その区間がいつも1 tick遅れに見える）。
    """
    worst = 0
    for index, stage in enumerate(PAD_STAGES):
        want, start = pad_expected_row(stage)[:PRESSED_AT], index * stage_ticks
        seen = [offset for offset, row in enumerate(rows[start:start + stage_ticks]) if row[:PRESSED_AT] == want]
        if not seen:
            return None
        worst = max(worst, seen[0])
    return worst


def judge_gamepad(page: dict, html_sha256: str, result: dict, stage_ticks: int, settle_ticks: int) -> list:
    """偽のコントローラーを差し込んで開く筋書きの確かめ。settle_ticks は、予定の区間の頭で判定しないtick数。"""
    ticks = pad_ticks(stage_ticks)
    rows, why = read_trace(result, ticks)
    no_trace = "入力の跡が使えないので、見られない"
    want_log = [(index + 1, index * stage_ticks) for index in range(len(PAD_STAGES))]
    log = read_pad_log(page)
    # 世界の要約からは、tick と入力の要約値の2項目だけを比べる。要約の形を、ここで手で組まない
    # （Sim.summary() に項目が足されても、この確かめが落ちないように）。
    sim = result.get("sim")
    sim_tick, sim_digest = (sim.get("tick"), sim.get("input_digest")) if isinstance(sim, dict) else (None, None)
    want_digest = None if rows is None else input_reference.digest_of(rows)
    checks = page_checks(page, html_sha256) + input_checks(result, ticks, "adapter") + [
        ("pad_plan", log == want_log, f"偽のコントローラーが、予定の区間を境目のtickで通っていない（通った跡 {log}。tick の印が置かれていない、など）"),
        ("trace_complete", rows is not None, f"入力の跡が使えない（{why}）"),
        (
            "sim_from_trace",
            rows is not None and sim_tick == ticks and sim_digest == want_digest,
            (
                f"世界の要約の tick と入力の要約値が、入力の跡から計算し直した値と違う"
                f"（世界は tick {sim_tick}、入力の要約値 {sim_digest}。入力の跡からは tick {ticks}、入力の要約値 {want_digest}）"
            ) if rows is not None else no_trace,
        ),
    ]
    for index, stage in enumerate(PAD_STAGES):
        name, start = f"pad_stage_{index + 1}", index * stage_ticks
        if rows is None:
            checks.append((name, False, no_trace))
            continue
        want = pad_expected_row(stage)
        bad = [tick for tick in range(start + settle_ticks, start + stage_ticks) if rows[tick] != want]
        seen = rows[bad[0]] if bad else want
        checks.append((
            name, not bad,
            f"区間{index + 1}（{stage.name}）の tick {bad[0] if bad else '-'} が {seen}（{want} のはず。並びは {QUANTIZED_FIELDS}。違うtickが {len(bad)} 個）",
        ))
    if rows is None:
        return checks + [("pad_pressed_quiet", False, no_trace), ("pad_pressed_once", False, no_trace)]
    quiet = [tick for index in PAD_QUIET_STAGES for tick in range(index * stage_ticks, (index + 1) * stage_ticks) if rows[tick][PRESSED_AT] != 0]
    press_start, bit = PAD_PRESS_STAGE * stage_ticks, 1 << BUTTONS.index(PAD_PRESS_BUTTON)
    presses = [tick for tick in range(press_start, press_start + stage_ticks) if rows[tick][PRESSED_AT] & bit]
    return checks + [
        ("pad_pressed_quiet", not quiet, f"区間2〜4で、押した瞬間が立っている（tick {quiet[:5]}）"),
        (
            "pad_pressed_once",
            len(presses) == 1 and presses[0] < press_start + settle_ticks,
            f"区間5で、押した瞬間の {PAD_PRESS_BUTTON} が立ったtickが {presses}（区間の頭の {settle_ticks} tickの中の、1 tickだけのはず）",
        ),
    ]


def probe_script(value: dict) -> str:
    """外から渡す値（window.CP_PROBE）を置く、差し込むスクリプトの1行。"""
    return f"window.{web_bridge.PROBE_NAME} = {json.dumps(value)};"


def pad_init_script(stage_ticks: int, trace_max: int) -> str:
    """偽のコントローラーの筋書きで差し込むスクリプト。予定を置く1行、fake_gamepad.js の中身、外から渡す値を置く1行。"""
    plan_line = f"window.{PAD_PLAN_NAME} = {json.dumps(pad_plan(stage_ticks))};"
    return "\n".join([plan_line, FAKE_PAD_JS.read_text(encoding="utf-8"), probe_script({"ticks": pad_ticks(stage_ticks), "trace_max": trace_max})])


def blocked_init_script(ticks: int) -> str:
    """保存先に触れると例外になる筋書きで差し込むスクリプト。block_storage.js の中身と、外から渡す値を置く1行。"""
    return "\n".join([BLOCK_STORAGE_JS.read_text(encoding="utf-8"), probe_script({"ticks": ticks})])


def open_page(name: str, timeout_s: float, extra: list):
    """ブラウザの実行役（webrun.js）を1本回し、結果のJSONを読む。読めなければ None。"""
    json_path = WORK / f"{name}.json"
    cmd = [
        "node", WEBRUN, "--html", HTML, "--mirror", fetch_runtime.MIRROR, "--json", json_path,
        "--shot", WORK / f"{name}.png", "--timeout-ms", int(timeout_s * 1000), *extra,
    ]
    code, out, err = run(cmd, timeout=timeout_s + 60)
    try:
        page = json.loads(json_path.read_text(encoding="utf-8")) if code == 0 else None
    except (OSError, ValueError):
        page = None
    if not isinstance(page, dict):
        show_tail(out, err)
        print(f"  web_smoke: [{name}] ブラウザの実行役の結果が無い（終了コード {code}）")
        return None
    return page


def open_with_probe(name: str, timeout_s: float, init_script: str, html_sha256: str, extra: tuple = ()) -> tuple:
    """外から値を渡して開き、アプリがコンソールへ出した結果を読む。返すのは (ページ, 結果, 確かめ, 回り切れない理由)。

    結果が読めたら、確かめは None（呼ぶ側が、筋書きの判定の関数で作る）。
    結果が読めないとき、失敗の合図があれば問題あり（確かめを返す）、何も無ければ回り切れていない（理由を返す）。
    extra は、ブラウザの実行役へ足す引数（localStorage の中身を読ませる、など）。
    """
    page = open_page(name, timeout_s, ["--init-script", init_script, "--until", f"^{web_bridge.DONE_MARK}$", *extra])
    if page is None:
        return None, None, None, "no_runner_result"
    result, reason = read_probe_result(page)
    if result is not None:
        return page, result, None, ""
    checks = page_checks(page, html_sha256)
    if all(ok for _, ok, _ in checks):
        print(f"  web_smoke: [{name}] 結果が読めない（{reason}）。失敗の合図も無い。時間切れ {timeout_s:g} 秒")
        return page, None, None, reason
    return page, None, checks + [(reason, False, "アプリの結果が読めない")], ""


def desktop_reference(name: str, ticks: int, script_path=None):
    """デスクトップ版を同じtick数だけ画面なしで回し、世界の要約を返す。取れなければ None。script_path があれば、その台本を渡す。"""
    result_path = WORK / f"desktop_{name}.json"
    env = child_env(CP_SMOKE=result_path, CP_SMOKE_TICKS=ticks, CP_SMOKE_DRIVER="flip")
    if script_path is not None:
        env["CP_SMOKE_SCRIPT"] = str(script_path)
    code, out, err = run([sys.executable, APP / "main.py"], timeout=60 + ticks / 20, env=env, cwd=WORK)
    try:
        data = json.loads(result_path.read_text(encoding="utf-8")) if code == 0 else None
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or data.get("ticks") != ticks or not isinstance(data.get("sim"), dict):
        show_tail(out, err)
        return None
    return data["sim"]


def scenario_shipped(args, budgets: dict, html_sha256: str, context: dict) -> tuple:
    """何も渡さずに開く。返すのは (確かめ, 最後の1行に出す値, 回り切れない理由)。回り切れなければ、確かめは None。"""
    # 終わりの localStorage の中身（鍵の頭が合うもの）を、ブラウザの実行役に読ませる。何も残っていないことを、道具が自分で見る。
    extra = ["--watch-ms", int(budgets["web_shipped_watch_s"] * 1000), "--local-storage", storage_web.PREFIX]
    page = open_page("shipped", args.timeout, extra)
    if page is None:
        return None, [], "no_runner_result"
    return judge_shipped(page, html_sha256), [f"canvas_ink={(page.get('canvas') or {}).get('ink')}"], ""


def scenario_probe(args, budgets: dict, html_sha256: str, context: dict) -> tuple:
    """回すtick数を渡して開く。処理時間と回数の線を見る。"""
    warmup_ticks = budgets["web_probe_warmup_ticks"]
    desktop_sim = desktop_reference("probe", args.ticks)
    if desktop_sim is None:
        return None, [], "no_desktop_reference"
    init_script = probe_script({"ticks": args.ticks, "warmup_ticks": warmup_ticks})
    # 終わった後の localStorage の中身（鍵の頭が合うもの）を、ブラウザの実行役に読ませる。道具が、保存の往復の値を自分で照らす。
    page, result, checks, reason = open_with_probe("probe", args.timeout, init_script, html_sha256, ("--local-storage", storage_web.PREFIX))
    if result is None:
        return checks, [], reason
    # 世界の要約に、比べ方の表に無い項目があれば、見ずに通さない（回り切れない）。
    strange = summary_fields_without_rule(result.get("sim"), desktop_sim)
    if strange:
        print(f"  web_smoke: [probe] 世界の要約に、比べ方の表（cp_core/sim.py の SUMMARY_FIELDS）に無い項目がある：{strange}")
        return None, [], "summary_field_without_rule"
    periods = context["periods"]
    perf = result.get("perf") if isinstance(result.get("perf"), dict) else {}
    whole = perf.get("with_warmup") if isinstance(perf.get("with_warmup"), dict) else {}
    saved = result.get("storage") if isinstance(result.get("storage"), dict) else {}
    fact = (
        f"ticks={result.get('ticks')} renders={result.get('renders')} "
        + " ".join(f"{key}={perf.get(key)}" for key in TIMING_CHECKS)
        + " with_warmup=" + "/".join(str(whole.get(key)) for key in TIMING_CHECKS)
        + f" python={result.get('python')} save={saved.get('backend')}"
        + f" probe_gap={input_reference.summary_gap(result.get('sim'), desktop_sim, periods)}"
    )
    # 定義データの、表ごとの項目の数。道具が、ソースの木のファイルを自分で読んで数える（出荷物の中身がソースと同じことは export が見る）。
    data_tables, data_why = data_reference.expected_tables()
    return judge_probe(page, html_sha256, result, desktop_sim, args.ticks, warmup_ticks, budgets, data_tables, data_why, periods), [fact], ""


def scenario_script(args, budgets: dict, html_sha256: str, context: dict) -> tuple:
    """台本を渡して開く。台本は、main() が先に読んで検査したもの。"""
    ticks, script_value, script = budgets["web_script_ticks"], context["script_value"], context["script"]
    desktop_sim = desktop_reference("script", ticks, input_reference.SMOKE_SCRIPT)
    if desktop_sim is None:
        return None, [], "no_desktop_reference"
    init_script = probe_script({"ticks": ticks, "script": script_value, "trace_max": budgets["web_input_trace_max"]})
    page, result, checks, reason = open_with_probe("script", args.timeout, init_script, html_sha256)
    if result is None:
        return checks, [], reason
    # 同じ値を渡して、もう1度開く。2回の世界の要約が、完全に同じことを見る（設計の「同じ台本を2回回して一致」）。
    _, again, again_checks, again_reason = open_with_probe("script_again", args.timeout, init_script, html_sha256)
    if again is None:
        return again_checks, [], again_reason
    # 世界の要約に、比べ方の表に無い項目があれば、見ずに通さない（回り切れない）。
    strange = summary_fields_without_rule(result.get("sim"), again.get("sim"), desktop_sim)
    if strange:
        print(f"  web_smoke: [script] 世界の要約に、比べ方の表（cp_core/sim.py の SUMMARY_FIELDS）に無い項目がある：{strange}")
        return None, [], "summary_field_without_rule"
    periods = context["periods"]
    inputs = result.get("inputs") if isinstance(result.get("inputs"), dict) else {}
    changes = inputs.get("changes")
    fact = (
        f"script_changes={len(changes) if isinstance(changes, list) else None}"
        f" script_gap={input_reference.summary_gap(result.get('sim'), desktop_sim, periods)}"
    )
    checks = judge_script(page, html_sha256, result, desktop_sim, script, ticks, budgets["web_summary_tolerance"], again.get("sim"), periods)
    return checks, [fact], ""


def scenario_gamepad(args, budgets: dict, html_sha256: str, context: dict) -> tuple:
    """偽のコントローラーを差し込んで開く。差し込むスクリプトは、main() が先に組んだもの。"""
    stage_ticks, settle_ticks = budgets["web_pad_stage_ticks"], budgets["web_pad_settle_ticks"]
    page, result, checks, reason = open_with_probe("gamepad", args.timeout, context["pad_init_script"], html_sha256)
    if result is None:
        return checks, [], reason
    rows, _ = read_trace(result, pad_ticks(stage_ticks))
    fact = f"pad_lag={None if rows is None else pad_lag(rows, stage_ticks)}"
    return judge_gamepad(page, html_sha256, result, stage_ticks, settle_ticks), [fact], ""


def scenario_storage_blocked(args, budgets: dict, html_sha256: str, context: dict) -> tuple:
    """localStorage に触れると例外になるようにして開く。差し込むスクリプトは、main() が先に組んだもの。"""
    page, result, checks, reason = open_with_probe("storage_blocked", args.timeout, context["blocked_init_script"], html_sha256)
    if result is None:
        return checks, [], reason
    saved = result.get("storage") if isinstance(result.get("storage"), dict) else {}
    fact = f"blocked_save={saved.get('backend')}"
    return judge_storage_blocked(page, html_sha256, result, budgets["web_blocked_ticks"]), [fact], ""


RUNNERS = {
    "shipped": scenario_shipped, "probe": scenario_probe, "script": scenario_script, "gamepad": scenario_gamepad,
    "storage_blocked": scenario_storage_blocked,
}


def main() -> int:
    budgets = load_budgets()
    ap = argparse.ArgumentParser(description="ブラウザ版の煙テスト")
    ap.add_argument("--only", choices=SCENARIOS, help="この筋書きだけ回す")
    ap.add_argument("--ticks", type=int, default=budgets["web_probe_ticks"], help="probe で回すtick数（慣らしを含む）")
    ap.add_argument("--timeout", type=float, default=budgets["web_timeout_s"], help="筋書き1本の時間切れ（秒）")
    args = ap.parse_args()
    names = [args.only] if args.only else list(SCENARIOS)
    warmup_ticks = budgets["web_probe_warmup_ticks"]
    min_ticks = warmup_ticks + MIN_MEASURED_TICKS
    if "probe" in names and args.ticks < min_ticks:
        return finish("web_smoke", INCOMPLETE, f"scenarios=0 reason=too_few_ticks min={min_ticks}")
    context = {}
    if "probe" in names or "script" in names:
        # 世界の要約を、デスクトップ版と突き合わせる筋書き。折り返して比べる項目の、1周の長さを、道具の既定の世界から引く
        # （定義データを、アプリと同じ読み方で読む。読めなければ、回り切れない）。
        try:
            context["periods"] = input_reference.summary_periods()
        except ValueError as exc:
            print(f"  web_smoke: 参照の世界を作れない（定義データが読めない）：{exc}")
            return finish("web_smoke", INCOMPLETE, "scenarios=0 reason=no_reference")
    if "script" in names:
        try:
            context["script_value"], context["script"] = input_reference.load_script(input_reference.SMOKE_SCRIPT)
        except ValueError as exc:
            print(f"  web_smoke: 台本が読めない：{exc}")
            return finish("web_smoke", INCOMPLETE, "scenarios=0 reason=script_unreadable")
        # 台本の終わりまで回さないと、台本の後ろの入力が世界へ届いたことを見られない。
        script_ticks, total = budgets["web_script_ticks"], context["script"].total_ticks
        if script_ticks < total:
            return finish("web_smoke", INCOMPLETE, f"scenarios=0 reason=ticks_shorter_than_script ticks={script_ticks} script_ticks={total}")
    if "gamepad" in names:
        # 予定のどの区間にも、判定するtickが1個以上あること。無ければ、何も見ずに合格になる。
        stage_ticks, settle_ticks = budgets["web_pad_stage_ticks"], budgets["web_pad_settle_ticks"]
        if not 0 <= settle_ticks < stage_ticks:
            return finish("web_smoke", INCOMPLETE, f"scenarios=0 reason=pad_stage_too_short stage_ticks={stage_ticks} settle_ticks={settle_ticks}")
        # 差し込むスクリプトを、先に組む。偽のコントローラーのスクリプトが読めなければ、回り切れない（例外で終わらせない）。
        try:
            context["pad_init_script"] = pad_init_script(stage_ticks, budgets["web_input_trace_max"])
        except (OSError, ValueError) as exc:  # 無い、読めない、UTF-8でない
            print(f"  web_smoke: 偽のコントローラーのスクリプト（{FAKE_PAD_JS.name}）が読めない：{type(exc).__name__}: {exc}")
            return finish("web_smoke", INCOMPLETE, "scenarios=0 reason=no_fake_gamepad")
    if "storage_blocked" in names:
        # 差し込むスクリプトを、先に組む。読めなければ、回り切れない（保存先を止めずに開いて、別の理由で落とさない）。
        try:
            context["blocked_init_script"] = blocked_init_script(budgets["web_blocked_ticks"])
        except (OSError, ValueError) as exc:  # 無い、読めない、UTF-8でない
            print(f"  web_smoke: 保存先に触れると例外にするスクリプト（{BLOCK_STORAGE_JS.name}）が読めない：{type(exc).__name__}: {exc}")
            return finish("web_smoke", INCOMPLETE, "scenarios=0 reason=no_block_storage")
    if not shutil.which("node"):
        return finish("web_smoke", INCOMPLETE, "scenarios=0 reason=no_node")
    try:
        missing, mismatched = fetch_runtime.check_mirror(fetch_runtime.read_sums())
    except (OSError, ValueError) as exc:
        print(f"  web_smoke: {exc}")
        return finish("web_smoke", INCOMPLETE, "scenarios=0 reason=no_sums")
    if missing or mismatched:
        print("  web_smoke: ランタイムの写しが使えない。python3 tools/web/fetch_runtime.py で取得して照合する。")
        reason = "runtime_mirror_mismatch" if mismatched else "no_runtime_mirror"
        return finish("web_smoke", INCOMPLETE, f"scenarios=0 reason={reason} missing={len(missing)} mismatched={len(mismatched)}")

    shutil.rmtree(WORK, ignore_errors=True)  # 前回の結果を読んで合格にしない
    WORK.mkdir(parents=True)
    code, out, err = run([sys.executable, TOOLS / "export.py"])
    if code != 0 or not HTML.is_file():
        show_tail(out, err)
        return finish("web_smoke", INCOMPLETE, f"scenarios=0 reason=export_failed export_exit={code}")
    html_sha256 = hashlib.sha256(HTML.read_bytes()).hexdigest()

    states, failed, incomplete, facts = {}, [], [], []
    checks_total = problems_total = 0
    for name in names:
        checks, scenario_facts, reason = RUNNERS[name](args, budgets, html_sha256, context)
        if checks is None:
            states[name] = INCOMPLETE
            incomplete.append(f"{name}.{reason}")
            continue
        facts += scenario_facts
        bad = [(check, message) for check, ok, message in checks if not ok]
        for check, message in bad:
            print(f"  web_smoke: [{name}] {message}")
        if bad and all(check in TIMING_CHECKS for check, _ in bad):
            print(f"  web_smoke: [{name}] 外れたのは処理時間と回数の線だけ。単独で1度回し直し、それでも外れたら失敗とする（docs/plan.md の段0の通過条件）。")
        checks_total += len(checks)
        problems_total += len(bad)
        failed += [f"{name}.{check}" for check, _ in bad]
        states[name] = FAIL if bad else OK

    word = {OK: "ok", FAIL: "failed", INCOMPLETE: "incomplete"}
    summary = f"scenarios={len(names)} " + " ".join(f"{name}={word[states[name]]}" for name in names)
    if facts:
        summary += " " + " ".join(facts)
    summary += f" checks={checks_total} problems={problems_total}"
    if failed:
        summary += " failed=" + ",".join(failed)
    if incomplete:
        summary += " incomplete=" + ",".join(incomplete)
    (WORK / "summary.json").write_text(json.dumps({"states": {n: word[s] for n, s in states.items()}, "failed": failed, "incomplete": incomplete, "html_sha256": html_sha256}, indent=1) + "\n", encoding="utf-8")
    return finish("web_smoke", max(states.values()), summary)


if __name__ == "__main__":
    sys.exit(main())
