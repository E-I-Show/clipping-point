"""起動とメインループ。決まりは docs/design/overview.md の「メインループ」。

1回の周期：更新（1 tick）→ 描画の番なら裏画面に描く → 裏画面を画面へ写す（毎回）。
Pyxelの描画関数を直に呼ぶのは、裏画面を消す、描画命令の実行、裏画面を画面へ写す、の3つだけ。
2Dの絵は必ず cp_ui の描画命令（Canvas）を通し、画面の組み立ては cp_ui.screens に置く。
ファイルを読むときは、必ず Path(__file__) を基準にする（pyxel.init が作業ディレクトリを変える）。

画面なしで回す口（tools/run.py が使う）。環境変数が無ければ普通に起動する。ブラウザ版には環境変数が無い。
  CP_SMOKE=<結果ファイル（JSON）の絶対パス>   あれば画面なしで回し、決まったtickで終わる
  CP_SMOKE_TICKS=<回すtick数>                既定は120
  CP_SMOKE_DRIVER=flip|run                   flip：自前のループ（速い）。run：pyxel.run（本番と同じ経路）
結果ファイルは全tickの後にだけ書く。終了コードが0でも、結果ファイルが無ければ回り切っていない。
"""
import json
import os
import sys
import time
from dataclasses import dataclass

import pyxel

from cp_core.fixed_loop import TICK_HZ, RenderGate
from cp_core.sim import Sim
from cp_ui.canvas import SCREEN_H, SCREEN_W, Canvas
from cp_ui.screens import COL_BACK, TITLE, build_placeholder

from .canvas_pyxel import execute

DRIVERS = ("flip", "run")
# 速い経路だけ、Pyxelの周期を上げて実時間の待ちを縮める。世界は fps を読まないので、結果は変わらない。
FAST_FPS = 1000


@dataclass(frozen=True)
class RunConfig:
    """画面なしで回すときの指定（結果ファイル、tick数、回す経路）。"""

    result_path: str
    ticks: int
    driver: str


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
    return RunConfig(result_path, ticks, driver)


class App:
    def __init__(self, run_config: RunConfig | None = None) -> None:
        self.run_config = run_config
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
        self.sim = Sim()
        self.gate = RenderGate()
        self.back = pyxel.Image(SCREEN_W, SCREEN_H)  # 裏画面。3DとHUDに当たる絵はここへ描く
        self.back.cls(COL_BACK)
        self.ticks = 0  # 回した更新の数
        self.renders = 0  # 実描画の回数
        self.done = False
        self.loop = ""  # 実際に入ったループ（"flip" か "run"）。結果ファイルに書く
        self.started_s = time.perf_counter()

    # --- 毎秒60回 ---
    def update(self) -> None:
        self.sim.step()
        self.gate.on_tick()
        self.ticks += 1
        config = self.run_config
        if config is not None and self.ticks >= config.ticks:
            self.finish_run(config)

    # --- Pyxelが毎周期呼ぶ。実描画は毎秒30回に間引く ---
    def draw(self) -> None:
        # 実時間は見た目の判断（間引き）にだけ使う。世界へは渡さない。
        if self.gate.should_render(time.perf_counter() * 1000.0):
            self.renders += 1
            self.render()
        # 裏画面を画面へ写すのは毎回。描かない周期でも、Pyxelが性能表示とカーソルを画面に描き足すため。
        pyxel.blt(0, 0, self.back, 0, 0, SCREEN_W, SCREEN_H)

    def render(self) -> None:
        canvas = Canvas()
        build_placeholder(canvas, self.sim.tick, self.renders)
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
    App(read_run_config(os.environ)).run()
