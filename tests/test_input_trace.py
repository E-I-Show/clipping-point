"""入力の跡（cp_app.input_trace）のテスト。変わり目だけを取ること、打ち切り、戻した列が元と同じこと。Pyxelは使わない。"""
import json

import pytest

import input_reference
from cp_app.input_trace import InputTrace, expand
from cp_core.input_frame import InputFrame, quantize

ZERO = (0, 0, 0, 0, 0, 0, 0, 0)
A = (500, 0, 0, 0, 0, 0, 0, 0)
B = (500, 0, 300, 0, 0, 0, 1, 1)


def trace_of(rows, max_changes=100) -> dict:
    trace = InputTrace(max_changes)
    for tick, row in enumerate(rows):
        trace.on_tick(tick, row)
    return trace.report()


# --- 変わり目だけを取る ---
def test_input_trace_keeps_only_the_ticks_where_the_values_changed():
    report = trace_of([ZERO, ZERO, A, A, A, B, ZERO, ZERO])
    assert report == {"changes": [[0, list(ZERO)], [2, list(A)], [5, list(B)], [6, list(ZERO)]], "truncated": False}


def test_input_trace_always_has_tick_zero_even_when_nothing_is_pressed():
    assert trace_of([ZERO] * 50) == {"changes": [[0, list(ZERO)]], "truncated": False}


def test_input_trace_before_the_first_tick_is_empty():
    assert InputTrace(10).report() == {"changes": [], "truncated": False}


def test_input_trace_report_is_plain_json_data():
    report = trace_of([ZERO, A, B])
    assert json.loads(json.dumps(report)) == report
    assert all(type(value) is int for _, values in report["changes"] for value in values)


def test_input_trace_report_is_a_copy():
    trace = InputTrace(10)
    trace.on_tick(0, ZERO)
    report = trace.report()
    report["changes"][0][1][0] = 999
    report["changes"].append([1, list(A)])
    assert trace.report() == {"changes": [[0, list(ZERO)]], "truncated": False}


def test_input_trace_takes_the_quantized_frames_as_they_are():
    frame = InputFrame(steer_analog=-0.5, throttle_digital=1, held=frozenset({"up"}), pressed=frozenset({"up"}))
    assert trace_of([quantize(frame)])["changes"] == [[0, list(quantize(frame))]]


# --- 打ち切り ---
def test_input_trace_stops_at_the_limit_and_says_so():
    rows = [ZERO, A, B, ZERO, A, B]
    report = trace_of(rows, max_changes=3)
    assert report == {"changes": [[0, list(ZERO)], [1, list(A)], [2, list(B)]], "truncated": True}


def test_input_trace_reaching_the_limit_exactly_counts_as_truncated():
    # 件数が上限に届いたら、打ち切り。後ろに変わり目があったかどうかは、もう分からない。
    assert trace_of([ZERO, A, B], max_changes=3)["truncated"] is True
    assert trace_of([ZERO, A, B], max_changes=4)["truncated"] is False


def test_input_trace_takes_nothing_after_it_is_truncated():
    trace = InputTrace(1)
    trace.on_tick(0, ZERO)
    assert trace.truncated is True
    for tick, row in enumerate([A, B, ZERO, A], start=1):
        trace.on_tick(tick, row)
    assert trace.report() == {"changes": [[0, list(ZERO)]], "truncated": True}


@pytest.mark.parametrize("bad", [0, -1, True, 1.5, "3", None])
def test_input_trace_limit_must_be_a_positive_integer(bad):
    with pytest.raises(ValueError):
        InputTrace(bad)


# --- 戻す ---
def test_input_trace_expand_gives_back_the_rows_tick_by_tick():
    rows = [ZERO, ZERO, A, A, A, B, ZERO, ZERO]
    assert expand(trace_of(rows), len(rows)) == rows


def test_input_trace_expand_of_the_smoke_script_is_the_script():
    # 道具の台本を、入力フレームへ直して量子化した列。台本を過ぎた後の、何も押していないtickも入れる。
    _, script = input_reference.load_script(input_reference.SMOKE_SCRIPT)
    rows = input_reference.quantized_rows(script, script.total_ticks + 20)
    report = trace_of(rows)
    assert 2 < len(report["changes"]) < len(rows)
    assert expand(json.loads(json.dumps(report)), len(rows)) == rows


def test_input_trace_expand_repeats_the_last_values_to_the_end():
    assert expand({"changes": [[0, list(A)]], "truncated": False}, 4) == [A, A, A, A]
    assert expand({"changes": [[0, list(ZERO)], [3, list(B)]], "truncated": False}, 4) == [ZERO, ZERO, ZERO, B]


def test_input_trace_expand_refuses_a_truncated_trace():
    # 打ち切られた跡は、最後の値が続いたのか、取っていないのかを見分けられない。
    report = trace_of([ZERO, A, B, ZERO], max_changes=2)
    assert report["truncated"] is True
    with pytest.raises(ValueError):
        expand(report, 4)


@pytest.mark.parametrize(
    "report",
    [
        None,
        [],
        {},
        {"changes": [[0, list(ZERO)]]},  # truncated が無い
        {"changes": [[0, list(ZERO)]], "truncated": None},
        {"changes": [[0, list(ZERO)]], "truncated": 0},
        {"changes": [], "truncated": False},  # 頭のtick 0は必ず入る
        {"changes": None, "truncated": False},
        {"changes": [[1, list(ZERO)]], "truncated": False},  # 頭がtick 0でない
        {"changes": [[0, list(ZERO)], [0, list(A)]], "truncated": False},  # tickが増えていない
        {"changes": [[0, list(ZERO)], [3, list(A)], [2, list(B)]], "truncated": False},
        {"changes": [[0, list(ZERO)], [10, list(A)]], "truncated": False},  # 回したtickの外
        {"changes": [[0, list(ZERO)], [-1, list(A)]], "truncated": False},
        {"changes": [[0, list(ZERO)], [2.0, list(A)]], "truncated": False},
        {"changes": [[0, list(ZERO)], [True, list(A)]], "truncated": False},
        {"changes": [[0, [0] * 7]], "truncated": False},  # 値が8個でない
        {"changes": [[0, [0] * 9]], "truncated": False},
        {"changes": [[0, [0.5] + [0] * 7]], "truncated": False},
        {"changes": [[0, [True] + [0] * 7]], "truncated": False},
        {"changes": [[0, tuple(ZERO)]], "truncated": False},  # JSONから読んだ形（並び）でない
        {"changes": [[0]], "truncated": False},
        {"changes": [0], "truncated": False},
        {"changes": [[0, list(ZERO), "extra"]], "truncated": False},
    ],
)
def test_input_trace_expand_refuses_a_trace_of_the_wrong_shape(report):
    with pytest.raises(ValueError):
        expand(report, 10)


def test_input_trace_expand_needs_at_least_one_tick():
    with pytest.raises(ValueError):
        expand({"changes": [[0, list(ZERO)]], "truncated": False}, 0)
