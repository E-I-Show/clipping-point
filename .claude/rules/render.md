---
paths:
  - "clipping_point/cp_app/render.py"
  - "clipping_point/cp_core/camera.py"
  - "clipping_point/cp_core/palette.py"
  - "clipping_point/cp_core/mesh.py"
  - "clipping_point/cp_core/car_shape.py"
  - "clipping_point/data/cameras.json"
  - "clipping_point/data/palettes.json"
  - "tools/scene_reference.py"
  - "tools/claude/make_palette.py"
  - "tests/test_render.py"
  - "tests/test_camera.py"
  - "tests/test_palette.py"
  - "tests/test_mesh.py"
  - "tests/test_car_shape.py"
  - "tests/test_scene_reference.py"
---

# 3Dの描画（3Dの場面、カメラ、色の役割、メッシュ用の数値、車の仮の形、3Dの絵の判定）

## 約束

- 3Dの形は、純Pythonの層で、数値（`cp_core/mesh.py` の `MeshPart`）として作る。Pyxelの3D（`pyxel.cube`）に触れるのは `cp_app/render.py` だけ。
- `render.py` は pyxel をimportしない。Pyxelは `Scene` の引数で受け、偽の Pyxel でテストする。場面は `main()` が作り、`pyxel.init` の後に `build()` で組む。
- 座標は2つ。形を作る所の注に、どちらかを書く。取り違えると、絵が鏡写しになる。
  - ロジックの座標：コース、地面、カメラの目と注視点、車の位置、判定用の柱。+z は、+x の左。`to_cube()` を通す（z を反転し、メッシュは頂点の順も入れ替える）。
  - 模型の座標：車の模型と、模型に付ける印。鼻先が +X、右が +Z、上が +Y、原点は接地中心。そのまま渡し、車の根の変換の下に置く。
- z の反転と、頂点の順の入れ替えを書くのは `to_cube()` の1か所だけ。`cp_core` と、ほかの `cp_app` では、反転しない。車の向きは `rotate_y(degrees(向き))`。
- 面の向きは、どちらの座標でも、(b−a)×(c−a) が外向き（`mesh.face_normal()`）。新しい形は、純Pythonのテストで見る。裏の面は、捨てる。
- 実描画の順：背景 → 3D（根の draw を1回。背景を消さない設定）→ 2Dの描画命令 → 画面へ写す。
- 描く口は `Scene.draw()` の1つ。ふだんの実描画、判定用の4枚、巡回の3Dの絵が、ここを通る。描くものは `layers`。
- パレットを当てるのは `apply_palette()` の1か所。色の番号は、役割の名（`cp_core/palette.py`）で引く。部品の中は、1色。
- カメラは、目と注視点を、ロジックの座標で返す。前の呼び出しの値を持たない。画角は、縦の画角（度）。
- 寸法と値は、定義データ：表 `cameras`、表 `palettes`、車の `shape`、コースの `mesh`（`track.md`）。仮の絵の背景と地面の寸法だけは `render.py` の定数（割り切りの印つき。段1の「コースの描画」で作り直す）。
- 車輪は、車体の子にしない（車の根の下）。
- 判定用の柱と印（片面の板。陰影を切る。表は、車の後ろ向き）と、判定用の実描画（`Scene.judge()`）は、検証の口があるときだけ。ふつうの起動では、作らない。
- 判定は、結果を書く直前に、裏画面を読んでから（周期の中の実描画が描いた絵。`before`）、描き直して。後で、柱と印を隠し、コースと車を戻す（例外でも）。合否と文は `tools/scene_reference.py` の1か所。
- 描いた結果と、測った値は、世界へ戻さない。

## 値を読む口

- 役割の名と番号：`palette.ROLES`、定数（`palette.WHITE` など）、`number()`、`SKY`、`MOUNTAINS`、`FAR_GROUND`。使うパレットの id：`EVENING`
- カメラ：`CameraSpec`、`spec_from_entry()`、`chase_pose()` → `CameraPose`（`eye`、`target`、`heading`、`pitch`）。使う項目の id：`CHASE`
- 塊が見えるか：`chunk_visible()`。背景：`focal_px()`、`backdrop_period_px()`、`backdrop_shift_px()`、`horizon_row()`
- 形：`mesh.box()`、`board()`、`quad()`、`car_shape.build_car_shape()` → `CarShape`（`body`、`wheel`、`wheel_centers`）
- 柱と印：`camera.pillar_parts()`、`car_shape.mark_parts()`。部品の名が、結果の `scene` の `probes` の鍵
- 場面：`Scene.chase()`、`draw()`、`judge()`、`stats`（三角形の数、組む時間）。描くもの：`LAYERS`、`NORMAL`。画素：`read_pixels()`、`count_diff()`、`split_diff()`、`color_centroid()`
- 結果の `scene` の形、確かめの名、道具の値の鍵：`scene_reference.py` の頭の注、`SCENE_CHECKS`、`BUDGET_KEYS`

## Xを足したらYも

- 色の役割を変えたら、`ROLES`、定数、`test_palette.py` の `DESIGN`、`make_palette.py` の昼の色を、一緒に変える。
- パレットの色は、`make_palette.py` の定数を変え、出た行を `palettes.json` へ写し、`--check` を回す。手で書き換えない。
- カメラを足したら、表 `cameras` の項目、id の定数、位置を作る関数、テストに足す。
- 車の `shape` に鍵を足したら、`CAR_FIELDS`、`car_shape.py`、実物と試験用データの車に足す。矛盾しうる値は `shape_problems()` に足す。
- 描くものを足したら、`LAYERS`、`show()`、`test_render.py` の偽のノード。
- 柱か印、判定の値を足したら、`judge()`、`scene_reference.py`（`PROBES`、`SCENE_CHECKS`）、テスト、`selftest_break.py`。

## テストと道具

- テスト：`test_render.py`（偽の Pyxel。変換、描く口、判定の後の戻し、アプリの配線の守り）、`test_mesh.py`、`test_camera.py`、`test_palette.py`、`test_car_shape.py`、`test_scene_reference.py`。
- 道具 run：確かめ `backdrop`、`scene3d`、`mirror`、`palette`、`scene_same`、`back_ink`、`back_live`。巡回 `tour.py --only scene`（`out/tour/scene_<名>.png`。`NOT_FOR_SHOTS` の2つは回さない）。web-smoke の筋書き `drive`。
- 補助 `python3 tools/claude/make_palette.py [--check]`。
- selftest-break の `run_scene_`、`run_drive_`、`tour_scene_`、`tour_heading_`、`test_render_`、`web_drive_`（3Dの絵を壊す）、`test_camera_`、`test_mesh_`、`test_car_shape_`、`test_scene_`、`check_data_palette`、`check_data_camera`、`check_data_car_shape_`、`make_palette_` で始まる件。

## 落とし穴

- 向き0、z=0 のスタート位置では、向きの符号の誤りと、反転の付け忘れが、絵に出ない。拾うのは、走る台本の回と、巡回。背景をずらす量の誤りは、道具に頼らない（テストで、写す x を固定）。
- 描き直した絵を見る確かめ（`scene_same`、`back_ink`）は、周期の中で描かない回を通す。拾うのは `back_live`（走る回）と、守りのテスト。
- ふつうの起動（検証の口が無い）を実物で通すのは、web-smoke の `shipped` だけ（色の数）。描く文を、条件の下に置かない。
- 模型をロジックの座標と同じ扱いにすると、車だけが鏡写しになる。箱の輪郭は変わらない（片面の印が0画素になる）。
- 深度の記録は、draw の呼び出しごとに消える。画面外のノードは、自動では捨てられない（塊を隠す）。
- UVは0〜1に切り詰められ、繰り返せない。`pyxel.pal` は、3Dに効かない。描画の状態（陰影を切る）は `on_draw` の中で。
- 陰影は、パレットの近い暗色を選ぶ。主要な色には、1段暗い兄弟色が要る。灯火は `unshaded`。
- 手前の切り取り面は、1.0 を超えると足元が欠ける。背景をずらす量は、画面の高さから。
- `data_ptr()` は、ブラウザ版でも使える。パレットは `pyxel.init` の後に当てる。
