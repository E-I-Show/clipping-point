# CLIPPING POINT 技術スパイク共通ブリーフ

このファイルは、実装設計を書く前に前提を実機で確かめる調査（スパイク）の共通資料です。
設計書そのものではありません。あなたの調査結果が設計書の根拠になります。

## 1. 作るもの（確定した企画の要点）

- タイトル: CLIPPING POINT。Pyxel 製、初代PS時代風ローポリの 3D レースゲーム。ブラウザで動く単一 HTML（pyxel app2html）で配布。
- 見た目と挙動はリアル寄り。セッティングは 6 項目の段階選択だけ。
- モード: タイムアタック（1台+自己ベストのゴースト、直近5周までリプレイ対象）/ シングルレース（AI 5台+自車=6台、3/5/10周）/ シアター（保存リプレイの一覧・再生・書き出し・読み込み）。
- 初期版の範囲: 車4台、コース1本。
  - ツバメ 1600: FF 165ps 1,040kg クラスB（安定・アンダー）
  - カザネ RS: FR 145ps 960kg クラスB（軽量・素直）
  - シロガネ GT-T: FR 280ps 1,340kg クラスA（ターボ。立ち上がりでリアが流れる）
  - アラシ 4T: 4WD 280ps 1,390kg クラスA（ターボ。立ち上がり最速・重い）
  - （初期版の後に追加: ミカヅキ MR 240ps 1,180kg / イカヅチ V8 FR 320ps 1,480kg）
  - コース: アカネ・ショート 全長約1.8km、9コーナー、ヘアピン2か所、低中速テクニカル、時間帯は夕方。目標ラップはクラスAで約1分、クラスBで約1分5秒。
  - （後に追加: カスミ・ヒルズ 3.2km 高低差40m / ミナト・ベイ 4.1km 高速）
- セッティング6項目（確定）: ギア比(5段階: 加速↔最高速) / ウイング(5: ダウンフォース小↔大) / サスペンション(5: ソフト↔ハード) / ブレーキバランス(5: 前寄り↔後寄り) / トラクション=LSDの効き(5: 回頭性↔立ち上がり) / ステアリング=車側の舵の速さ(3: マイルド↔クイック)。全項目中央が標準。別枠で 変速 AT/MT、アシスト ON/OFF。
- 走行挙動: 自前の車両モデル。前後・横・ヨーの3自由度、4輪のタイヤ（滑り角・滑り率・摩擦円、限界を超えるとグリップが落ちる）、荷重移動、駆動方式差(FF/FR/MR/4WD)、ターボの遅れ、空力、路面4種（アスファルト/縁石/芝/グラベル）、接触は押し戻しと減速のみ（ダメージなし）。再現しないもの: タイヤ温度と摩耗、燃料、ダメージ、天候、ピット。
- AI: コースごとの理想ライン（位置と目標速度）を追う。EASY/NORMAL/HARD。追い付き補正なし。
- リプレイ: 状態記録方式。全車の位置と姿勢を毎秒20回記録し再生時に補間。1台1回分14バイト（位置xyz各16bit、ヨー16bit、ピッチ・ロール各8bit、舵角8、回転数8、ギアとフラグ8、予備8）。差分化+zlib。カメラ4種（TV=コースサイド固定カメラ自動切替 / チェイス / 車載 / ヘリ）。一時停止・スロー(1/2,1/4)・早送り(2x,4x)・巻き戻し・周回頭出し・注目車切替・HUD切替・直近10秒GIF保存。
- シアター: ブラウザ内保存（localStorage、12本・合計3MBまで）とファイル（.cpr）の書き出し/読み込み（ドラッグ&ドロップ、スマホはファイル選択）。.cpr はヘッダ/本体/チェックサム。
- 画面: 320x240、整数倍拡大。パレット32色（コースの時間帯で差し替え）。陰影はPyxel Cubeの8段階ディザ。車1台150〜250ポリゴン、コース画面内2,000〜3,000ポリゴン、描画距離約300m、遠景は空と山並みの1枚絵。HUDは英数字のみ（Pyxel内蔵フォント）。
- サウンド: Pyxel内蔵4ch。走行中 ch0 自車エンジン（ループ音のピッチを回転数で変える）/ ch1 スキール / ch2 効果音 / ch3 近い他車のエンジン。BGMはメニュー・リプレイ・リザルトの3曲、走行中は無し。

## 2. 今回ユーザーが決めたこと（最優先の要件）

1. 実行環境は起動時にネットから読み込む形でよい（app2html の標準形）。
2. **描画は 30 fps、入力処理と物理演算は 60 fps（毎秒60回の固定刻み）**。
3. 画面内の文字は英数字のみ。
4. 名称は確定。初期版は車4台とコース1本。
5. 操作: **PCのアナログコントローラーが本命**。デジタル操作（キーボード・十字キー）でも慣れればコースアウトせずに走れる程度にしたい。
   - アナログ・デジタルを問わずアシスト（入力補正）が必要。
   - ステアリングの切り始めから最大舵角までの切れ角のカーブ、アクセル・ブレーキの踏み込み量のカーブを、ある程度調整できるようにする。
   - 車速に応じて最大の切れ角を調整する。
   - カウンターステアのときは最大角度の制限を弱める。
6. セッティングは上の6項目で確定。

## 3. 進め方の前提（game-dev-pilot スキル）

開発は添付スキル game-dev-pilot の流儀で進める（スキルの写し: `<scratchpad>/skill_gdp/game-dev-pilot/`）。土台の原則:

- **ロジックをエンジンから切り離す**: ゲームの規則・式・世界の状態・リプレイ・セーブは pyxel を import しない純 Python のライブラリに置く。pyxel 側は表示と入力の薄いアダプタ。
- GUI 無しで全部回せる（ヘッドレス実行、N フレームで終わる煙テスト、スクリーンショット巡回）。
- 決定性（固定刻み、乱数ストリーム、指紋テスト）。
- データ駆動と読み込み時の検査。
- 見かけの合格を潰す（0件や未評価を合格にしない。わざと壊して落ちるか確かめる）。

## 4. この環境と、Pyxel 3.0.1 について確かめ済みの事実

環境: Linux コンテナ、Python 3.13、`pip install pyxel` 済み（Pyxel 3.0.1）。ディスプレイも音デバイスも無いので `pyxel.init(..., headless=True)` を使う（ALSA のエラー出力は無視してよい）。
ネットワーク: PyPI と GitHub（raw.githubusercontent.com）は取得できる。**kitao.dev は遮断されている**（Pyxel Web ランタイムの配信元。プロキシが 403 を返す）。
Pyxel のソースは `https://raw.githubusercontent.com/kitao/pyxel/main/<path>` で読める。

型定義とサンプル（一次情報。必ずここで API を確かめる。記憶で API を書かない）:
- `/usr/local/lib/python3.13/site-packages/pyxel/__init__.pyi`（2D・入力・音・システム）
- `/usr/local/lib/python3.13/site-packages/pyxel/cube/__init__.pyi`（3D: Pyxel Cube）
- `/usr/local/lib/python3.13/site-packages/pyxel/examples/`（`cube/c01〜c06`、`04_sound_api.py`、`14_synthesizer.py`、`18_audio_playback.py`、`19_perspective.py` など）
- `/usr/local/lib/python3.13/site-packages/pyxel/cli.py`（package / app2html の実装）
- 取得済みの Web ランタイム: `<scratchpad>/pyxel_probe/web/pyxel.js`、変更履歴 `<scratchpad>/pyxel_probe/web/CHANGELOG.md`

確かめ済み（前段の調査で実行または一次情報で確認）:
- `pyxel.init(width, height, title, fps=30, quit_key, display_scale, capture_scale=2, capture_sec=10, headless=False)`。`pyxel.run(update, draw)`、`pyxel.flip()`、`pyxel.quit()`。
- `pyxel.colors` は 1〜256 色。`pyxel.colors[:] = [...]` で置換。既定は16色。画像バンクは 3 枚（256x256）、`pyxel.Image(w, h)` で任意サイズを作れる。
- 入力: `btn / btnp / btnr / btnv`、`GAMEPAD1_AXIS_LEFTX/LEFTY/RIGHTX/RIGHTY/TRIGGERLEFT/TRIGGERRIGHT`、`GAMEPAD1_BUTTON_A/B/X/Y/BACK/START/DPAD_*` など。`set_btn / set_btnv`（入力の注入）と `dropped_files` がある。
- 音: 4ch。`Channel.gain`、`Channel.detune`（セント単位）、`Channel.play(snd, sec, loop, resume)`（MML 文字列も可）、`Sound`、`Tone`、`gen_bgm`。
- `pyxel.screenshot(filename, scale)`、`pyxel.screencast(filename, scale)`（Web 版ではブラウザのダウンロード）。`pyxel.screen` は Image。
- Pyxel Cube（3.0.0 で追加。ソフトウェア描画の3D）: `Vec3 / Mat4 / Quat / Camera(transform, fov, near, far, ortho_size, clear_color) / Shading(colors)（LEVEL_COUNT=8。(色, レベル)→2色の対＝ディザ） / Primitive(mode, positions, indices, normals, uvs, cull)（plane/box/sphere/capsule の生成あり） / Mesh(primitives, transforms, parents, names, col_img, colkey)（from_glb あり） / Node（シーングラフ。on_update / on_draw、prim / box / sphere / plane / sprite / tri / line / text / decal / depth_test / depth_write / depth_offset / dither / shaded、draw(x, y, w, h, target)、raycast、overlap_*） / Collider`。
- `pyxel package APP_DIR STARTUP.py` → `.pyxapp`（zip, deflate）。`pyxel app2html X.pyxapp` → `<script src="https://kitao.dev/pyxel/3.0.1/pyxel.js">` と `launchPyxel({command:"play", name, gamepad:"enabled", base64})` だけの HTML。
- Web ランタイムは Pyodide 314.0.7。仮想ゲームパッド（十字+A/B/X/Y+START/BACK）あり。画面へのファイルドロップは `/tmp/<名前>` に書かれ `pyxel.dropped_files` に入る。`window._savePyxelFile(filename)` が仮想FSのファイルをダウンロードさせる。IndexedDB や localStorage を扱うコードはランタイムに無い。
- 実測（このコンテナ、ネイティブ headless）: 320x240 でテクスチャ付き約8,000三角形+箱12個の `scene.draw` が約2.0 ms。8,192三角形のメッシュコライダーへの `raycast` が約4.7 µs/本。
- リプレイ試算（疑似データ）: 14バイト×20Hz を差分化+列並べ+zlib で約36%（6台5分で生492KB→177KB）。

## 4b. 先行スパイクで確かめたこと（以後の調査はこれを前提にする）

フレームループとヘッドレス実行（確かめ済み。試作: `<scratchpad>/spikes/frameloop/proto/`、結果の全文: 同 `frameloop/RESULT.json`）:
- ループは `pyxel.init(320, 240, fps=60, quit_key=pyxel.KEY_NONE)`。update 1回 = 入力を1度読み 1 tick（1/60秒）進める。draw は「前回の実描画から 2 tick 以上、または 1 tick 以上かつ 30 ms 以上経過」のときだけ実描画する（frame_count の偶奇は使えない）。3D と HUD は裏画面 `pyxel.Image(320, 240)` に描き（Cube は `Node.draw` の target 引数）、draw では毎回 blt で画面へ写す。
- Pyxel は遅れた分の update を先に回して draw を飛ばす。描かないフレームでは前の画面が残る。
- ヘッドレスでも `pyxel.run` / `pyxel.flip` は実時間待ちをする。速く回すには自前ループ + `pyxel.flip` + fps=1000（約900フレーム/秒）。flip を呼ばずに update / draw だけ呼ぶと入力状態が進まない。`pyxel.flip` はブラウザ版では使えない。
- `pyxel.quit()` は常に終了コード 0 で即終了する（finally は走らない）。pytest の中で呼ぶと失敗が消える。Pyxel を通すテストは別プロセスで動かし、終了は `sys.exit(code)`、合否は「終了コード + 全 tick 後に書く結果ファイル + 指紋」で判定する。update / draw 内の例外は終了コード 1。
- `pyxel.init` は 1 プロセス 1 回で、呼び出したファイルのディレクトリへ chdir する。ファイルは `Path(__file__)` 基準で読む。
- `pyxel.set_btn` / `set_btnv` は同じフレームの btn / btnp / btnv に反映される。軸に btn、ボタンに btnv を呼ぶと PanicException。スティックは -32768..32767、トリガーは 0..32767。デッドゾーン処理は無い。
- `pyxel.screen.save(path, scale)` で PNG を保存できる。
- `pyxel package` は APP_DIR 直下に main.py が要る。除外は「.」始まり、`__pycache__`、`.gif`、`.zip`。

ブラウザ版（Pyodide）の実動作（確かめ済み。道具: `<scratchpad>/spikes/web/tools/`）:
- この環境でも、GitHub（kitao/pyxel v3.0.1 の wasm/）と npm（pyodide 314.0.7）から取得したランタイムの写しを使い、Pyxel Web をヘッドレス Chromium で動かせる。Python は 3.14.2、`sys.platform` は `"emscripten"`。
- 自分のアプリをブラウザ版で動かす手順（`spikes/web` には書き込まない。読むだけ）:
  1. 自分のディレクトリに APP_DIR（直下に main.py）を作り、`pyxel package APP_DIR APP_DIR/main.py`、続けて `pyxel app2html APP.pyxapp` で HTML を作る。
  2. `node <scratchpad>/spikes/web/tools/webrun.js --url 自分の.html --mirror <scratchpad>/spikes/web/mirror --until '^SPIKE_DONE' --timeout 120000 --json 結果.json --shot 画面.png`
  3. アプリは結果を print（1行の JSON など）し、最後に `print("SPIKE_DONE")` する。print はブラウザのコンソールに出て、結果.json の console に入る。終了コード 0 が成功。Python の例外や無応答は失敗になる。全オプションは webrun.js の冒頭のコメントにある。ブラウザ版では `pyxel.run` を使う（flip は不可）。時間は `time.perf_counter()` で測る。
- 実測（ヘッドレス Chromium、このコンテナ）: 純 Python の速さはネイティブ CPython 3.13 の約 1/2（1.8〜2.2 倍遅い。最初の1回だけ 3〜4.5 倍）。Pyxel Cube の描画はテクスチャ付き 8,192 三角形で 2.4 ms（ネイティブ 1.8 ms）。fps=60 で update は毎秒 60.0 回、描画の間引きで実描画 30 回/秒を保てた。
- ゲームパッド: Pyxel 経由（btnv）ではスティックはアナログだが、**トリガーは 0 か 32767 の 2 値になる**（偽のゲームパッドで確認）。Python から `import js` で `js.navigator.getGamepads()` を直接読むと、トリガーのアナログ値（`buttons[6].value` / `buttons[7].value`、0..1）が取れる（1回 約0.05 ms）。本命のアナログ操作は、ブラウザではこの直読みを使う。
- 数学関数（sin / cos / atan2 など）の結果は、ネイティブとブラウザで 3〜24% の入力について最下位 1 ビットの差が出る。浮動小数の計算結果が環境をまたいで一致する前提は置けない（同じ環境の中では一致する）。

## 5. スパイクの約束

- 作業は自分に割り当てられたディレクトリの中だけで行う（ほかのスパイクのディレクトリは読むだけ）。`/home/user` には何も書かない。
- 追加のパッケージは、調査にどうしても要るものだけ pip で入れてよい（pytest など）。入れたものは報告に書く。
- **確かめたこと（実行して結果を見た・一次情報を読んだ）と、推測を分けて書く。** 実行できなかったこと・確かめられなかったことは「未確認」として必ず挙げる。0件や未実行を「問題なし」と書かない。
- 数値は実測の条件（何を、何回、どの環境で）を添える。ブラウザ版（Pyodide/WebAssembly）の数値はこの環境では測れない。ネイティブの数値から決めつけず、未確認と書く。
- API は型定義・サンプル・ソースで確かめてから使う。存在しない関数や引数を書かない。
- 深追いしすぎない。設計判断に必要な答えが出たら止め、残りは未確認に書く。
- 報告用のファイル（REPORT.md など）は作らない。報告は最後の構造化出力の各欄に、省略せず詳しく書く（式、値の表、手順、コードの要点も）。あなたの構造化出力がそのまま設計書の根拠になる。コードの識別子は英語、説明は日本語。
- 作業ディレクトリに前回中断した作業のファイルが残っていることがある。最初に一覧を見て、使えるものは使う。
- 時間をかけすぎない。目安は30分以内。途中でも分かったことから構造化出力にまとめられるよう、実験の結果は自分のディレクトリの小さなファイル（JSON やテキスト）に都度残す。
