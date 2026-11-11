"""デスクトップ版を、画面なしで決まったtickだけ別プロセスで回す。

  python3 tools/run.py [--ticks N] [--realtime] [--script FILE | --no-script] [--timeout 秒]

  既定        速い経路。アプリ自前のループ（pyxel.flip）で回す。入力は、道具の台本（tools/input_script_smoke.json）
  --realtime  本番と同じ経路。pyxel.run で実時間（毎秒60回）で回す。台本を渡さず、入力アダプタを実物のPyxelで毎tick呼ぶ
  --script FILE  この台本（JSON）を渡す。どちらの経路でも使える
  --no-script    台本を渡さない（入力アダプタから読む）。どちらの経路でも使える

終了コード：0＝合格、1＝回ったが合わない、2＝全tickを回り切れない（時間切れ、結果ファイルが無い）・
台本が読めない・回すtick数が台本の合計より短い。
アプリの終了コードが0でも、それだけでは合格にしない。pyxel.quit() は常に0で終わるため。
失敗にする条件：アプリの終了コード、結果ファイルが無い、回したtickが違う、世界のtickが違う、
実描画の回数が範囲の外（tickの半分の前後）、裏画面が空、画面が裏画面と違う、回した経路が違う、
入力の出どころが違う（台本か入力アダプタか）、入力アダプタを呼んだ回数と、直読みを呼んだ回数が違う
（どちらも、台本なら0、入力アダプタなら回したtickと同じ。直読みは、デスクトップ版では値を返さないが、呼んだ回数は数える）、
世界の要約が参照（tools/input_reference.py。台本なしなら、何も押していない入力）と違う。
指紋、3Dが描かれていること、左右の向き、保存の往復は、後の区切りで足す（最後の1行の not_yet）。
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import input_reference
from _common import APP, FAIL, INCOMPLETE, OK, OUT, child_env, finish, load_budgets, run, show_tail

NOT_YET = ("fingerprint", "scene3d", "mirror", "save")  # 後の区切りで足す確かめ


def main() -> int:
    ap = argparse.ArgumentParser(description="デスクトップ版を画面なしで回す")
    ap.add_argument("--ticks", type=int, default=120)
    ap.add_argument("--realtime", action="store_true", help="pyxel.run で実時間で回す（本番と同じ経路）")
    choice = ap.add_mutually_exclusive_group()
    choice.add_argument("--script", default=None, metavar="FILE", help="渡す台本（JSON）。既定は、速い経路だけ tools/input_script_smoke.json")
    choice.add_argument("--no-script", action="store_true", help="台本を渡さない（入力アダプタから読む）")
    ap.add_argument("--timeout", type=float, default=None, help="秒。既定は tick数から決める")
    args = ap.parse_args()
    driver = "run" if args.realtime else "flip"
    if args.no_script:
        script_path = None
    elif args.script is not None:
        script_path = Path(args.script).resolve()  # アプリには絶対パスで渡す（pyxel.init が作業ディレクトリを変える）
    else:
        script_path = None if args.realtime else input_reference.SMOKE_SCRIPT
    want_source = "adapter" if script_path is None else "script"
    head = f"driver={driver} input={want_source} ticks_wanted={args.ticks}"
    tolerance = load_budgets()["run_renders_tolerance"]
    # 実描画が0回でも幅の中に入ってしまう短さでは、判定にならない。
    min_ticks = 2 * (tolerance + 1)
    if args.ticks < min_ticks:
        return finish("run", INCOMPLETE, f"{head} reason=too_few_ticks min={min_ticks}")
    script = None
    if script_path is not None:
        try:
            _, script = input_reference.load_script(script_path)
        except ValueError as exc:
            print(f"  run: 台本が読めない：{exc}")
            return finish("run", INCOMPLETE, f"{head} reason=script_unreadable")
        # 台本の終わりまで回さないと、台本の後ろの入力が世界へ届いたことを見られない。
        if args.ticks < script.total_ticks:
            return finish("run", INCOMPLETE, f"{head} reason=ticks_shorter_than_script script_ticks={script.total_ticks}")
    # 実時間で回す分（tick数÷60秒）の3倍に、起動の分を足す。
    timeout = args.timeout if args.timeout is not None else 30 + args.ticks / 20

    work = OUT / "run"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    result_path = work / "result.json"
    env = child_env(CP_SMOKE=result_path, CP_SMOKE_TICKS=args.ticks, CP_SMOKE_DRIVER=driver)
    if script_path is not None:
        env["CP_SMOKE_SCRIPT"] = str(script_path)
    code, out, err = run([sys.executable, APP / "main.py"], timeout=timeout, env=env, cwd=work)
    if code is None:
        show_tail(out, err)
        return finish("run", INCOMPLETE, f"{head} reason=timeout timeout_s={timeout:g}")
    if code != 0:
        show_tail(out, err)
        return finish("run", FAIL, f"{head} reason=app_exit_code app_exit={code}")
    if not result_path.exists():
        show_tail(out, err)
        return finish("run", INCOMPLETE, f"{head} reason=no_result_file app_exit=0")
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return finish("run", FAIL, f"{head} reason=result_unreadable")

    want_renders = args.ticks // 2
    want_reads = 0 if script is not None else args.ticks
    want_sim = input_reference.sim_summary(script, args.ticks)  # 参照。台本なしなら、何も押していない入力
    checks = {  # 名前: (合っているか, 合わないときの文)
        "app_exit": (True, ""),  # ここまで来たら、終了コードは0で、結果ファイルは読めている
        "result_file": (True, ""),
        "ticks": (data.get("ticks") == args.ticks, f"回したtickが {data.get('ticks')}（{args.ticks} のはず）"),
        "sim_tick": (
            (data.get("sim") or {}).get("tick") == args.ticks,
            f"世界のtickが {(data.get('sim') or {}).get('tick')}（更新1回が1 tickなら {args.ticks}）",
        ),
        "renders": (
            isinstance(data.get("renders"), int) and abs(data["renders"] - want_renders) <= tolerance,
            f"実描画が {data.get('renders')} 回（{want_renders} 回の前後 {tolerance} 回のはず。毎秒30回）",
        ),
        "back_ink": (
            isinstance(data.get("back_ink"), int) and data["back_ink"] > 0,
            f"裏画面が空（背景色と違う画素が {data.get('back_ink')}）",
        ),
        "screen_diff": (data.get("screen_diff") == 0, f"画面が裏画面と違う（違う画素が {data.get('screen_diff')}）"),
        "driver": (data.get("driver") == driver, f"回した経路が {data.get('driver')!r}（{driver!r} のはず）"),
        "input_source": (
            data.get("input_source") == want_source,
            f"入力の出どころが {data.get('input_source')!r}（{want_source!r} のはず）",
        ),
        "adapter_reads": (
            data.get("adapter_reads") == want_reads,
            f"入力アダプタを呼んだ回数が {data.get('adapter_reads')}（{want_reads} のはず。入力アダプタから読むなら、1 tickに1度）",
        ),
        "direct_reads": (
            data.get("direct_reads") == want_reads,
            f"直読みを呼んだ回数が {data.get('direct_reads')}（{want_reads} のはず。入力アダプタから読むなら1 tickに1度、台本なら呼ばない）",
        ),
        "sim": (data.get("sim") == want_sim, f"世界の要約が {data.get('sim')}（参照は {want_sim}。入力フレームが、順のまま世界へ届いていない）"),
    }
    failed = [name for name, (ok, _) in checks.items() if not ok]
    for name in failed:
        print(f"  run: {checks[name][1]}")
    summary = (
        f"driver={driver} input={data.get('input_source')} ticks={data.get('ticks')} renders={data.get('renders')} "
        f"back_ink={data.get('back_ink')} screen_diff={data.get('screen_diff')} wall_s={data.get('wall_s')} "
        f"checks={len(checks)} problems={len(failed)}"
    )
    if failed:
        summary += " failed=" + ",".join(failed)
    summary += f" not_yet={len(NOT_YET)}({','.join(NOT_YET)})"
    return finish("run", FAIL if failed else OK, summary)


if __name__ == "__main__":
    sys.exit(main())
