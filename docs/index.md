# docsの目次

> 要約：`docs/` にある文書の1行の説明と状態。文書を足したら、ここに1行足す。

## 常に使うもの

| 文書 | 中身 | 状態 |
| --- | --- | --- |
| [handoff.md](handoff.md) | 作業の控え。25行まで。再開のとき最初に読む | 区切りのコミット、途中のコミット、止める前に上書き |
| [worklog.md](worklog.md) | 作業記録。状態の表、次の手、決めた細目、検証の行、事後報告 | 区切りごとに追記 |
| [plan.md](plan.md) | 開発計画。段の並び、区切り、通過条件、検証の組、文書とClaude Codeの構成 | 確定（2026-11-11）。段の区切りは、その段の設計で確定させる |
| [standing-policy.md](standing-policy.md) | 常設の方針。伺いの回答を、方法と理由の形で書いたもの | 確定（2026-11-11）。指示をいただいたら足す |
| [glossary.md](glossary.md) | 言葉の表 | 語を足すたびに更新 |

## 作るものの元

| 文書 | 中身 | 状態 |
| --- | --- | --- |
| [canon/planning.md](canon/planning.md) | 企画書。正本。Claudeは書き換えない | 確定（2026-11-11） |
| [proposals/](proposals/README.md) | 改訂案。正本とのずれと、方向を決める材料 | 1件ごとの状態は `proposals/README.md` の一覧 |
| [design/overview.md](design/overview.md) | 実装設計。全体の設計 | 確定（2026-11-11）。批評と確かめを反映済み |

段ごとの設計と批評は、段の開始時に `design/` へ足します。

## 頼みの文

| 文書 | 中身 | 状態 |
| --- | --- | --- |
| [requests/README.md](requests/README.md) | 頼みの文のひな形と、置いてある頼みの文の一覧 | 区切りの頼みを足すたびに更新 |
| [requests/stage0-k3.md](requests/stage0-k3.md) | 段0の区切り3（環境とブラウザ版の煙テスト）を、実装役に頼む文 | 実装済み |
| [requests/stage0-k5.md](requests/stage0-k5.md) | 段0の区切り5（入力の土台）を、実装役に頼む文。主が決めた細目17件の表つき | 実装済み |
| [requests/stage0-k6.md](requests/stage0-k6.md) | 段0の区切り6（画面の検査と巡回）を、実装役に頼む文。主が決めた細目17件の表つき | 実装済み |
| [requests/stage0-k7.md](requests/stage0-k7.md) | 段0の区切り7（保存と決定性の土台）を、実装役に頼む文。主が決めた細目23件の表つき | 実装中 |

## 調べ

| 文書 | 中身 | 状態 |
| --- | --- | --- |
| [research/claude-code-config.md](research/claude-code-config.md) | Claude Codeの設定の書式（サブエージェントの型、規則ファイル、フック、禁止する操作） | 新しいセッションで確かめた（7点とも通った） |

## 進み具合と、済んだ作業の結果

| 文書 | 中身 | 状態 |
| --- | --- | --- |
| [day1-checklist.md](day1-checklist.md) | 段0で置くものの進み具合 | 段0の間だけ更新 |
| [reports/](reports/README.md) | 進捗レポート。およそ1時間ごと | 追記 |
| [review/](review/README.md) | 着手前の設計に対する批評と確かめの記録 | 済。足さない |
| `reviews/` | 区切りごとのレビューの結果（通った指摘、退けた指摘と理由、役が見られなかった所）。`tools/claude/review_summary.py --out` が書く。実装の前に頼みの文を確かめたときは、`stageN-kM-request.txt` の名で置く | 区切りごとに1つ足す |
| [img/](img/) | 文書の図と、試作の画面 | 設計時のもの |

## docsの外にあるもの

| 場所 | 中身 |
| --- | --- |
| `CLAUDE.md` | 根の決まり。200行まで |
| `.claude/rules/` | 分野ごとの規則ファイル。分野の最初のファイルを作る区切りで足す |
| `spikes/README.md` | 設計時の試作と実測の記録の案内 |
