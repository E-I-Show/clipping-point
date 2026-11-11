# Claude Codeの設定の書式（調べ）

> 要約：段0の区切り4（Claude Codeの整え）で置く、サブエージェントの型、規則ファイル、フック、禁止する操作の書式を、公式の文書で調べたもの（2026-11-11。Claude Code 2.1.322）。実際のセッションではまだ試していない。置く前に、小さく試す。

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
- 置いた後に、禁止する操作が、ふだんの命令を誤って断らないことを、このセッションの過去の命令で確かめる。

見えなかったこと：実際のセッションでは、規則ファイルの読み込みのほかは試していない。サブエージェントの型の、最初の要求の重さも測っていない。
