---
paths:
  - "clipping_point/cp_core/camera.py"
  - "clipping_point/cp_core/palette.py"
  - "clipping_point/cp_core/mesh.py"
  - "clipping_point/cp_core/car_shape.py"
  - "clipping_point/data/cameras.json"
  - "clipping_point/data/palettes.json"
  - "tools/scene_reference.py"
  - "tools/claude/make_palette.py"
  - "tests/test_camera.py"
  - "tests/test_palette.py"
  - "tests/test_mesh.py"
  - "tests/test_car_shape.py"
  - "tests/test_scene_reference.py"
---

# 3Dの描画（カメラ、色の役割、メッシュ用の数値、車の仮の形、3Dの絵の判定）

## 約束

- 3Dの形は、純Pythonの層で、数値（頂点、三角形、色の役割の名。`cp_core/mesh.py` の `MeshPart`）として作る。Pyxelの3Dの物にするのは `cp_app/render.py` だけ。
- 座標は2つ。形を作る所の注に、どちらの座標かを書く。取り違えると、絵が鏡写しになる。
  - ロジックの座標：コース、地面、カメラの目と注視点、車の位置、判定用の柱。+z は、+x の左。Pyxelへ渡すとき、z の符号を反転し、メッシュは頂点の順も入れ替える。
  - 模型の座標：車の模型と、模型に付ける印。鼻先が +X、右が +Z、上が +Y、原点は接地中心。Pyxelへ、そのまま渡す（反転も、入れ替えも、しない）。
- 面の向きは、どちらの座標でも同じ決まり：頂点の3つ組を、そのままベクトルとして、(b−a)×(c−a) が外向き（`mesh.face_normal()`）。新しい形は、純Pythonのテストで、面の向きを見る。
- z の反転と、頂点の順の入れ替えを書くのは、`cp_app/render.py` の1つの関数だけ。`cp_core` では、反転しない。
- カメラは、目と注視点を、ロジックの座標で返す。前の呼び出しの値を持たない。画角は、縦の画角（度）。
- 色の番号は、直に書かない。役割の名（`cp_core/palette.py`）で引く。番号の役割は、どの時間帯でも同じ。
- 部品の中は、1色。模様は入れない（段1の「コースの描画」）。
- 寸法と値は、定義データに置く：カメラは表 `cameras`、パレットは表 `palettes`、車の仮の形は車の項目の `shape`、メッシュの寸法はコースの項目の `mesh`（`track.md`）。
- 車輪は、車体の箱の子にしない（車の根の下に置く）。
- 判定用の柱（ロジックの座標）と印（模型の座標）は、検証の口があるときにだけ作る。片面の板で、表が、車の後ろ（カメラの側）を向く。
- 3Dの絵の判定（合否と文）は `tools/scene_reference.py` の1か所。道具ごとに書かない。

## 値を読む口

- 役割の名と番号：`palette.ROLES`、定数（`palette.WHITE` など）、`number()`、`SKY`、`MOUNTAINS`、`FAR_GROUND`。使うパレットの id：`EVENING`
- カメラ：`CameraSpec`、`spec_from_entry()`、`chase_pose()` → `CameraPose`（`eye`、`target`、`heading`、`pitch`）。使う項目の id：`CHASE`
- 塊が見えるか：`chunk_visible()`。背景：`focal_px()`、`backdrop_period_px()`、`backdrop_shift_px()`、`horizon_row()`
- 箱と板：`mesh.box()`、`mesh.board()`、`mesh.quad()`
- 車の仮の形：`car_shape.build_car_shape(車の項目)` → `CarShape`（`body`、`wheel`、`wheel_centers`）
- 柱と印：`camera.pillar_parts()`、`car_shape.mark_parts()`。部品の名が、結果の `scene` の `probes` の鍵
- 結果の `scene` の形、確かめの名、道具の値の鍵：`tools/scene_reference.py` の頭の注、`SCENE_CHECKS`、`BUDGET_KEYS`

## Xを足したらYも

- 色の役割を変えたら、`ROLES`、定数、`tests/test_palette.py` の `DESIGN`、`make_palette.py` の昼の色を、一緒に変える。
- パレットの色は、`make_palette.py` の定数を変え、出た行を `palettes.json` へ写し、`--check` を回す。手で書き換えない。
- カメラを足したら、表 `cameras` の項目、id の定数、位置を作る関数、テストに足す。
- 車の項目の `shape` に鍵を足したら、`CAR_FIELDS`、`car_shape.py`、実物と試験用データの車に足す。矛盾しうる値は `shape_problems()` に足す。
- 柱か印を足したら、`scene_reference.py` の `PROBES` と `PROBE_SIDES` に足す。判定を足したら、`SCENE_CHECKS`、テスト、`tools/selftest_break.py` に足す。

## テストと道具

- テスト：`test_mesh.py`、`test_camera.py`、`test_palette.py`、`test_car_shape.py`、`test_scene_reference.py`（確かめごとの、合う場合と合わない場合）。コースのメッシュは `test_track.py`。
- 作業の補助 `python3 tools/claude/make_palette.py [--check]`：夕方の32色を、試作の昼の32色から作る、定義データと照らす。
- 道具 selftest-break の `test_camera_`、`test_mesh_`、`test_car_shape_`、`test_scene_`、`check_data_palette`、`check_data_camera`、`check_data_car_shape_`、`make_palette_` で始まる件。

## 落とし穴

- 模型の座標は右手系で、Pyxelの3Dと同じ。ロジックの座標と同じ扱い（反転と入れ替え）にすると、車だけが鏡写しになる。箱の輪郭は変わらないので、絵では気づきにくい（片面の印の画素が0になることで拾う）。
- 向き0、z=0 のスタート位置では、向きの符号の誤りと、反転の付け忘れが、絵に出ない。向きが 0、π/2、π から離れた所でも見る。
- 背景をずらす量は、画面の高さから作った焦点距離で決まる（幅ではない）。
- 手前の切り取り面は、1.0 を超えると足元が欠ける（試作の実測）。表の定義の範囲で、止めている。
- 陰影は、パレットの中の近い暗色を選ぶ。主要な色には、1段暗い兄弟色が要る。灯火の色は、パレットの `unshaded` に入れる。
