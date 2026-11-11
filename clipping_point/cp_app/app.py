"""起動とメインループ。決まりは docs/design/overview.md の「メインループ」。

1回の周期：入力を1度だけ読む → 更新（1 tick）→ 描画の番なら裏画面に描く → 裏画面を画面へ写す（毎回）。
入力フレームは、1 tickに1度だけ作る。台本があれば台本から、無ければ入力アダプタ（cp_app/input_pyxel.py）から。
ブラウザ版のトリガーは、直読み（cp_app/input_web.py）を先に試す。台本があるときは、入力アダプタも直読みも呼ばない。
Pyxelの描画関数を直に呼ぶのは、裏画面を消す、描画命令の実行、裏画面を画面へ写す、の3つだけ。
2Dの絵は必ず cp_ui の描画命令（Canvas）を通し、画面の組み立ては cp_ui.screens に置く。
ファイルを読むときは、必ず Path(__file__) を基準にする（pyxel.init が作業ディレクトリを変える）。

画面なしで回す口（tools/run.py が使う）。環境変数が無ければ普通に起動する。ブラウザ版には環境変数が無い。
  CP_SMOKE=<結果ファイル（JSON）の絶対パス>   あれば画面なしで回し、決まったtickで終わる
  CP_SMOKE_TICKS=<回すtick数>                既定は120
  CP_SMOKE_DRIVER=flip|run                   flip：自前のループ（速い）。run：pyxel.run（本番と同じ経路）
  CP_SMOKE_SCRIPT=<台本（JSON）の絶対パス>    あれば、入力フレームを台本から作る。CP_SMOKE があるときだけ読む
結果ファイルは全tickの後にだけ書く。終了コードが0でも、結果ファイルが無ければ回り切っていない。
台本のパスが相対パス、ファイルが読めない、台本の形が違う、のどれでも、起動時に例外にする。

ブラウザ版で外から渡す値（tools/web_smoke.py が使う）。読む所と形は cp_app/web_bridge.py。
  window.CP_PROBE = {ticks, warmup_ticks, script, trace_max}
あれば、決まったtickの後に、結果の1行と完了の合図をコンソールへ出す。
値が無ければ普通に起動する。結果を出した後も終了しない（ブラウザ版では sys.exit と pyxel.quit を呼ばない）。
更新1回と実描画1回の時間は、この値があるときだけ測る（cp_app/perf.py）。測った値は世界へ渡さない。
trace_max が1以上のときだけ、入力の跡を取り（cp_app/input_trace.py）、更新のたびに tick の印（window.CP_PROBE_TICK）を置く。
"""
import json
import os
import sys
import time
from dataclasses import dataclass

import pyxel

from cp_core import input_script
from cp_core.fixed_loop import TICK_HZ, RenderGate
from cp_core.input_frame import NEUTRAL, InputFrame, quantize
from cp_core.sim import Sim
from cp_ui.canvas import SCREEN_H, SCREEN_W, Canvas
from cp_ui.screens import COL_BACK, TITLE, build_placeholder

from . import web_bridge
from .canvas_pyxel import execute
from .input_pyxel import PyxelInput
from .input_trace import InputTrace
from .input_web import TriggerReader
from .perf import PerfMeter

DRIVERS = ("flip", "run")
# 速い経路だけ、Pyxelの周期を上げて実時間の待ちを縮める。世界は fps を読まないので、結果は変わらない。
FAST_FPS = 1000


@dataclass(frozen=True)
class RunConfig:
    """画面なしで回すときの指定（結果ファイル、tick数、回す経路、台本）。"""

    result_path: str
    ticks: int
    driver: str
    script: input_script.InputScript | None = None  # 台本。無ければ、入力アダプタから読む


def read_run_config(env) -> RunConfig | None:
    """環境変数から、画面なしで回す指定を読む。CP_SMOKE が無ければ None（普通の起動）。"""
    result_path = env.get("CP_SMOKE", "")
    if not result_path:
        return None
    if not os.path.isabs(result_path):
        raise ValueError("CP_SMOKE must be an absolute path (pyxel.init changes the working directory)")
    ticks = int(env.get("CP_SMOKE_TICKS", "120"))
    if ticks < 1:
        raise ValueError("CP_SMOKE_TICKS must be >= 1")
    driver = env.get("CP_SMOKE_DRIVER", "flip")
    if driver not in DRIVERS:
        raise ValueError(f"CP_SMOKE_DRIVER must be one of {DRIVERS}, got {driver!r}")
    script = None
    script_path = env.get("CP_SMOKE_SCRIPT", "")
    if script_path:
        if not os.path.isabs(script_path):
            raise ValueError("CP_SMOKE_SCRIPT must be an absolute path (pyxel.init changes the working directory)")
        with open(script_path, encoding="utf-8") as f:
            script = input_script.parse(json.load(f))  # 読めない、形が違う、は起動時に例外
    return RunConfig(result_path, ticks, driver, script)


class App:
    def __init__(self, run_config: RunConfig | None = None, probe: web_bridge.Probe | None = None, js=None) -> None:
        self.run_config = run_config
        self.probe = probe  # ブラウザ版で外から渡された、回すtick数などの指定。無ければ None
        self.js = js  # ブラウザの機能（js のモジュール）。デスクトップ版では None
        self.probe_reported = False
        # 処理時間は、外から回すtick数を渡されたときだけ測る。世界（Sim）へは渡さない。
        self.meter = PerfMeter(probe.warmup_ticks) if probe is not None else None
        # 入力の跡も、外から頼まれたときだけ取る。世界（Sim）へは渡さない。
        self.trace = InputTrace(probe.trace_max) if probe is not None and probe.trace_max >= 1 else None
        # 台本。デスクトップ版は環境変数から、ブラウザ版は外から渡す値から。無ければ、入力アダプタから読む。
        self.script = run_config.script if run_config is not None else probe.script if probe is not None else None
        self.script_reads = 0  # 台本から入力フレームを作った回数
        self.frame = NEUTRAL  # 直近の入力フレーム。仮の表示に出す
        fast = run_config is not None and run_config.driver == "flip"
        pyxel.init(
            SCREEN_W,
            SCREEN_H,
            title=TITLE,
            fps=FAST_FPS if fast else TICK_HZ,  # 更新1回が1 tick
            quit_key=pyxel.KEY_NONE,  # Escで終了させない。ブラウザ版で終了すると戻れない
            capture_sec=0,  # 画面の録画は切る。既定のままだと直近10秒分の画面を常に持つ
            headless=run_config is not None,
        )
        pyxel.integer_scale(True)  # 拡大は整数倍にする
        self.adapter = PyxelInput(pyxel)  # 入力アダプタ。割り当ての表の名前を、ここ（起動時）で全部引く
        self.triggers = TriggerReader(js)  # 直読み。デスクトップ版では、いつも None を返す
        self.sim = Sim()
        self.gate = RenderGate()
        self.back = pyxel.Image(SCREEN_W, SCREEN_H)  # 裏画面。3DとHUDに当たる絵はここへ描く
        self.back.cls(COL_BACK)
        self.ticks = 0  # 回した更新の数
        self.renders = 0  # 実描画の回数
        self.done = False
        self.loop = ""  # 実際に入ったループ（"flip" か "run"）。結果ファイルに書く
        self.started_s = time.perf_counter()

    # --- 入力 ---
    def read_frame(self) -> InputFrame:
        """このtickの入力フレームを作る。1 tickに1度だけ呼ぶ。台本があれば台本から、無ければ入力アダプタから。"""
        if self.script is not None:
            self.script_reads += 1
            return self.script.frame_at(self.sim.tick)
        return self.adapter.read(self.js is not None, self.triggers.read())

    def input_report(self) -> dict:
        """結果に足す、入力の出どころと、読んだ回数。指定ではなく、実際に読んだ所を書く。

        adapter_reads は入力アダプタ、direct_reads は直読みを呼んだ回数。どちらも、台本のときは0、
        入力アダプタから読むときは回したtickと同じになる（1 tickに1度）。
        """
        adapter_reads = self.adapter.reads
        if self.script_reads and adapter_reads:
            source = "mixed"
        elif self.script_reads:
            source = "script"
        else:
            source = "adapter" if adapter_reads else "none"
        return {"input_source": source, "adapter_reads": adapter_reads, "direct_reads": self.triggers.reads}

    # --- 毎秒60回 ---
    def update(self) -> None:
        started_s = time.perf_counter()
        frame = self.read_frame()
        self.frame = frame
        self.sim.step(frame)
        if self.trace is not None:
            self.trace.on_tick(self.ticks, quantize(frame))
        self.gate.on_tick()
        self.ticks += 1
        if self.trace is not None:
            # tick の印。偽のコントローラーが、これを見て予定を進める。
            web_bridge.mark_tick(self.js, self.ticks)
        if self.meter is not None:
            self.meter.on_update(started_s, time.perf_counter())
        config = self.run_config
        if config is not None and self.ticks >= config.ticks:
            self.finish_run(config)
        probe = self.probe
        if probe is not None and not self.probe_reported and self.ticks >= probe.ticks:
            self.finish_probe()

    # --- Pyxelが毎周期呼ぶ。実描画は毎秒30回に間引く ---
    def draw(self) -> None:
        # 実時間は見た目の判断（間引き）にだけ使う。世界へは渡さない。
        if self.gate.should_render(time.perf_counter() * 1000.0):
            self.renders += 1
            started_s = time.perf_counter()
            self.render()
            if self.meter is not None:
                self.meter.on_render(started_s, time.perf_counter())
        # 裏画面を画面へ写すのは毎回。描かない周期でも、Pyxelが性能表示とカーソルを画面に描き足すため。
        pyxel.blt(0, 0, self.back, 0, 0, SCREEN_W, SCREEN_H)

    def render(self) -> None:
        canvas = Canvas()
        build_placeholder(canvas, self.sim.tick, self.renders, self.frame)
        self.back.cls(COL_BACK)
        execute(canvas.commands, self.back)

    # --- 画面なしで回す口 ---
    def finish_run(self, config: RunConfig) -> None:
        """全tickの後に1度だけ呼ぶ。結果ファイルを書く。"""
        back_ink = 0  # 裏画面で、背景色と違う画素の数
        screen_diff = 0  # 画面と裏画面で、色が違う画素の数
        for y in range(SCREEN_H):
            for x in range(SCREEN_W):
                col = self.back.pget(x, y)
                back_ink += col != COL_BACK
                screen_diff += col != pyxel.pget(x, y)
        result = {
            "ticks": self.ticks,
            "renders": self.renders,
            "sim": self.sim.summary(),
            "back_ink": back_ink,
            "screen_diff": screen_diff,
            "driver": self.loop,  # 指定された経路ではなく、実際に入ったループ
            **self.input_report(),
            "wall_s": round(time.perf_counter() - self.started_s, 3),
            "python": sys.version.split()[0],
            "pyxel": pyxel.VERSION,
        }
        tmp_path = config.result_path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1, sort_keys=True)
        os.replace(tmp_path, config.result_path)
        self.done = True
        if config.driver == "run":
            # pyxel.run の中から抜ける。pyxel.quit() は常に終了コード0で終わり、失敗を消すので使わない。
            sys.exit(0)

    # --- ブラウザ版で、外から回すtick数を渡されたときの口 ---
    def finish_probe(self) -> None:
        """決まったtickの後に1度だけ呼ぶ。結果の1行と完了の合図をコンソールへ出す。終了はしない。"""
        self.probe_reported = True
        result = {
            "ticks": self.ticks,
            "renders": self.renders,
            "sim": self.sim.summary(),
            "warmup_ticks": self.probe.warmup_ticks,
            "perf": self.meter.report(),
            **self.input_report(),
            "platform": sys.platform,
            "python": sys.version.split()[0],
            "pyxel": pyxel.VERSION,
        }
        if self.trace is not None:
            result["inputs"] = self.trace.report()  # 入力の跡
        web_bridge.emit_result(self.js, result)

    def run(self) -> None:
        config = self.run_config
        if config is not None and config.driver == "flip":
            # 自前のループ。デスクトップ版だけで使う（ブラウザ版に pyxel.flip は無い）。
            self.loop = "flip"
            while not self.done:
                self.update()
                self.draw()
                pyxel.flip()
            return
        self.loop = "run"
        pyxel.run(self.update, self.draw)


def main() -> None:
    js = web_bridge.browser_js(sys.platform)  # デスクトップ版では None
    App(read_run_config(os.environ), web_bridge.read_probe(js), js).run()
