# Claude Codeの設定の書式（調べ）

> 要約：段0の区切り4（Claude Codeの整え）で置く、サブエージェントの型、規則ファイル、フック、禁止する操作の書式を、公式の文書で調べたもの（2026-11-11。Claude Code 2.1.322）。設定と型は、段0の区切り4で置いた。効くかどうかは、新しいセッションで確かめる（末尾の表）。

出どころは、Claude Codeの公式の文書（code.claude.com/docs/en/ の sub-agents、memory、hooks、permissions、permission-modes、settings、claude-code-on-the-web）。

## サブエージェントの型（`.claude/agents/<名>.md`）

- 頭の項目で必須なのは `name` と `description`。知らない項目は黙って無視される（大文字と小文字を区別する）。
- `tools`：`Read, Grep, Glob, Bash` のように並べる。省くと全部を引き継ぐ。`disallowedTools` で外せる。
- `model`：別名か完全な名、または `inherit`。
- CLAUDE.mdを読ませない：`omitClaudeMd: true`。
- cacheを1時間にする：`experimental:` の下に `cacheTtl: 1h` と書く（いちばん上の階層には書かない）。
- ほかに、`permissionMode`、`maxTurns`、`skills`、`hooks`、`memory`、`background`、`effort`、`isolation`、`color`。
- 新しい定義は、ふつうはすぐ使える。ただし、セッションの開始時に `.claude/agents/` が無く、途中で作った場合は、セッションを作り直す必要がある。
- 親の権限の決まり（禁止を含む）を引き継ぐ。
- 組み込みの Explore と Plan は、CLAUDE.mdを読まない。ほかは、既定で読む。

## 規則ファイル（`.claude/rules/<名>.md`）

- 頭の `paths:` は、YAMLの並びで書く。globと波括弧が使える。基点は `.claude` の親のディレクトリ。
- 当たるファイルを Read、Write、Edit したときと、Bashの cat や head で1つのファイルを読んだときに、読み込まれる。Grepは対象の外と読める（文書に明記は無い）。
- `paths:` の無い規則ファイルは、常に読まれる。
- 大きさの上限は、文書に見つからなかった。
- サブエージェントに届くかは、文書に明記が無い。頼みの文で、規則ファイルの名を挙げる。
- このセッションで見たこと：`tools/` と `clipping_point/cp_ui/` のファイルをcatで読んだときに、tools.md と ui.md が読み込まれた。

## フック（`.claude/settings.json` の `hooks`）

- SessionStart の matcher に書ける値は、startup、resume、clear、compact、fork。
- SessionStart では、標準出力に出した文が、そのまま文脈に入る。
- matcher を `|` で並べられるかは、確かめられなかった。分けて書くか、スクリプトの中で種類を見る。
- `command` は、文字列ならシェルに渡される。`${CLAUDE_PROJECT_DIR}` が使える。`timeout` は秒。
- PreCompact の標準出力は、圧縮の要約への指示になる。
- 設定の変更は、ふつうは走っているセッションにもすぐ効く。
- クラウドのセッション：リポジトリが1つのセッションは、cloneの中の `.claude/settings.json` を読む。プロジェクトのスレッドでは、当たらない。環境変数 `CLAUDE_CODE_REMOTE` が `true` になる。
- 見本：

```json
{"hooks": {"SessionStart": [{"matcher": "compact", "hooks": [
  {"type": "command", "command": "python3 \"${CLAUDE_PROJECT_DIR}/tools/claude/handoff_hook.py\"", "timeout": 20}
]}]}}
```

## 禁止する操作（`permissions.deny`）

- 評価の順は、deny、ask、allow。deny は、どの権限のモードでも、サブエージェントにも効く。
- `Bash(git push --force*)` は、頭からの一致。途中の `*` も使える。`Bash(git * push --force*)` は、`git -C dir push --force` に当たる。
- `Bash(git push *)` は、`git -C . push …` には当たらない。両方の形を書く。
- `&&`、`;`、`|` でつないだ命令は、分けて判定される。`timeout` や `nohup` の包みは、はがされる。
- `/usr/bin/git` や `sh -c 'git …'` には当たらない。完全な壁ではない。
- Edit の決まりは、Write にも効く。`Edit(/docs/canon/**)` は、プロジェクトの直下の `docs/canon/` に当たる。
- `--force*` は、`--force-with-lease` にも当たる。
- 見本：

```json
{"permissions": {"deny": [
  "Bash(git push --force*)", "Bash(git push -f *)", "Bash(git * push --force*)", "Bash(git * push -f *)",
  "Bash(git reset --hard*)", "Bash(git * reset --hard*)",
  "Bash(git clean *)", "Bash(git * clean *)"
]}}
```

## このプロジェクトでの扱い（区切り4で決めること）

- 正本（`docs/canon/`）への Edit は、禁止する操作に入れない。採られた改訂案を当てるコミットで書き換えるため。見張りは、正本の要約値の写しで行う。
- 作業の控えの差し込みは、新しいコンテナでは数行の案内だけ、圧縮と再開の後は全文を出す（計画の「文書とClaude Codeの構成」）。
- 禁止する操作の規則は、`git push …`、`git reset …`、`git clean …` で始まる形と、`git -C <dir> …` で始まる形だけにした。`git * clean *` のように頭に `*` を置く形は、やめた。規則は命令の文字列の全体に当たるので、コミットの文やブランチの名に同じ語があるだけで断られるため（例：`git commit -m "… git clean …"`、`git checkout -b clean`）。
- 抜ける形が残っている。`git push -fu origin dev`（旗をつないだ形）、`git -c x=y push --force`（小文字の -c）、`env X=1 git …`、`/usr/bin/git …`、`sh -c "git …"`。globでは、正当な命令を断らずには書けない。完全な壁ではないので、根のCLAUDE.mdの「gitの決まり」を守ることが先。
- 作業ツリーを捨てる形（`git checkout -- .`、`git restore .`、`git stash drop`）は、禁止する操作に入れない。ふだん使う `git checkout <ブランチ>` や `git restore --staged` と、規則で書き分けられないため。使わない、という決まりは、根のCLAUDE.mdに書く。
- SessionStart の matcher は、公式の見本に `"startup|resume"` の形がある。いまは matcher を省き、スクリプトの中で種類を見ている。

## 置いた後に見たこと（2026-11-11、設計から続けているセッション）

- `.claude/settings.json` に禁止する操作を置いた後、消す対象を表示するだけの `git clean -n` を回したところ、断られずに動いた（複合の形でも、単独の形でも）。このセッションは、リポジトリが無い状態で始まり、後からリポジトリを足したので、プロジェクトの設定が読まれていないと見ている（確かめてはいない）。
- 新しいセッションで、次を確かめる。セッションは、リポジトリを1つだけ選び、ブランチ `dev` で始めていただく（後からリポジトリを足したセッションと、プロジェクトのスレッドでは、設定もフックも型も読まれない）。

| # | 確かめること | 落ちたときの動き |
| --- | --- | --- |
| 1 | 開始時に、作業の控えの案内（`[clipping-point] 作業の控えの案内`）が文脈に入っている | `echo '{"source":"startup"}' \| python3 tools/claude/handoff_hook.py` を手で回して、控えを読む。フックの書式を、公式の文書で見直す |
| 2 | `git clean -n`（表示するだけ）が断られる。`git -C . clean -n` も断られる | 断られなければ、設定が読まれていない。禁止する操作は、根のCLAUDE.mdの決まりだけで守り、作業記録に書いて、人に知らせる |
| 3 | ふだんの命令が断られない：`git status`、`git push -u origin dev`、`git commit -F <ファイル>` | 断られた規則を、`.claude/settings.json` から外すか狭める |
| 4 | サブエージェントの型（implementer、reviewer、reader）が使える | 使えなければ、型を付けずに、頼みの文に型の本文の約束を書いて頼む |
| 5 | `tools/claude/step_review.js` を、`agentType` を付けて、1つの観点だけで回せる | 回せなければ、`agentType` を省いて回す |
| 6 | 環境のセットアップが走っている（Pyxel、pytest、`.cache/pyxel_web/` がある）。`python3 tools/verify.py --all` が通る | `bash tools/setup_env.sh` を手で回す。環境のセットアップスクリプトを見直す（人の承認が要る） |
| 7 | ブランチが `dev` である | `dev` に切り替える。別のブランチに新しいコミットがあれば、人に知らせる |

- 結果は、作業記録の区切り4の節に書き、初日のチェックリストの通過条件の4つ目に印を付ける。

## 新しいセッションで見たこと（2026-11-11 12:49 UTCから）

- 上の7点のうち、5番を除く6点が通った。5番（型を付けたレビュー）は、始められた所まで見た。回り切ったかどうかは、作業記録の「区切り5」の節に書く。結果の表は、作業記録（`docs/worklog.md`）の「区切り4」の節にある。
- 禁止する操作は、リポジトリを1つだけ選んで始めたセッションで効いた（`git clean -n` と `git -C . clean -n` が断られた）。設計から続けたセッションで効かなかったのは、後からリポジトリを足したため、という見立てと合う。
- サブエージェントの型は、3つとも型の一覧に出た。読み手の最初の要求は、約6,600トークンだった（根のCLAUDE.mdを読み込まない型）。

見えなかったこと：圧縮や再開の後に、控えの全文が差し込まれること。抜ける形（`git push -fu origin dev` など）が実際に通ってしまうかどうかは、試していない（試すと、戻せない操作になりうるため）。
