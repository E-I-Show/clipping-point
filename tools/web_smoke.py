"""ブラウザ版の煙テスト。出荷するHTMLそのものを、ヘッドレスのChromiumで開く。

  python3 tools/web_smoke.py [--only shipped|probe] [--ticks N] [--timeout 秒]

開くのは、この道具が tools/export.py を回して作らせた dist/clipping_point.html そのもの（同じバイト列）。
煙テスト用に作り直したHTMLは開かない。ランタイムへの要求は、ランタイムの写し（.cache/pyxel_web/mirror/）へ差し替える。
筋書きは2本。順に、1本ずつ回す。
  shipped  何も渡さずに開く。見るもの：Pythonの例外が無い、エラー表示が無い、読み込みの失敗が無い、
           ランタイムの写しの外への要求が無い、開始のクリックの後の決めた秒数で画面が描かれている（背景と違う画素がある）。
  probe    ページを開く前に差し込むスクリプトで、回すtick数（window.CP_PROBE）を置いて開く。
           アプリがコンソールへ出す結果の1行と完了の合図を待つ。見るもの：上に加えて、回したtick、
           世界の要約がデスクトップ版と同じ、実描画の回数、更新と実描画の毎秒の回数、更新1回と実描画1回の時間（95%点）、
           ブラウザ版であること（sys.platform が emscripten）、Pythonの版。線は tools/budgets.json。
終了コード：0＝合格、1＝問題あり、2＝回り切れない（ランタイムの写しが無い・照合が合わない、node が無い、
ビルドできない、デスクトップ版の参照が取れない、実行役の結果が無い、完了の合図が出ない）。2を合格にしない。
結果は out/web_smoke/ に書く。前回の結果は、回す前に消す。
"""
import argparse
import hashlib
import json
import shutil
import sys

from _common import APP, DIST, FAIL, INCOMPLETE, OK, OUT, TOOLS, child_env, finish, load_budgets, run, show_tail

# fetch_runtime（ランタイムの写しの置き場と照合）と、cp_app.web_bridge（外から渡す値の名前と、結果の行の頭）を読む。
# どちらも pyxel を読み込まない。後ろに足す（標準ライブラリの名前を隠さないように）。
for extra_path in (str(TOOLS / "web"), str(APP)):
    if extra_path not in sys.path:
        sys.path.append(extra_path)

import fetch_runtime  # noqa: E402
from cp_app import web_bridge  # noqa: E402

WORK = OUT / "web_smoke"
HTML = DIST / f"{APP.name}.html"
WEBRUN = TOOLS / "web" / "webrun.js"
SCENARIOS = ("shipped", "probe")
MIN_MEASURED_TICKS = 60  # 慣らしの後に測るtick数の下限。これより短いと、毎秒の回数が1回の揺れで線を外れる
# tools/web/webrun.js が集める失敗の種類と、その読み方。並びは、最後の1行の failed= に出す順。
FAILURE_KINDS = {
    "no_start_prompt": "開始の表示が出ない（ランタイムが読み込めていない）",
    "error_overlay": "Pyxelのエラー表示がある（Pythonの例外）",
    "fatal_error": "ランタイムが致命的なエラーを記した",
    "console_error": "コンソールにエラーの行がある",
    "page_error": "ページの中で、捕まえられなかった例外がある",
    "outside_mirror": "ランタイムの写しの外への要求がある",
    "not_in_mirror": "ランタイムの写しに無いファイルへの要求がある",
    "request_failed": "読み込みの失敗がある",
    "http_status": "400以上の応答がある",
}
TIMING_CHECKS = ("updates_per_s", "renders_per_s", "update_ms_p95", "render_ms_p95")


def is_number(value) -> bool:
    return type(value) in (int, float)


def page_checks(page: dict, html_sha256: str) -> list:
    """どの筋書きでも見ること。返すのは [(名前, 合っているか, 合わないときの文)]。"""
    failures = page.get("failures") or []
    checks = []
    for kind, text in FAILURE_KINDS.items():
        hits = [f for f in failures if f.get("kind") == kind]
        detail = str(hits[0].get("detail", "")).strip().splitlines()[-1:] if hits else []
        checks.append((kind, not hits, f"{text}（{len(hits)}件）：{' '.join(detail)[:300]}"))
    other = sorted({str(f.get("kind")) for f in failures} - set(FAILURE_KINDS))
    checks.append(("other_failure", not other, f"知らない種類の失敗がある：{other}"))
    checks.append(("html_bytes", page.get("htmlSha256") == html_sha256, "開いたHTMLが、export が作ったHTMLと同じバイト列でない"))
    return checks


def judge_shipped(page: dict, html_sha256: str) -> list:
    """何も渡さずに開く筋書きの確かめ。"""
    state = page.get("state") or {}
    ink = (page.get("canvas") or {}).get("ink")
    return page_checks(page, html_sha256) + [
        ("started", page.get("clickedAt") is not None and state.get("initialized") is True, "アプリが始まっていない"),
        ("canvas_ink", type(ink) is int and ink > 0, f"画面が描かれていない（背景と違う画素が {ink}）"),
    ]


def read_probe_result(page: dict):
    """コンソールの行から、アプリが出した結果を読む。返すのは (結果の辞書, 理由)。読めなければ結果は None。"""
    head = web_bridge.RESULT_MARK + " "
    lines = [c.get("text", "") for c in page.get("console") or [] if str(c.get("text", "")).startswith(head)]
    if page.get("untilAt") is None:
        return None, "no_done_signal"
    if len(lines) != 1:
        return None, "result_line_count"
    try:
        data = json.loads(lines[0][len(head):])
    except ValueError:
        data = None
    return (data, "") if isinstance(data, dict) else (None, "result_unreadable")


def judge_probe(page: dict, html_sha256: str, result: dict, desktop_sim, ticks: int, warmup_ticks: int, budgets: dict) -> list:
    """回すtick数を渡して開く筋書きの確かめ。result は、アプリがコンソールへ出した結果。"""
    perf = result.get("perf") if isinstance(result.get("perf"), dict) else {}
    renders, tolerance = result.get("renders"), budgets["web_renders_tolerance"]
    python = str(result.get("python", ""))
    ups, rps = perf.get("updates_per_s"), perf.get("renders_per_s")
    update_ms, render_ms = perf.get("update_ms_p95"), perf.get("render_ms_p95")
    ups_min, rps_min = budgets["web_updates_per_s_min"], budgets["web_renders_per_s_min"]
    update_max, render_max = budgets["web_update_ms_p95_max"], budgets["web_render_ms_p95_max"]
    return page_checks(page, html_sha256) + [
        ("platform", result.get("platform") == web_bridge.WEB_PLATFORM, f"ブラウザ版でない（sys.platform が {result.get('platform')!r}）"),
        ("python", python.startswith(fetch_runtime.WEB_PYTHON + "."), f"Pythonの版が {python!r}（{fetch_runtime.WEB_PYTHON} のはず）"),
        ("ticks", result.get("ticks") == ticks, f"回したtickが {result.get('ticks')}（{ticks} のはず）"),
        (
            "measured_ticks",
            perf.get("updates") == ticks - warmup_ticks,
            f"測ったtickが {perf.get('updates')}（慣らしの {warmup_ticks} を除いて {ticks - warmup_ticks} のはず）",
        ),
        ("sim", desktop_sim is not None and result.get("sim") == desktop_sim, f"世界の要約がデスクトップ版と違う（ブラウザ版 {result.get('sim')}、デスクトップ版 {desktop_sim}）"),
        (
            "renders",
            type(renders) is int and abs(renders - ticks // 2) <= tolerance,
            f"実描画が {renders} 回（{ticks // 2} 回の前後 {tolerance} 回のはず。毎秒30回）",
        ),
        ("updates_per_s", is_number(ups) and ups >= ups_min, f"更新が毎秒 {ups} 回（{ups_min} 回以上のはず）"),
        ("renders_per_s", is_number(rps) and rps >= rps_min, f"実描画が毎秒 {rps} 回（{rps_min} 回以上のはず）"),
        ("update_ms_p95", is_number(update_ms) and update_ms <= update_max, f"更新1回が {update_ms} ms（95%点。{update_max} ms以内のはず）"),
        ("render_ms_p95", is_number(render_ms) and render_ms <= render_max, f"実描画1回が {render_ms} ms（95%点。{render_max} ms以内のはず）"),
    ]


def open_page(name: str, timeout_s: float, extra: list):
    """実行役（webrun.js）を1本回し、結果のJSONを読む。読めなければ None。"""
    json_path = WORK / f"{name}.json"
    cmd = [
        "node", WEBRUN, "--html", HTML, "--mirror", fetch_runtime.MIRROR, "--json", json_path,
        "--shot", WORK / f"{name}.png", "--timeout-ms", int(timeout_s * 1000), *extra,
    ]
    code, out, err = run(cmd, timeout=timeout_s + 60)
    try:
        page = json.loads(json_path.read_text(encoding="utf-8")) if code == 0 else None
    except (OSError, ValueError):
        page = None
    if not isinstance(page, dict):
        show_tail(out, err)
        print(f"  web_smoke: [{name}] 実行役の結果が無い（実行役の終了コード {code}）")
        return None
    return page


def desktop_reference(ticks: int):
    """デスクトップ版を同じtick数だけ画面なしで回し、世界の要約を返す。取れなければ None。"""
    result_path = WORK / "desktop.json"
    env = child_env(CP_SMOKE=result_path, CP_SMOKE_TICKS=ticks, CP_SMOKE_DRIVER="flip")
    code, out, err = run([sys.executable, APP / "main.py"], timeout=60 + ticks / 20, env=env, cwd=WORK)
    try:
        data = json.loads(result_path.read_text(encoding="utf-8")) if code == 0 else None
    except (OSError, ValueError):
        data = None
    if not isinstance(data, dict) or data.get("ticks") != ticks or not isinstance(data.get("sim"), dict):
        show_tail(out, err)
        return None
    return data["sim"]


def main() -> int:
    budgets = load_budgets()
    ap = argparse.ArgumentParser(description="ブラウザ版の煙テスト")
    ap.add_argument("--only", choices=SCENARIOS, help="この筋書きだけ回す")
    ap.add_argument("--ticks", type=int, default=budgets["web_probe_ticks"], help="probe で回すtick数（慣らしを含む）")
    ap.add_argument("--timeout", type=float, default=budgets["web_timeout_s"], help="筋書き1本の時間切れ（秒）")
    args = ap.parse_args()
    names = [args.only] if args.only else list(SCENARIOS)
    warmup_ticks = budgets["web_probe_warmup_ticks"]
    min_ticks = warmup_ticks + MIN_MEASURED_TICKS
    if "probe" in names and args.ticks < min_ticks:
        return finish("web_smoke", INCOMPLETE, f"scenarios=0 reason=too_few_ticks min={min_ticks}")
    if not shutil.which("node"):
        return finish("web_smoke", INCOMPLETE, "scenarios=0 reason=no_node")
    try:
        missing, mismatched = fetch_runtime.check_mirror(fetch_runtime.read_sums())
    except (OSError, ValueError) as exc:
        print(f"  web_smoke: {exc}")
        return finish("web_smoke", INCOMPLETE, "scenarios=0 reason=no_sums")
    if missing or mismatched:
        print("  web_smoke: ランタイムの写しが使えない。python3 tools/web/fetch_runtime.py で取得して照合する。")
        reason = "runtime_mirror_mismatch" if mismatched else "no_runtime_mirror"
        return finish("web_smoke", INCOMPLETE, f"scenarios=0 reason={reason} missing={len(missing)} mismatched={len(mismatched)}")

    shutil.rmtree(WORK, ignore_errors=True)  # 前回の結果を読んで合格にしない
    WORK.mkdir(parents=True)
    code, out, err = run([sys.executable, TOOLS / "export.py"])
    if code != 0 or not HTML.is_file():
        show_tail(out, err)
        return finish("web_smoke", INCOMPLETE, f"scenarios=0 reason=export_failed export_exit={code}")
    html_sha256 = hashlib.sha256(HTML.read_bytes()).hexdigest()

    states, failed, incomplete, facts = {}, [], [], []
    checks_total = problems_total = 0
    for name in names:
        if name == "shipped":
            page = open_page(name, args.timeout, ["--watch-ms", int(budgets["web_shipped_watch_s"] * 1000)])
            if page is None:
                states[name] = INCOMPLETE
                incomplete.append(f"{name}.no_runner_result")
                continue
            checks = judge_shipped(page, html_sha256)
            facts.append(f"canvas_ink={(page.get('canvas') or {}).get('ink')}")
        else:
            desktop_sim = desktop_reference(args.ticks)
            if desktop_sim is None:
                states[name] = INCOMPLETE
                incomplete.append(f"{name}.no_desktop_reference")
                continue
            script = f"window.{web_bridge.PROBE_NAME} = {json.dumps({'ticks': args.ticks, 'warmup_ticks': warmup_ticks})};"
            page = open_page(name, args.timeout, ["--init-script", script, "--until", f"^{web_bridge.DONE_MARK}$"])
            if page is None:
                states[name] = INCOMPLETE
                incomplete.append(f"{name}.no_runner_result")
                continue
            result, reason = read_probe_result(page)
            if result is None:
                # 結果が読めない。失敗の合図があれば問題あり、何も無ければ回り切れていない。
                checks = page_checks(page, html_sha256)
                if all(ok for _, ok, _ in checks):
                    states[name] = INCOMPLETE
                    incomplete.append(f"{name}.{reason}")
                    print(f"  web_smoke: [{name}] 結果が読めない（{reason}）。失敗の合図も無い。時間切れ {args.timeout:g} 秒")
                    continue
                checks.append((reason, False, "アプリの結果が読めない"))
            else:
                checks = judge_probe(page, html_sha256, result, desktop_sim, args.ticks, warmup_ticks, budgets)
                perf = result.get("perf") if isinstance(result.get("perf"), dict) else {}
                facts.append(f"ticks={result.get('ticks')} renders={result.get('renders')} " + " ".join(f"{key}={perf.get(key)}" for key in TIMING_CHECKS) + f" python={result.get('python')}")
        bad = [(check, message) for check, ok, message in checks if not ok]
        for check, message in bad:
            print(f"  web_smoke: [{name}] {message}")
        if bad and all(check in TIMING_CHECKS for check, _ in bad):
            print(f"  web_smoke: [{name}] 外れたのは処理時間と回数の線だけ。単独で1度回し直し、それでも外れたら失敗とする（docs/plan.md の段0の通過条件）。")
        checks_total += len(checks)
        problems_total += len(bad)
        failed += [f"{name}.{check}" for check, _ in bad]
        states[name] = FAIL if bad else OK

    word = {OK: "ok", FAIL: "failed", INCOMPLETE: "incomplete"}
    summary = f"scenarios={len(names)} " + " ".join(f"{name}={word[states[name]]}" for name in names)
    if facts:
        summary += " " + " ".join(facts)
    summary += f" checks={checks_total} problems={problems_total}"
    if failed:
        summary += " failed=" + ",".join(failed)
    if incomplete:
        summary += " incomplete=" + ",".join(incomplete)
    (WORK / "summary.json").write_text(json.dumps({"states": {n: word[s] for n, s in states.items()}, "failed": failed, "incomplete": incomplete, "html_sha256": html_sha256}, indent=1) + "\n", encoding="utf-8")
    return finish("web_smoke", max(states.values()), summary)


if __name__ == "__main__":
    sys.exit(main())
