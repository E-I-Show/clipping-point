"""デスクトップ版を、画面なしで決まったtickだけ別プロセスで回す。

  python3 tools/run.py [--ticks N] [--realtime] [--script FILE | --no-script] [--timeout 秒]

  既定        速い経路。アプリ自前のループ（pyxel.flip）で回す。入力は、道具の台本（tools/input_script_smoke.json）
  --realtime  本番と同じ経路。pyxel.run で実時間（毎秒60回）で回す。台本を渡さず、入力アダプタを実物のPyxelで毎tick呼ぶ
  --script FILE  この台本（JSON）を渡す。どちらの経路でも使える
  --no-script    台本を渡さない（入力アダプタから読む）。どちらの経路でも使える

終了コード：0＝合格、1＝回ったが合わない、2＝全tickを回り切れない（時間切れ、結果ファイルが無い）・
台本が読めない・回すtick数が台本の合計より短い・指紋の写しが無い（読めない）。
アプリの終了コードが0でも、それだけでは合格にしない。pyxel.quit() は常に0で終わるため。
失敗にする条件：アプリの終了コード、結果ファイルが無い、回したtickが違う、世界のtickが違う、
実描画の回数が範囲の外（tickの半分の前後）、裏画面が空、画面が裏画面と違う、回した経路が違う、
入力の出どころが違う（台本か入力アダプタか）、入力アダプタを呼んだ回数と、直読みを呼んだ回数が違う
（どちらも、台本なら0、入力アダプタなら回したtickと同じ。直読みは、デスクトップ版では値を返さないが、呼んだ回数は数える）、
世界の要約が参照（tools/input_reference.py。台本なしなら、何も押していない入力）と違う、
世界の要約が、指紋の写し（tests/snapshots/fingerprint.json）の、同じ筋書き（台本の有無と中身、回したtick数が同じもの）の要約と違う、
保存の往復が通っていない・保存先の名が file でない、道具が自分で読んだ保存のファイルが往復の見本と違う、
名前空間 main のファイルができている。
保存は、置き場（out/run/saves）を、環境変数 CP_SAVE_DIR でアプリへ渡す。アプリは、検証の口のときだけ、名前空間 selfcheck で
保存の往復を回して、書いた鍵を残す。道具は、そのファイルを自分で読み、封筒を開けて、往復の見本と比べる（アプリの申告だけに頼らない）。
指紋の筋書きに無い回し方（--ticks N、--script FILE など）では、指紋の確かめを外して、最後の1行に fingerprint=skipped と出す。
3Dが描かれていること、左右の向きは、後の区切りで足す（最後の1行の not_yet）。
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import fingerprint
import input_reference
from _common import APP, FAIL, INCOMPLETE, OK, OUT, ROOT, child_env, finish, load_budgets, run, show_tail

from cp_app import storage_file, storage_select  # noqa: E402 - cp_app への道は、input_reference が足す。pyxel を読み込まないモジュールだけ
from cp_core import profile, storage  # noqa: E402

NOT_YET = ("scene3d", "mirror")  # 後の区切りで足す確かめ


def read_saved_settings(save_dir: Path) -> tuple:
    """保存の往復が残したファイルを、道具が自分で読む。返すのは (合っているか, 合わないときの文)。

    見るのは、名前空間 selfcheck の設定のファイル。封筒を開けて、形式バージョンと本体を、往復の見本と比べる。
    """
    name = f"{profile.SELFCHECK_NAMESPACE}{storage.NAMESPACE_SEPARATOR}{profile.SETTINGS_KEY}{storage_file.SUFFIX}"
    try:
        blob = (save_dir / name).read_bytes()
    except OSError as exc:
        return False, f"保存の往復のファイル（{name}）が読めない：{type(exc).__name__}"
    try:
        version, payload = storage.unwrap(blob)
    except storage.CorruptError as exc:
        return False, f"保存の往復のファイル（{name}）の封筒が読めない：{exc}"
    want = (profile.SETTINGS_VERSION, profile.encode(profile.SELFCHECK_SETTINGS))
    return (version, payload) == want, f"保存の往復のファイル（{name}）が、往復の見本と違う（形式バージョン {version}、本体 {payload[:120]!r}）"


def main_namespace_files(save_dir: Path) -> list:
    """置き場にある、ふつうの保存（名前空間 main）のファイルの名。保存の往復は、ここに触れないはず。"""
    prefix = storage.DEFAULT_NAMESPACE + storage.NAMESPACE_SEPARATOR
    try:
        return sorted(path.name for path in save_dir.iterdir() if path.name.startswith(prefix))
    except OSError:
        return []


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
    script_value = script = None
    if script_path is not None:
        try:
            script_value, script = input_reference.load_script(script_path)
        except ValueError as exc:
            print(f"  run: 台本が読めない：{exc}")
            return finish("run", INCOMPLETE, f"{head} reason=script_unreadable")
        # 台本の終わりまで回さないと、台本の後ろの入力が世界へ届いたことを見られない。
        if args.ticks < script.total_ticks:
            return finish("run", INCOMPLETE, f"{head} reason=ticks_shorter_than_script script_ticks={script.total_ticks}")
    # 指紋の写し。無いか、読めなければ、回り切れない（黙って作らない。取り直す口は tools/fingerprint.py --update）。
    snapshot = fingerprint.read_fingerprint_snapshot(ROOT)
    if snapshot is None:
        print(f"  run: 指紋の写し（{fingerprint.FINGERPRINT_SNAPSHOT}）が無いか、読めない")
        return finish("run", INCOMPLETE, f"{head} reason=no_fingerprint_snapshot")
    try:
        # 同じ筋書き（台本の有無と中身、回すtick数が同じもの）。無ければ、指紋の確かめを外す。
        scenario = fingerprint.scenario_for(script_value, args.ticks)
    except ValueError as exc:
        print(f"  run: 指紋の筋書きの台本が読めない：{exc}")
        return finish("run", INCOMPLETE, f"{head} reason=script_unreadable")
    # 実時間で回す分（tick数÷60秒）の3倍に、起動の分を足す。
    timeout = args.timeout if args.timeout is not None else 30 + args.ticks / 20

    work = OUT / "run"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    result_path, save_dir = work / "result.json", work / "saves"
    # 保存のファイルの置き場は、絶対パスで渡す。置き場は、アプリが最初の書き込みで作る。
    env = child_env(CP_SMOKE=result_path, CP_SMOKE_TICKS=args.ticks, CP_SMOKE_DRIVER=driver, **{storage_select.SAVE_DIR_ENV: save_dir})
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
    if scenario is not None:
        # 指紋。参照（上の sim）は、いまのコードで計算し直した値。こちらは、保存してある指紋の写し。世界の式が変わると、こちらだけが落ちる。
        recorded = fingerprint.recorded_summary(snapshot, scenario)
        checks["fingerprint"] = (
            recorded is not None and data.get("sim") == recorded,
            f"世界の要約が {data.get('sim')}（指紋の写しの筋書き {scenario.name} は {recorded}。"
            "意図した変更なら、単独のコミットで python3 tools/fingerprint.py --update）",
        )
    # 保存の往復。アプリの申告（通ったか、保存先の名）と、道具が自分で読んだファイル。
    saved = data.get("storage") if isinstance(data.get("storage"), dict) else {}
    checks["save"] = (
        saved.get("ok") is True and saved.get("backend") == storage_select.BACKEND_FILE,
        f"保存の往復が通っていない（保存先 {saved.get('backend')!r}、通ったか {saved.get('ok')!r}、理由 {saved.get('detail')!r}。"
        f"保存先は {storage_select.BACKEND_FILE!r} のはず）",
    )
    checks["save_file"] = read_saved_settings(save_dir)
    main_files = main_namespace_files(save_dir)
    checks["save_main"] = (not main_files, f"ふつうの保存（名前空間 {storage.DEFAULT_NAMESPACE}）のファイルができている：{main_files}（保存の往復は、名前空間 {profile.SELFCHECK_NAMESPACE} で回す）")
    failed = [name for name, (ok, _) in checks.items() if not ok]
    for name in failed:
        print(f"  run: {checks[name][1]}")
    summary = (
        f"driver={driver} input={data.get('input_source')} ticks={data.get('ticks')} renders={data.get('renders')} "
        f"back_ink={data.get('back_ink')} screen_diff={data.get('screen_diff')} wall_s={data.get('wall_s')} "
        f"save={saved.get('backend')} checks={len(checks)} problems={len(failed)}"
    )
    if failed:
        summary += " failed=" + ",".join(failed)
    if scenario is None:
        summary += " fingerprint=skipped"
    summary += f" not_yet={len(NOT_YET)}({','.join(NOT_YET)})"
    return finish("run", FAIL if failed else OK, summary)


if __name__ == "__main__":
    sys.exit(main())
