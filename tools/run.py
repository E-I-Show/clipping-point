"""デスクトップ版を、画面なしで決まったtickだけ別プロセスで回す。

  python3 tools/run.py [--ticks N] [--realtime] [--script FILE | --no-script] [--pack 名] [--timeout 秒]

  既定        速い経路。アプリ自前のループ（pyxel.flip）で回す。入力は、道具の台本（tools/input_script_smoke.json）
  --realtime  本番と同じ経路。pyxel.run で実時間（毎秒60回）で回す。台本を渡さず、入力アダプタを実物のPyxelで毎tick呼ぶ
  --script FILE  この台本（JSON）を渡す。どちらの経路でも使える
  --no-script    台本を渡さない（入力アダプタから読む）。どちらの経路でも使える
  --pack 名      試験用データ（testpacks/<名>/）を重ねて回す（環境変数 CP_DATA_PACK でアプリへ渡す）。指紋は照らさない

終了コード：0＝合格、1＝回ったが合わない、2＝全tickを回り切れない（時間切れ、結果ファイルが無い）・
台本が読めない・回すtick数が台本の合計より短い・指紋の写しが無い（読めない）・--pack の名の試験用データが無い（置き場が無い、
置き場にファイルが1つも無い、名の字が違う）・参照の世界を作れない（道具が、定義データを読めない）。
アプリの終了コードが0でも、それだけでは合格にしない。pyxel.quit() は常に0で終わるため。
失敗にする条件：アプリの終了コード、結果ファイルが無い、回したtickが違う、世界のtickが違う、
実描画の回数が範囲の外（tickの半分の前後）、3Dの絵の判定（下の6つ）が合わない、画面が裏画面と違う、回した経路が違う、
入力の出どころが違う（台本か入力アダプタか）、入力アダプタを呼んだ回数と、直読みを呼んだ回数が違う
（どちらも、台本なら0、入力アダプタなら回したtickと同じ。直読みは、デスクトップ版では値を返さないが、呼んだ回数は数える）、
世界の要約が参照（tools/input_reference.py。台本なしなら、何も押していない入力。世界は、アプリと同じ読み方で読んだ定義データから作る。
--pack の回は、同じ試験用データを重ねて作る）と違う、
世界の要約の、車とコースの id が、道具の既定（tools/input_reference.py の CAR_ID、TRACK_ID）と違う（確かめの名は sim_ids）、
世界の要約が、指紋の写し（tests/snapshots/fingerprint.json）の、同じ筋書き（台本の有無と中身、回したtick数が同じもの）の要約と違う、
同じ筋書きに、走行の下限（tools/fingerprint.py の Scenario.floors）があって、アプリの世界の要約が、それを満たさない（確かめの名は floor。
指紋を照らさない --pack の回でも、筋書きが同じなら見る）、
保存の往復が通っていない・保存先の名が file でない、道具が自分で読んだ保存のファイルが往復の見本と違う、
名前空間 main のファイルができている、
結果の data が合わない（表ごとの件数が、道具が定義データのファイルを自分で読んで数えた件数と違う。警告が0件でない。
重ねた試験用データの名が、渡した名と違う（渡していなければ null）。設定を読んだ保存の口の名前空間が、main
（渡していれば pack_<名>）でない）。数え方と確かめは tools/data_reference.py。
保存は、置き場（out/run/saves）を、環境変数 CP_SAVE_DIR でアプリへ渡す。アプリは、検証の口のときだけ、名前空間 selfcheck で
保存の往復を回して、書いた鍵を残す。道具は、そのファイルを自分で読み、封筒を開けて、往復の見本と比べる（アプリの申告だけに頼らない）。
「名前空間 main のファイルができていない」は、保存の往復が main に触れないことの確かめ。試験用データを重ねたときの、
名前空間の切り替えは、結果の data の namespace で見る（段0の起動は、設定を書かないので、ファイルでは分からない）。
指紋の筋書きに無い回し方（--ticks N、--script FILE、--pack 名 など）では、指紋の確かめを外して、最後の1行に fingerprint=skipped と出す。
3Dの絵の判定（結果の scene。アプリが、結果を書く直前に、判定用の実描画で数えた値。判定の関数と、値の形は tools/scene_reference.py）：
  backdrop    背景が写っている（空の役割の色の画素が、下限以上）
  scene3d     3Dが描かれている（コースの画素と、車の画素が、どちらも下限以上。車だけの絵、コースだけの絵を、通さない）
  mirror      左右と前後が、正しく写っている（判定用の柱と印の重心）。スタート位置（向き0、z=0）では、向きの符号の誤りと、
              カメラや車の位置だけの反転の付け忘れは、絵に出ない。拾うのは、走る台本の回（全体の検証の run-drive）と、巡回
  palette     当てたパレットが、道具が定義データのファイルを自分で読んだ32色と同じ（--pack の回は、同じ試験用データを重ねて読む）
  scene_same  ふだんの実描画が、判定と同じ3Dを描いている（裏画面と、判定用の3枚目の、2Dの描画命令の矩形の外の違う画素が0）
  back_ink    2Dの描画命令が、裏画面に描かれている（矩形の内の違う画素が1以上）
下限と余裕は tools/budgets.json（無ければ2。reason=no_scene_budgets）。
最後の1行には、3Dの絵の値（sky、track、car、ink、digest）、処理時間の要約（update_ms と render_ms は「平均/95%点/最大」。
cycles_over_tick は、実描画のある周期が、1 tickの長さを超えた回数）、場面の数（描いた三角形の数、場面を組む時間、メッシュを作る時間、
起動にかかった時間）も出す。処理時間と場面の数は、判定に使わない（線の判定は、ブラウザ版の煙テスト）。
"""
import argparse
import json
import shutil
import sys
from pathlib import Path

import data_reference
import fingerprint
import input_reference
import scene_reference
from _common import APP, FAIL, INCOMPLETE, OK, OUT, ROOT, child_env, finish, load_budgets, run, show_tail

from cp_app import data_files, storage_file, storage_select  # noqa: E402 - cp_app への道は、input_reference が足す。pyxel を読み込まないモジュールだけ
from cp_core import profile, storage  # noqa: E402

NOT_YET = ()  # 後の区切りで足す確かめ。いまは、無い（scene3d と mirror は、段0 区切り10で足した）


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


def scene_checks_of(data: dict, budgets: dict, pack=None) -> dict:
    """3Dの絵の判定。返すのは {確かめの名: (合っているか, 合わないときの文)}。並びは scene_reference.SCENE_CHECKS の順。

    data は、アプリの結果。budgets は、道具の値（下限と余裕がそろっていること）。pack は、重ねた試験用データの名（無ければ None）。
    """
    want_palette, why = scene_reference.expected_palette(pack=pack)
    checks = scene_reference.scene_checks(data, budgets, want_palette, f"（読めなかった：{why}）" if why else "")
    return {name: (ok, message) for name, ok, message in checks}


def main() -> int:
    ap = argparse.ArgumentParser(description="デスクトップ版を画面なしで回す")
    ap.add_argument("--ticks", type=int, default=120)
    ap.add_argument("--realtime", action="store_true", help="pyxel.run で実時間で回す（本番と同じ経路）")
    choice = ap.add_mutually_exclusive_group()
    choice.add_argument("--script", default=None, metavar="FILE", help="渡す台本（JSON）。既定は、速い経路だけ tools/input_script_smoke.json")
    choice.add_argument("--no-script", action="store_true", help="台本を渡さない（入力アダプタから読む）")
    ap.add_argument("--pack", default=None, metavar="NAME", help="試験用データ（testpacks/NAME/）を重ねて回す。指紋は照らさない")
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
    if args.pack is not None:
        head += f" pack_wanted={args.pack}"
    budgets = load_budgets()
    tolerance = budgets["run_renders_tolerance"]
    # 実描画が0回でも幅の中に入ってしまう短さでは、判定にならない。
    min_ticks = 2 * (tolerance + 1)
    if args.ticks < min_ticks:
        return finish("run", INCOMPLETE, f"{head} reason=too_few_ticks min={min_ticks}")
    # 3Dの絵の判定に要る、下限と余裕（道具の値）。無ければ、判定できない（黙って、外さない）。
    missing_budgets = scene_reference.missing_budgets(budgets)
    if missing_budgets:
        print(f"  run: 3Dの絵の判定の下限と余裕が、道具の値（tools/budgets.json）に無い：{missing_budgets}")
        return finish("run", INCOMPLETE, f"{head} reason=no_scene_budgets")
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
    snapshot = None
    if args.pack is not None:
        # 試験用データを重ねて回す。名に当たる置き場が無い、置き場にファイルが1つも無い、名の字が違う、は回り切れない
        # （アプリは、起動時に ValueError にする。道具は、同じ所を先に見て、2にする）。指紋は照らさない。
        why = data_reference.pack_or_reason(args.pack)
        if why:
            print(f"  run: 試験用データ（{args.pack}）が使えない：{why}")
            return finish("run", INCOMPLETE, f"{head} reason=no_such_pack")
    else:
        # 指紋の写し。無いか、読めなければ、回り切れない（黙って作らない。取り直す口は tools/fingerprint.py --update）。
        snapshot = fingerprint.read_fingerprint_snapshot(ROOT)
        if snapshot is None:
            print(f"  run: 指紋の写し（{fingerprint.FINGERPRINT_SNAPSHOT}）が無いか、読めない")
            return finish("run", INCOMPLETE, f"{head} reason=no_fingerprint_snapshot")
    try:
        # 同じ筋書き（台本の有無と中身、回すtick数が同じもの）。無ければ、指紋の確かめを外す。
        # 試験用データを重ねた回は、指紋を照らさないが、筋書きの走行の下限は見る。
        scenario = fingerprint.scenario_for(script_value, args.ticks)
    except ValueError as exc:
        print(f"  run: 指紋の筋書きの台本が読めない：{exc}")
        return finish("run", INCOMPLETE, f"{head} reason=script_unreadable")
    compare_fingerprint = scenario is not None and snapshot is not None
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
    if args.pack is not None:
        env[data_files.PACK_ENV] = args.pack  # 重ねる試験用データの名
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
    try:
        # 参照。台本なしなら、何も押していない入力。世界は、アプリと同じ読み方で読んだ定義データ（--pack の回は、同じ試験用データを
        # 重ねたもの）と、道具の既定の車とコースの id から作る。
        want_sim = input_reference.sim_summary(script, args.ticks, 0, args.pack)
    except ValueError as exc:
        print(f"  run: 参照の世界を作れない（定義データが読めない）：{exc}")
        return finish("run", INCOMPLETE, f"{head} reason=no_reference")
    ids_problem = input_reference.world_ids_problem(data.get("sim"))
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
        # 3Dの絵の判定（backdrop、scene3d、mirror、palette、scene_same、back_ink）。判定の関数は、道具 tour、web-smoke と同じ。
        # パレットは、道具が、定義データのファイルを自分で読んで照らす（--pack の回は、同じ試験用データを重ねて読む）。
        **scene_checks_of(data, budgets, args.pack),
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
        "sim": (
            data.get("sim") == want_sim,
            f"世界の要約が {data.get('sim')}（参照は {want_sim}。入力フレームが、順のまま世界へ届いていないか、アプリの世界が、別の車かコースで回っている）",
        ),
        # アプリの世界の、車とコースの id。道具の既定と違えば、参照と、アプリの世界が、別のデータで回っている。
        "sim_ids": (not ids_problem, ids_problem),
    }
    if compare_fingerprint:
        # 指紋。参照（上の sim）は、いまのコードで計算し直した値。こちらは、保存してある指紋の写し。世界の式が変わると、こちらだけが落ちる。
        recorded = fingerprint.recorded_summary(snapshot, scenario)
        checks["fingerprint"] = (
            recorded is not None and data.get("sim") == recorded,
            f"世界の要約が {data.get('sim')}（指紋の写しの筋書き {scenario.name} は {recorded}。"
            "意図した変更なら、単独のコミットで python3 tools/fingerprint.py --update）",
        )
    if scenario is not None and scenario.floors:
        # 走行の下限。アプリを通した回でも、走行が成り立っていること（指紋を照らさない回でも、筋書きが同じなら見る）。
        below = fingerprint.floor_problems(scenario, data.get("sim"))
        checks["floor"] = (not below, "。".join(below))
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
    # 定義データ。アプリの申告（表ごとの件数、警告、重ねた名、保存の名前空間）を、道具が自分で数えた件数と、渡した名と照らす。
    want_tables, why = data_reference.expected_tables(args.pack)
    for name, ok, message in data_reference.data_checks(data, want_tables, args.pack, f"（数えられなかった：{why}）" if why else ""):
        checks[name] = (ok, message)
    loaded = data.get("data") if isinstance(data.get("data"), dict) else {}
    failed = [name for name, (ok, _) in checks.items() if not ok]
    for name in failed:
        print(f"  run: {checks[name][1]}")
    summary = (
        f"driver={driver} input={data.get('input_source')} ticks={data.get('ticks')} renders={data.get('renders')} "
        f"{scene_reference.scene_words(data)} screen_diff={data.get('screen_diff')} wall_s={data.get('wall_s')} "
        f"{scene_reference.perf_words(data)} {scene_reference.stats_words(data)} "
        f"pack={'none' if loaded.get('pack') is None else loaded.get('pack')} namespace={loaded.get('namespace')} "
        f"save={saved.get('backend')} checks={len(checks)} problems={len(failed)}"
    )
    if failed:
        summary += " failed=" + ",".join(failed)
    if not compare_fingerprint:
        summary += " fingerprint=skipped"
    summary += f" not_yet={len(NOT_YET)}" + (f"({','.join(NOT_YET)})" if NOT_YET else "")
    return finish("run", FAIL if failed else OK, summary)


if __name__ == "__main__":
    sys.exit(main())
