"""デスクトップ版を、画面なしで決まったtickだけ別プロセスで回す。

  python3 tools/run.py [--ticks N] [--realtime] [--timeout 秒]

  既定        速い経路。アプリ自前のループ（pyxel.flip）で回す
  --realtime  本番と同じ経路。pyxel.run で実時間（毎秒60回）で回す

終了コード：0＝合格、1＝回ったが合わない、2＝全tickを回り切れない（時間切れ、結果ファイルが無い）。
アプリの終了コードが0でも、それだけでは合格にしない。pyxel.quit() は常に0で終わるため。
失敗にする条件：アプリの終了コード、結果ファイルが無い、回したtickが違う、世界のtickが違う、
実描画の回数が範囲の外（tickの半分の前後）、裏画面が空、画面が裏画面と違う、回した経路が違う。
指紋、3Dが描かれていること、左右の向き、保存の往復は、後の区切りで足す（最後の1行の not_yet）。
"""
import argparse
import json
import shutil
import sys

from _common import APP, FAIL, INCOMPLETE, OK, OUT, child_env, finish, load_budgets, run, tail

MIN_TICKS = 10  # これより短いと、実描画の回数の幅（前後3回）が判定にならない
NOT_YET = ("fingerprint", "scene3d", "mirror", "save")  # 後の区切りで足す確かめ


def main() -> int:
    ap = argparse.ArgumentParser(description="デスクトップ版を画面なしで回す")
    ap.add_argument("--ticks", type=int, default=120)
    ap.add_argument("--realtime", action="store_true", help="pyxel.run で実時間で回す（本番と同じ経路）")
    ap.add_argument("--timeout", type=float, default=None, help="秒。既定は tick数から決める")
    args = ap.parse_args()
    driver = "run" if args.realtime else "flip"
    head = f"driver={driver} ticks_wanted={args.ticks}"
    if args.ticks < MIN_TICKS:
        return finish("run", INCOMPLETE, f"{head} reason=too_few_ticks min={MIN_TICKS}")
    timeout = args.timeout if args.timeout is not None else 30 + args.ticks / 20
    tolerance = load_budgets()["run_renders_tolerance"]

    work = OUT / "run"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    result_path = work / "result.json"
    env = child_env(CP_SMOKE=result_path, CP_SMOKE_TICKS=args.ticks, CP_SMOKE_DRIVER=driver)
    code, out, err = run([sys.executable, APP / "main.py"], timeout=timeout, env=env, cwd=work)
    if code is None:
        print(tail(out + "\n" + err))
        return finish("run", INCOMPLETE, f"{head} reason=timeout timeout_s={timeout:g}")
    if code != 0:
        print(tail(out + "\n" + err))
        return finish("run", FAIL, f"{head} reason=app_exit_code app_exit={code}")
    if not result_path.exists():
        print(tail(out + "\n" + err))
        return finish("run", INCOMPLETE, f"{head} reason=no_result_file app_exit=0")
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except ValueError as exc:
        return finish("run", FAIL, f"{head} reason=result_unreadable ({exc})")

    want_renders = args.ticks // 2
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
    }
    failed = [name for name, (ok, _) in checks.items() if not ok]
    for name in failed:
        print(f"  run: {checks[name][1]}")
    summary = (
        f"driver={driver} ticks={data.get('ticks')} renders={data.get('renders')} back_ink={data.get('back_ink')} "
        f"screen_diff={data.get('screen_diff')} wall_s={data.get('wall_s')} checks={len(checks)} problems={len(failed)}"
    )
    if failed:
        summary += " failed=" + ",".join(failed)
    summary += f" not_yet={len(NOT_YET)}({','.join(NOT_YET)})"
    return finish("run", FAIL if failed else OK, summary)


if __name__ == "__main__":
    sys.exit(main())
