"""実描画の間引き（RenderGate）のテスト。Pyxelは使わない。"""
import ast

import pytest

from conftest import ROOT
from cp_core.fixed_loop import RENDER_DIVISOR, RENDER_HZ, RENDER_MIN_INTERVAL_MS, TICK_HZ, RenderGate

APP_PY = ROOT / "clipping_point" / "cp_app" / "app.py"


def test_fixed_loop_app_passes_real_time_to_the_gate():
    # 守りのテスト。アプリの draw() が、should_render に実時間を渡していること。ソースを読むだけで、pyxel は読み込まない。
    # 引数を落としても例外にならず（既定は None）、デスクトップ版の道具も、ブラウザ版の煙テストも通ってしまう。差が出るのは、
    # 実描画のある周期が、1 tickの長さ（16.7 ms）を超えるときだけ。段0 区切り10で載った走行の場面では、超えるのは、
    # ブラウザ版の600〜840 tickに0〜1回（実測。結果の perf の cycles_over_tick）で、実描画の回数には、出ない。
    # 見るのは「引数が1つある」ことだけ。実描画が重い場面ができた段で、煙テストの実描画の回数で見える形に置き換えるかを、見直す。
    tree = ast.parse(APP_PY.read_text(encoding="utf-8"))
    draws = [
        node
        for cls in ast.walk(tree)
        if isinstance(cls, ast.ClassDef) and cls.name == "App"
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "draw"
    ]
    assert len(draws) == 1

    def gate_calls(scope):
        return [
            node
            for node in ast.walk(scope)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "should_render"
        ]

    assert len(gate_calls(draws[0])) == 1
    assert all(len(call.args) + len(call.keywords) == 1 for call in gate_calls(tree))


def drive_gate(pattern: str, divisor: int = 2) -> list:
    """pattern の 'U' は更新1回、'D' は描画の呼び出し1回。実描画が走ったときのtick数の並びを返す。"""
    gate = RenderGate(divisor)
    tick = 0
    rendered_at = []
    for ch in pattern:
        if ch == "U":
            gate.on_tick()
            tick += 1
        elif gate.should_render():
            rendered_at.append(tick)
    return rendered_at


def test_fixed_loop_constants_match_the_design():
    assert (TICK_HZ, RENDER_HZ, RENDER_DIVISOR) == (60, 30, 2)
    assert RENDER_MIN_INTERVAL_MS == 30.0


def test_fixed_loop_renders_30_times_per_second_at_normal_pace():
    # ふつうの進み方：更新1回につき描画の呼び出しが1回。60 tick（1秒）で実描画は30回。
    rendered = drive_gate("UD" * TICK_HZ)
    assert len(rendered) == RENDER_HZ
    assert all(b - a == 2 for a, b in zip(rendered, rendered[1:]))


def test_fixed_loop_renders_30_times_per_second_with_real_time_at_60hz():
    # 実時間を渡しても、毎秒60回の進み方では実時間の決まりは働かず、30回のまま。
    gate = RenderGate()
    rendered = 0
    for i in range(TICK_HZ):
        gate.on_tick()
        rendered += gate.should_render(i * 1000.0 / TICK_HZ)
    assert rendered == RENDER_HZ


def test_fixed_loop_first_draw_renders():
    gate = RenderGate()
    gate.on_tick()
    assert gate.should_render()


def test_fixed_loop_keeps_rendering_while_pyxel_catches_up():
    # 処理落ちから追い付く間、Pyxelは描画1回につき更新を2回呼ぶ（実測：U D UUD UUD …）。
    # どの描画の呼び出しでも実描画が走り、0回にならない。
    rendered = drive_gate("UD" + "UUD" * 59)
    assert len(rendered) == 60


@pytest.mark.parametrize("pattern", ["UD" + "UUUD" * 20, "UD" + "UUD" * 5 + "UD" * 9 + "UUUUUD" * 4])
def test_fixed_loop_never_starves_under_irregular_patterns(pattern):
    rendered = drive_gate(pattern)
    assert rendered, "実描画が0回なら不合格"
    longest_run = max(len(run) for run in pattern.split("D"))
    assert max(b - a for a, b in zip(rendered, rendered[1:])) <= max(2, longest_run) + 1


def test_fixed_loop_parity_gate_would_render_nothing_under_catch_up():
    """落とし穴を残しておく：フレーム番号の偶奇で間引くと、追い付く間に1度も描かれない。"""
    frame_count = 0
    renders = 0
    # Pyxel：余分な更新のたびにフレーム番号が進み、最後の更新と描画は同じ番号を見る。
    for updates in [1] + [2] * 59:
        frame_count += updates - 1
        if frame_count % 2 == 1:
            renders += 1
        frame_count += 1
    assert renders == 0
    # 同じ進み方で、RenderGate は描画の呼び出しのたびに描く。
    assert len(drive_gate("UD" + "UUD" * 59)) == 60


def test_fixed_loop_time_rule_recovers_30fps_in_the_browser_lag_pattern():
    # ブラウザ版：遅れた周期は1つ後の呼び出しで知らされる。(呼び出しの時刻 ms, その回の更新の数)
    calls = [(0.0, 1), (33.3, 1), (66.7, 2), (100.0, 2), (133.3, 2)]
    gate = RenderGate()  # アプリと同じ、既定の引数で作る。既定から実時間の決まりが外れたら、ここで落ちる
    rendered = []
    for now_ms, ticks in calls:
        for _ in range(ticks):
            gate.on_tick()
        rendered.append(gate.should_render(now_ms))
    assert rendered == [True, True, True, True, True]


def test_fixed_loop_tick_rule_alone_skips_a_late_frame():
    # 実時間の決まりを切ると、2つ目の呼び出しが飛ぶ（毎秒20回に落ち着く形）。
    gate = RenderGate(2, None)
    rendered = []
    for now_ms, ticks in [(0.0, 1), (33.3, 1), (50.0, 2)]:
        for _ in range(ticks):
            gate.on_tick()
        rendered.append(gate.should_render(now_ms))
    assert rendered == [True, False, True]


def test_fixed_loop_time_rule_does_not_fire_on_a_75hz_display():
    # 75 Hzの画面では、周期の間が13.3 msと26.7 msになる。26.7 msでは実時間の決まりを働かせない。
    gate = RenderGate(2, 30.0)
    gate.on_tick()
    assert gate.should_render(0.0)
    gate.on_tick()
    assert not gate.should_render(26.7)


def test_fixed_loop_never_renders_again_without_a_new_tick():
    # 新しいtickが無ければ、どれだけ時間がたっても同じ絵を描き直さない。
    gate = RenderGate(2, 30.0)
    gate.on_tick()
    assert gate.should_render(0.0)
    assert not gate.should_render(500.0)
    assert not gate.should_render()


def test_fixed_loop_uses_only_the_tick_rule_when_no_time_is_given():
    # 実時間は引数でだけ受ける。渡さなければ、tickの決まりだけで決まる。
    gate = RenderGate(2, 30.0)
    rendered = []
    for _ in range(6):
        gate.on_tick()
        rendered.append(gate.should_render())
    assert rendered == [True, False, True, False, True, False]


def test_fixed_loop_time_rule_needs_30ms_since_the_last_render():
    # 1 tickたっていても、前回の実描画から30 ms未満なら描かない。30 ms以上なら描く。
    gate = RenderGate()  # アプリと同じ、既定の引数で作る
    gate.on_tick()
    assert gate.should_render(100.0)
    gate.on_tick()
    assert not gate.should_render(129.9)
    assert gate.should_render(130.0)


def test_fixed_loop_rejects_a_divisor_below_one():
    with pytest.raises(ValueError):
        RenderGate(0)
