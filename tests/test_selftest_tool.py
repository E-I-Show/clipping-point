"""道具 selftest-break（tools/selftest_break.py）の、件の回し方のテスト。件そのものは回さない（偽の回し役を渡す）。Pyxelは使わない。

見るのは、時間に頼る件（ブラウザ版の煙テスト、本番と同じ経路の run、全体の検証）と、頼らない件の分け方と、回す順：
頼らない件は、同時に何件かずつ。頼る件は、頼らない件が全部終わった後に、1件ずつ（並列に回すと、毎秒の回数や、処理時間の線が揺れる）。
件を実際に回して、壊したら落ちることは、道具 selftest-break そのものが見る。
"""
import threading

import selftest_break as selftest
from _common import load_budgets

PY = selftest.PY


def case(name: str, *cmd) -> tuple:
    """件の見本。(名, 壊し方, コマンド, 期待の終了コード, 期待の語)。"""
    return (name, [], [PY, *cmd], {0}, "OK")


# --- 時間に頼る件の判定 ---
def test_selftest_tool_web_smoke_realtime_run_and_verify_are_timed():
    assert selftest.is_timed([PY, "tools/web_smoke.py"]) is True
    assert selftest.is_timed([PY, "tools/web_smoke.py", "--only", "probe"]) is True
    assert selftest.is_timed([PY, "tools/run.py", "--realtime"]) is True
    assert selftest.is_timed([PY, "tools/verify.py", "--all"]) is True  # ブラウザ版の煙テストと、本番と同じ経路の run を含む


def test_selftest_tool_the_other_tools_are_not_timed():
    for cmd in (["tools/check.py"], ["tools/test.py"], ["tools/test.py", "-k", "fingerprint"], ["tools/run.py"], ["tools/run.py", "--pack", "extreme"],
                ["tools/tour.py"], ["tools/export.py"], ["tools/screen_check.py"], ["tools/fingerprint.py"]):
        assert selftest.is_timed([PY, *cmd]) is False, cmd


def test_selftest_tool_every_real_case_with_a_timed_tool_is_run_one_by_one():
    free, timed = selftest.split_cases(selftest.CASES)
    assert len(free) + len(timed) == len(selftest.CASES) and free and timed
    for _, _, cmd, _, _ in free:
        words = [str(word) for word in cmd]
        assert not any(word.endswith(("web_smoke.py", "verify.py")) for word in words) and "--realtime" not in words, words
    # 並びは、どちらも、元の順のまま。
    order = {entry[0]: index for index, entry in enumerate(selftest.CASES)}
    assert [order[entry[0]] for entry in free] == sorted(order[entry[0]] for entry in free)
    assert [order[entry[0]] for entry in timed] == sorted(order[entry[0]] for entry in timed)


def test_selftest_tool_case_names_are_unique():
    # 結果の行は、件の名で引く。同じ名が2つあると、片方の結果が消える。
    names = [entry[0] for entry in selftest.CASES]
    assert len(set(names)) == len(names)


def test_selftest_tool_default_number_of_jobs_is_a_positive_integer():
    jobs = load_budgets()["selftest_jobs"]
    assert type(jobs) is int and jobs >= 1


# --- 回す順 ---
class Recorder:
    """偽の回し役。件ごとに、始まりと終わりを記録し、同時に動いている件の数を数える。"""

    def __init__(self, meet: int = 0) -> None:
        self.lock = threading.Lock()
        self.active = set()
        self.max_active = 0
        self.events = []  # ("start" か "end", 名, そのときに動いていた件の名の並び)
        # meet 件が同時に始まるまで待つ柵。並列に回っていることを、時間に頼らずに確かめる（そろわなければ、時間切れで例外）。
        self.barrier = threading.Barrier(meet) if meet else None
        self.meeting = set()

    def __call__(self, entry) -> dict:
        name = entry[0]
        with self.lock:
            self.active.add(name)
            self.max_active = max(self.max_active, len(self.active))
            self.events.append(("start", name, tuple(sorted(self.active))))
        if self.barrier is not None and name in self.meeting:
            self.barrier.wait(timeout=10)
        with self.lock:
            self.active.discard(name)
            self.events.append(("end", name, tuple(sorted(self.active))))
        return {"case": name, "verdict": "ok"}


FREE = [case(f"free_{index}", "tools/check.py") for index in range(6)]
TIMED = [case("timed_web", "tools/web_smoke.py"), case("timed_verify", "tools/verify.py", "--all"), case("timed_realtime", "tools/run.py", "--realtime")]
MIXED = [FREE[0], TIMED[0], FREE[1], FREE[2], TIMED[1], FREE[3], TIMED[2], FREE[4], FREE[5]]


def test_selftest_tool_rows_come_back_in_the_order_of_the_cases():
    rows = selftest.run_cases(MIXED, 4, runner=Recorder())
    assert [row["case"] for row in rows] == [entry[0] for entry in MIXED]


def test_selftest_tool_timed_cases_start_after_every_other_case_and_run_alone():
    recorder = Recorder()
    selftest.run_cases(MIXED, 4, runner=recorder)
    timed_names = {entry[0] for entry in TIMED}
    first_timed = next(index for index, event in enumerate(recorder.events) if event[1] in timed_names)
    # 時間に頼る件より前に、頼らない件が、全部終わっている。
    ended_before = {event[1] for event in recorder.events[:first_timed] if event[0] == "end"}
    assert ended_before == {entry[0] for entry in FREE}
    # 時間に頼る件が動いている間、ほかの件は動いていない。順は、元の順。
    for kind, name, active in recorder.events[first_timed:]:
        assert name in timed_names
        assert active == ((name,) if kind == "start" else ())
    assert [event[1] for event in recorder.events[first_timed:] if event[0] == "start"] == [entry[0] for entry in TIMED]


def test_selftest_tool_untimed_cases_run_side_by_side():
    recorder = Recorder(meet=2)
    recorder.meeting = {"free_0", "free_1"}  # 2件が同時に動かないと、柵が開かない
    selftest.run_cases(FREE, 4, runner=recorder)
    assert recorder.max_active >= 2


def test_selftest_tool_one_job_runs_one_case_at_a_time():
    recorder = Recorder()
    selftest.run_cases(MIXED, 1, runner=recorder)
    assert recorder.max_active == 1


def test_selftest_tool_report_is_called_once_for_each_case():
    seen = []
    selftest.run_cases(MIXED, 4, runner=Recorder(), report=lambda row: seen.append(row["case"]))
    assert sorted(seen) == sorted(entry[0] for entry in MIXED)
