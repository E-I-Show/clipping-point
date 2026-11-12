"""起動とメインループ。決まりは docs/design/overview.md の「メインループ」。

1回の周期：入力を1度だけ読む → 更新（1 tick）→ 描画の番なら裏画面に描く → 裏画面を画面へ写す（毎回）。
入力フレームは、1 tickに1度だけ作る。台本があれば台本から、無ければ入力アダプタ（cp_app/input_pyxel.py）から。
ブラウザ版のトリガーは、直読み（cp_app/input_web.py）を先に試す。台本があるときは、入力アダプタも直読みも呼ばない。
Pyxelの描画関数を直に呼ぶのは、裏画面を消す、描画命令の実行、裏画面を画面へ写す、の3つだけ。
2Dの絵は必ず cp_ui の描画命令（Canvas）を通し、画面の組み立ては cp_ui.screens に置く。
描く画面は、画面の状態（cp_core.flow）のいまの画面の名で、画面の登録（cp_ui.screens の SCREENS）を引いて決める。
ファイルを読むときは、必ず Path(__file__) を基準にする（pyxel.init が作業ディレクトリを変える）。

画面なしで回す口（tools/run.py が使う）。環境変数が無ければ普通に起動する。ブラウザ版には環境変数が無い。
  CP_SMOKE=<結果ファイル（JSON）の絶対パス>   あれば画面なしで回し、決まったtickで終わる
  CP_SMOKE_TICKS=<回すtick数>                既定は120
  CP_SMOKE_DRIVER=flip|run                   flip：自前のループ（速い）。run：pyxel.run（本番と同じ経路）
  CP_SMOKE_SCRIPT=<台本（JSON）の絶対パス>    あれば、入力フレームを台本から作る。CP_SMOKE があるときだけ読む
結果ファイルは全tickの後にだけ書く。終了コードが0でも、結果ファイルが無ければ回り切っていない。
台本のパスが相対パス、ファイルが読めない、台本の形が違う、のどれでも、起動時に例外にする。

巡回の口（tools/tour.py が使う）。デスクトップ版で、環境変数 CP_TOUR があるときだけ動く。読む所と形は cp_app/tour.py。
  CP_TOUR、CP_TOUR_DIR、CP_TOUR_ONLY
あれば、メインループへ入らずに、見本データで画面を描いて照らし、結果ファイルを書いて終わる。CP_SMOKE とは一緒に使えない。

ブラウザ版で外から渡す値（tools/web_smoke.py が使う）。読む所と形は cp_app/web_bridge.py。
  window.CP_PROBE = {ticks, warmup_ticks, script, trace_max}
あれば、決まったtickの後に、結果の1行と完了の合図をコンソールへ出す。
値が無ければ普通に起動する。結果を出した後も終了しない（ブラウザ版では sys.exit と pyxel.quit を呼ばない）。
更新1回と実描画1回の時間は、この値があるときだけ測る（cp_app/perf.py）。測った値は世界へ渡さない。
trace_max が1以上のときだけ、入力の跡を取り（cp_app/input_trace.py）、更新のたびに tick の印（window.CP_PROBE_TICK）を置く。

保存。保存先は、起動時に main() が選ぶ（cp_app/storage_select.py）。ブラウザ版は localStorage（試し書きが通らなければメモリ）。
デスクトップ版は、どの起動でも次の環境変数を読む。相対パスは、起動時に ValueError。
  CP_SAVE_DIR=<保存のファイルの置き場の絶対パス>   あればファイル、無ければメモリ（保存は残らない）
起動時に、設定を読み込む（壊れた値の退避と、既定値での書き直しを含む）。段0では、設定を変える画面が無いので、保存はしない。
知らせの1行（保存先を切り替えた、保存が読めない）は、仮の表示に出す。一度に出すのは、多くて1つ（保存先の切り替えが先）。
保存の往復（cp_core/profile.py の selfcheck。名前空間 selfcheck）は、検証の口（CP_SMOKE、window.CP_PROBE）のときだけ回し、
結果の storage に {backend, ok, notice, detail} を入れる。notice は、最後に組み立てた表示用の値から取る。

定義データ。起動時に main() が、保存先を選んだ後に読んで、読み込み検査を通す（cp_app/data_files.py と cp_core/datadefs.py）。
問題があれば、全部を並べた例外（DataError）で止まる。デスクトップ版もブラウザ版も、巡回の口でも読む。
デスクトップ版は、どの起動でも次の環境変数を読む。ブラウザ版は読まない。
  CP_DATA_PACK=<試験用データの名>   あれば、testpacks/<名>/ を重ねる。置き場が無い、空、名の字が違う、は起動時に ValueError
重ねている間、設定を読む保存の口の名前空間は pack_<名>（main の代わり）。保存の往復の名前空間（selfcheck）は、そのまま。
結果の data に {tables, warnings, pack, namespace} を入れる。namespace は、設定を読んだ保存の口（SaveStore.namespace）から取る。

世界（Sim）は、読み込んだ定義と、車とコースの id（CAR_ID、TRACK_ID。いまは、ここの定数）から作る。Pyxelを始める前に作る
（無い id は、分かる文の例外で、ここで止まる）。仮の表示には、車の値（速度、ギア、回転数、位置、路面の種類）を2行で出す。
車の値は、世界の状態から、cp_core.flow の car_view() が作る（ここでは、小数を丸めない）。
"""
import json
import os
import sys
import time
from dataclasses import dataclass

import pyxel

from cp_core import input_script, profile
from cp_core.fixed_loop import TICK_HZ, RenderGate
from cp_core.flow import Flow, PlaceholderView, car_view
from cp_core.input_frame import NEUTRAL, InputFrame, quantize
from cp_core.sim import Sim
from cp_core.storage import SaveStore
from cp_ui.canvas import SCREEN_H, SCREEN_W, Canvas
from cp_ui.screens import COL_BACK, SCREENS, TITLE

from . import data_files, storage_select, tour, web_bridge
from .canvas_pyxel import execute
from .input_pyxel import PyxelInput
from .input_trace import InputTrace
from .input_web import TriggerReader
from .perf import PerfMeter

DRIVERS = ("flip", "run")
# 速い経路だけ、Pyxelの周期を上げて実時間の待ちを縮める。世界は fps を読まないので、結果は変わらない。
FAST_FPS = 1000
# 割り切り：世界の種は、いつも0。乱数を引く所が、まだ無い（AIのばらつきは段3）。
# レースを作る段3で、レースの通し番号と設定から決める形に見直す。
WORLD_SEED = 0
# 割り切り：車とコースは、いつも、この id（車1台、仮の周回路1本）。選ぶ画面が、まだ無い。
# 車とコースを選ぶ画面を作る段1で、選んだ id を渡す形に見直す。道具の既定（tools/input_reference.py）と、同じ値にする。
CAR_ID = "kazane"
TRACK_ID = "test_loop"


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
    def __init__(self, selected: storage_select.Selected, data, run_config: RunConfig | None = None, probe: web_bridge.Probe | None = None, js=None) -> None:
        self.run_config = run_config
        self.probe = probe  # ブラウザ版で外から渡された、回すtick数などの指定。無ければ None
        self.js = js  # ブラウザの機能（js のモジュール）。デスクトップ版では None
        self.probe_reported = False
        # 読み込んだ定義（cp_core.datadefs の GameData）。読み込み検査は、main() で済んでいる。
        self.data = data
        # 世界。読み込んだ定義と、車とコースの id から作る（定義は、世界が、ここで1度だけ引く）。無い id は、分かる文の例外で、ここで止まる。
        self.sim = Sim(WORLD_SEED, data, CAR_ID, TRACK_ID)
        # 保存。選んだ保存先（selected）から、設定を読み込む。壊れた値の退避と、既定値での書き直しは、読み込みの中で済む。
        self.storage_name = selected.name  # 保存先の名。結果に入れる
        # 設定を読む保存の口。名前空間は、読み込んだ定義から取る（試験用データを重ねている間は pack_<名>。ふだんの保存に触れない）。
        self.store = SaveStore(selected.backend, data.save_namespace)
        loaded = profile.load_settings(self.store)
        self.settings = loaded.settings  # 設定。使う所（音、変速、アシスト、視点）は、段1から作る
        # 知らせの1行。一度に出すのは、多くて1つ。保存先の切り替えを先にする。仮の表示に出す。
        self.notice = selected.notice or loaded.notice
        # 保存の往復は、検証の口のときだけ回す（名前空間 selfcheck。ふつうの鍵には触れない）。返るのは (通ったか, 失敗の理由)。
        self.storage_check = profile.selfcheck(selected.backend) if run_config is not None or probe is not None else None
        self.view = None  # 最後に組み立てた表示用の値。結果の知らせは、ここから取る
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
        self.flow = Flow()  # 画面の状態。いまの画面の名を持つ
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

    # --- 保存 ---
    def storage_report(self) -> dict:
        """結果に足す、保存先の名、保存の往復の結果、知らせの1行。

        notice は、最後に組み立てた表示用の値から取る（アプリが持つ知らせを、直に入れない）。
        表示用の値へ渡し忘れると、ここが空になり、道具（保存先に触れると例外になる筋書き）で落ちる。
        """
        ok, detail = self.storage_check if self.storage_check is not None else (False, "the round trip was not run")
        notice = self.view.notice if self.view is not None else ""
        return {"backend": self.storage_name, "ok": ok, "notice": notice, "detail": detail}

    # --- 定義データ ---
    def data_report(self) -> dict:
        """結果に足す、表ごとの件数、警告の数、重ねた試験用データの名（無ければ None）、保存の名前空間。

        namespace は、設定を読んだ保存の口から取る（読み込んだ定義の側の値を、直に入れない）。
        保存の口へ名前空間を渡し忘れると、ここが main になり、道具（試験用データを重ねて回す手順）で落ちる。
        """
        return {"tables": self.data.counts(), "warnings": len(self.data.warnings), "pack": self.data.pack, "namespace": self.store.namespace}

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
        # 表示用の値。実描画の回数は、表示にだけ使う（世界へは渡さない）。車の値は、世界の状態から作る。
        view = PlaceholderView(self.sim.tick, self.renders, self.frame, self.notice, car_view(self.sim))
        self.view = view
        SCREENS[self.flow.screen](canvas, view)
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
            "storage": self.storage_report(),
            "data": self.data_report(),
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
            "storage": self.storage_report(),
            "data": self.data_report(),
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
    # 保存先を選ぶ。ブラウザ版は、ここで試し書きをする。デスクトップ版は、どの起動でも CP_SAVE_DIR を読む
    # （巡回の口でも読む。相対パスは、ここで ValueError）。
    selected = storage_select.select(js, os.environ)
    # 定義データを読んで、読み込み検査を通す。問題があれば、全部を並べた例外（DataError）で、ここで止まる（巡回の口でも読む）。
    # デスクトップ版は、どの起動でも CP_DATA_PACK を読む（試験用データを重ねる。置き場が無ければ、ここで ValueError）。
    data = data_files.load(os.environ, js)
    # 巡回の口。デスクトップ版で、CP_TOUR があるときだけ。ブラウザ版では読まない。
    tour_config = tour.read_config(os.environ) if js is None else None
    if tour_config is not None:
        tour.run(pyxel, tour_config)
        # pyxel.quit() は常に終了コード0で終わり、失敗を消すので使わない。
        sys.exit(0)
    App(selected, data, read_run_config(os.environ), web_bridge.read_probe(js), js).run()
