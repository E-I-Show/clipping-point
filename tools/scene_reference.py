"""3Dの絵の参照。判定用の実描画の結果（結果の scene）の確かめと、道具が、パレットを定義データから自分で読む所。

tools/run.py、tools/tour.py、tools/web_smoke.py が使う。同じ判定を、道具ごとに書かない。pyxel は読み込まない。
アプリは、検証の口があるときだけ、結果を書く直前に、裏画面とは別の絵へ4枚描いて、画素を数え、結果の scene に入れる。
  scene = {
    "sky"          1枚目（背景と地面）の、空の役割の色の画素の数
    "track"        1枚目と、2枚目（1枚目＋コース）の、違う画素の数（コースの画素。地面は、1枚目に入れるので、含まない）
    "car"          2枚目と、3枚目（2枚目＋車）の、違う画素の数（車の画素）
    "ink_inside"   裏画面（3Dと2D）と、3枚目の、違う画素のうち、2Dの描画命令の矩形の内の数
    "ink_outside"  同じく、矩形の外の数
    "stale"        描き直す前の裏画面（周期の中の実描画が描いた絵。1〜2 tick前の世界）と、描き直した後の裏画面の、違う画素の数。
                   アプリの結果にだけ入る（巡回の3Dの絵には、周期の中の実描画が無いので、入らない）
    "probes"       4枚目（柱と印だけ）の、柱と印ごとの {"pixels": 画素の数, "x10": 重心の x（0.1画素の単位）}。名は PROBES
    "palette"      当てたパレットを読み戻した32色（0xRRGGBB の整数）
    "digest"       3枚目の画素の要約値（デスクトップ版とブラウザ版の絵の違いを、報告に書くための値。合否には、使わない）
  }
  値は、どれも整数（bool と小数は、受けない）。
確かめ（SCENE_CHECKS）：
  backdrop    sky が、下限以上（背景を写していない絵を、通さない）
  scene3d     track と car が、どちらも、下限以上（車だけが描かれた絵、コースだけの絵を、通さない）
  mirror      柱と印の、どの色も、画素が1つ以上。左の柱の重心が、画面の中央より左、右の柱と、模型の右の印の重心が、右、
              鼻先の印の重心が、中央の近く（どれも、余裕つき）。鏡写しの絵と、車だけが鏡写しの絵を、通さない
  palette     palette が、道具が定義データから自分で読んだ32色と同じ（パレットを当てていない絵を、通さない）
  scene_same  ink_outside が 0（ふだんの実描画が、判定と同じ3Dを描いている）
  back_ink    ink_inside が 1 以上（2Dの描画命令が、裏画面に描かれている）
  back_live   stale が、上限以下（周期の中の実描画が、裏画面へ描いている。scene_same と back_ink は、結果を書く直前に描き直した絵を
              見るので、周期の中で1度も描かない、途中から描かない、を通す。描いていなければ、黒のままか、古い絵で、ほぼ全面が違う）
巡回の3Dの絵（2Dの描画命令を重ねず、周期の中の実描画も無い）では、back_ink と back_live を外す（NOT_FOR_SHOTS）。scene_same は、回す。
下限、上限、余裕は tools/budgets.json（BUDGET_KEYS）。値は、実測してから置く。
柱と印の名は、出荷するコード（cp_core/camera.py と cp_core/car_shape.py）から引く。画面の幅は cp_ui/canvas.py。
"""
import json
import sys
from pathlib import Path

from _common import APP

if str(APP) not in sys.path:
    sys.path.append(str(APP))  # cp_core と cp_ui を読む。後ろに足す（標準ライブラリの名前を隠さないように）

import data_reference  # noqa: E402
from cp_core import camera, car_shape, datadefs, palette  # noqa: E402 - pyxel を読み込まないモジュール
from cp_ui.canvas import SCREEN_W  # noqa: E402

SCENE_CHECKS = ("backdrop", "scene3d", "mirror", "palette", "scene_same", "back_ink", "back_live")  # 結果の scene の確かめの名
NOT_FOR_SHOTS = ("back_ink", "back_live")  # 巡回の3Dの絵では、回さない確かめ（2Dの描画命令の画素と、周期の中の実描画）
# 柱と印の名（結果の scene の probes の鍵）。左の柱、右の柱、模型の右の印、鼻先の印。
PROBES = (camera.PILLAR_LEFT, camera.PILLAR_RIGHT, car_shape.MARK_RIGHT, car_shape.MARK_NOSE)
LEFT_OF_CENTER, RIGHT_OF_CENTER, NEAR_CENTER = "left", "right", "center"
# 柱と印が、写るはずの側。
PROBE_SIDES = {
    camera.PILLAR_LEFT: LEFT_OF_CENTER, camera.PILLAR_RIGHT: RIGHT_OF_CENTER,
    car_shape.MARK_RIGHT: RIGHT_OF_CENTER, car_shape.MARK_NOSE: NEAR_CENTER,
}
SIDE_WORDS = {LEFT_OF_CENTER: "中央より左", RIGHT_OF_CENTER: "中央より右", NEAR_CENTER: "中央の近く"}
CENTER_X10 = (SCREEN_W - 1) * 5  # 画面の中央の x（0.1画素の単位。画素の番号は 0〜幅−1）
MAX_X10 = (SCREEN_W - 1) * 10  # 重心の x の上限（0.1画素の単位）
BUDGET_SKY, BUDGET_TRACK, BUDGET_CAR = "scene_sky_min_px", "scene_track_min_px", "scene_car_min_px"  # 空、コース、車の画素の下限
BUDGET_MIRROR = "scene_mirror_margin_px"  # 柱と印の重心の、中央からの余裕（画素）
BUDGET_STALE = "scene_stale_max_px"  # 描き直す前と後の、裏画面の違う画素の数の上限
BUDGET_KEYS = (BUDGET_SKY, BUDGET_TRACK, BUDGET_CAR, BUDGET_MIRROR, BUDGET_STALE)  # tools/budgets.json の鍵
PALETTES_FILE = f"palettes{datadefs.SUFFIX}"  # パレットの定義データのファイルの名


def missing_budgets(budgets: dict) -> list:
    """tools/budgets.json に無いか、0以上の整数でない、下限と余裕の鍵。空なら、判定できる。"""
    return [key for key in BUDGET_KEYS if type(budgets.get(key)) is not int or budgets[key] < 0]


def expected_palette(palette_id: str = palette.EVENING, pack=None, data_dir=data_reference.DATA_DIR, packs_root=data_reference.PACKS_ROOT) -> tuple:
    """道具が、パレットの定義データのファイルを自分で読んで取った32色。返すのは (色の並び, 読めなかった理由)。読めなければ、並びは None。

    アプリの読み込み（読み込み検査）は通さない（標準のJSONの読みだけ）。pack は、重ねた試験用データの名（無ければ None）。
    試験用データにパレットのファイルがあれば、同じ id の項目を差し替え、新しい id を足す（アプリの重ね方と同じ）。
    """
    found = {}
    directories = [Path(data_dir)] + ([] if pack is None else [Path(packs_root) / pack])
    for index, directory in enumerate(directories):
        path = directory / PALETTES_FILE
        if index and not path.is_file():
            continue  # 試験用データは、パレットを持たなくてよい
        try:
            for entry in json.loads(path.read_text(encoding="utf-8"))["palettes"]:
                found[str(entry[datadefs.ID_KEY])] = list(entry["colors"])
        except (OSError, ValueError, KeyError, TypeError) as exc:
            return None, f"{path}: {type(exc).__name__}: {exc}"
    if palette_id not in found:
        return None, f"{PALETTES_FILE} に、id が {palette_id!r} のパレットが無い"
    return found[palette_id], ""


def _scene(result) -> dict:
    """結果の scene。辞書でなければ、空の辞書（どの確かめも、合格にしない）。"""
    scene = result.get("scene") if isinstance(result, dict) else None
    return scene if isinstance(scene, dict) else {}


def _count(value) -> bool:
    """0以上の整数か。bool と小数は、数えた値でない。"""
    return type(value) is int and value >= 0


def check_backdrop(scene: dict, budgets: dict) -> tuple:
    """空の画素が、下限以上か。返すのは (合っているか, 合わないときの文)。"""
    sky, low = scene.get("sky"), budgets[BUDGET_SKY]
    return _count(sky) and sky >= low, f"背景が写っていない（空の役割の色の画素が {sky!r}。{low} 以上のはず）"


def check_scene3d(scene: dict, budgets: dict) -> tuple:
    """コースの画素と、車の画素が、どちらも下限以上か。"""
    track, car = scene.get("track"), scene.get("car")
    track_low, car_low = budgets[BUDGET_TRACK], budgets[BUDGET_CAR]
    ok = _count(track) and track >= track_low and _count(car) and car >= car_low
    return ok, f"3Dが描かれていない（コースの画素が {track!r}（{track_low} 以上のはず）、車の画素が {car!r}（{car_low} 以上のはず））"


def probe_problems(scene: dict, margin_px: int) -> list:
    """柱と印の、合わない所の文の一覧。空なら、左右と前後が、正しく写っている。

    どの色も、画素が1つ以上。左の柱の重心は、中央より margin_px を超えて左。右の柱と、模型の右の印は、margin_px を超えて右。
    鼻先の印は、中央から margin_px の内。
    """
    probes = scene.get("probes") if isinstance(scene.get("probes"), dict) else {}
    margin10 = margin_px * 10
    problems = []
    for name in PROBES:
        seen = probes.get(name) if isinstance(probes.get(name), dict) else {}
        pixels, x10 = seen.get("pixels"), seen.get("x10")
        if not _count(pixels) or pixels < 1:
            problems.append(f"{name} が写っていない（画素が {pixels!r}）")
            continue
        if not _count(x10) or x10 > MAX_X10:
            problems.append(f"{name} の重心の x が {x10!r}（0.1画素の単位で 0〜{MAX_X10} のはず）")
            continue
        side = PROBE_SIDES[name]
        offset10 = x10 - CENTER_X10
        placed = offset10 < -margin10 if side == LEFT_OF_CENTER else offset10 > margin10 if side == RIGHT_OF_CENTER else -margin10 <= offset10 <= margin10
        if not placed:
            problems.append(f"{name} の重心が、中央から {offset10 / 10:+.1f} 画素（{SIDE_WORDS[side]}のはず。余裕 {margin_px} 画素）")
    strange = sorted(str(name) for name in probes if name not in PROBES)
    if strange:
        problems.append(f"知らない名の柱か印がある：{strange}")
    return problems


def check_mirror(scene: dict, budgets: dict) -> tuple:
    """左右と前後が、正しく写っているか（柱と印の重心）。"""
    problems = probe_problems(scene, budgets[BUDGET_MIRROR])
    return not problems, "左右か前後が、正しく写っていない：" + "。".join(problems)


def check_palette(scene: dict, want_palette, why: str = "") -> tuple:
    """読み戻した32色が、道具が定義データから自分で読んだ32色と同じか。want_palette が None（読めなかった）なら、合格にしない。"""
    seen = scene.get("palette")
    listed = type(seen) is list and all(type(color) is int for color in seen)
    ok = want_palette is not None and listed and seen == list(want_palette)
    where = [index for index in range(palette.COLOR_COUNT) if listed and want_palette is not None and seen[index:index + 1] != list(want_palette)[index:index + 1]]
    return ok, f"当てたパレットが、定義データと違う（読み戻した色は {seen!r}。違う番号は {where}）{why}"


def check_scene_same(scene: dict) -> tuple:
    """ふだんの実描画が、判定と同じ3Dを描いているか（2Dの描画命令の矩形の外の、違う画素が0）。"""
    outside = scene.get("ink_outside")
    return _count(outside) and outside == 0, f"ふだんの実描画の3Dが、判定用の実描画と違う（2Dの描画命令の矩形の外の、違う画素が {outside!r}。0 のはず）"


def check_back_ink(scene: dict) -> tuple:
    """2Dの描画命令が、裏画面に描かれているか（矩形の内の、違う画素が1以上）。"""
    inside = scene.get("ink_inside")
    return _count(inside) and inside >= 1, f"2Dの描画命令が、裏画面に描かれていない（矩形の内の、違う画素が {inside!r}。1 以上のはず）"


def check_back_live(scene: dict, budgets: dict) -> tuple:
    """周期の中の実描画が、裏画面へ描いているか（描き直す前と後の、裏画面の違う画素が、上限以下）。"""
    stale, high = scene.get("stale"), budgets[BUDGET_STALE]
    return _count(stale) and stale <= high, f"周期の中の実描画が、裏画面へ描いていない（描き直す前と後の、違う画素が {stale!r}。{high} 以下のはず）"


def scene_checks(result: dict, budgets: dict, want_palette, why: str = "", names=SCENE_CHECKS) -> list:
    """結果の scene の確かめ。返すのは [(名前, 合っているか, 合わないときの文)]。並びは names の順。

    budgets は、道具の値（tools/budgets.json。BUDGET_KEYS が要る。無ければ KeyError。先に missing_budgets で見る）。
    want_palette は、道具が自分で読んだ32色（expected_palette。読めなかったら None。合格にしない）。why は、読めなかった理由。
    names は、回す確かめ（既定は、全部。巡回の3Dの絵では、NOT_FOR_SHOTS の2つだけを外す。scene_same は、渡した絵と3枚目が
    同じことを見るので、残す）。知らない名は ValueError。
    """
    strange = [name for name in names if name not in SCENE_CHECKS]
    if strange:
        raise ValueError(f"unknown scene checks: {strange}")
    scene = _scene(result)
    checks = {
        "backdrop": lambda: check_backdrop(scene, budgets),
        "scene3d": lambda: check_scene3d(scene, budgets),
        "mirror": lambda: check_mirror(scene, budgets),
        "palette": lambda: check_palette(scene, want_palette, why),
        "scene_same": lambda: check_scene_same(scene),
        "back_ink": lambda: check_back_ink(scene),
        "back_live": lambda: check_back_live(scene, budgets),
    }
    return [(name, *checks[name]()) for name in names]


def probe_words(result: dict) -> str:
    """件ごとの行に出す、柱と印の値。「名:画素の数@重心の x（画素）」を、PROBES の順に、コンマで並べる。"""
    scene = _scene(result)
    probes = scene.get("probes") if isinstance(scene.get("probes"), dict) else {}
    words = []
    for name in PROBES:
        seen = probes.get(name) if isinstance(probes.get(name), dict) else {}
        x10 = seen.get("x10")
        words.append(f"{name}:{seen.get('pixels')}@{x10 / 10 if type(x10) is int else x10}")
    return ",".join(words)


def perf_words(result: dict) -> str:
    """最後の1行に出す、処理時間の要約（結果の perf。更新1回と実描画1回の、平均/95%点/最大。ms）と、
    実描画のある周期が、1 tickの長さを超えた回数。判定には、使わない（線の判定は、ブラウザ版の煙テスト）。"""
    perf = result.get("perf") if isinstance(result, dict) and isinstance(result.get("perf"), dict) else {}
    update = "/".join(str(perf.get(f"update_ms_{part}")) for part in ("mean", "p95", "max"))
    render = "/".join(str(perf.get(f"render_ms_{part}")) for part in ("mean", "p95", "max"))
    return f"update_ms={update} render_ms={render} cycles_over_tick={perf.get('cycles_over_tick')}"


def stats_words(result: dict) -> str:
    """最後の1行に出す、場面の数（結果の scene_stats。直近に描いた三角形の数、場面を組む時間、メッシュを作る時間、起動にかかった時間。ms）。
    判定には、使わない。"""
    stats = result.get("scene_stats") if isinstance(result, dict) and isinstance(result.get("scene_stats"), dict) else {}
    return (
        f"triangles={stats.get('triangles_drawn')} build_ms={stats.get('build_ms')} mesh_ms={stats.get('mesh_ms')} "
        f"boot_ms={stats.get('boot_ms')} page_ms={stats.get('page_ms')}"
    )


def scene_words(result: dict) -> str:
    """最後の1行に出す、結果の scene の値（空、コース、車の画素。矩形の内と外の違う画素。描き直す前と後の違う画素。3枚目の画素の要約値）。"""
    scene = _scene(result)
    return (
        f"sky={scene.get('sky')} track={scene.get('track')} car={scene.get('car')} "
        f"ink={scene.get('ink_inside')}/{scene.get('ink_outside')} stale={scene.get('stale')} digest={scene.get('digest')}"
    )
