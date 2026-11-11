export const meta = {
  name: 'step-review',
  description: '区切りの成果を観点ごとにレビューし、指摘を反証役が確かめ直す',
  phases: [
    { title: 'レビュー', detail: '観点ごとのレビュー役が読んで指摘を出す' },
    { title: '反証', detail: '指摘を初めから誤りと見て確かめ直す' },
  ],
}

// 使い方は tools/claude/README.md。args の形：
//   { step, targets, basis, note, lenses: [{ key, title, prompt }], agentType }
// agentType は、サブエージェントの型の名（"reviewer"）。型が使えるセッションで渡す。省けば、既定のサブエージェントで回す。
const A = args || {}
const lenses = A.lenses || []
const TYPE = A.agentType ? { agentType: A.agentType } : {}

const FINDINGS = {
  type: 'object',
  properties: {
    scope: { type: 'string' },
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          severity: { type: 'string', enum: ['高', '中', '低'] },
          tag: { type: 'string', enum: ['確かめた', '推測'] },
          where: { type: 'string' },
          case: { type: 'string' },
          fix: { type: 'string' },
        },
        required: ['id', 'severity', 'tag', 'where', 'case', 'fix'],
      },
    },
    unevaluated: { type: 'array', items: { type: 'string' } },
  },
  required: ['scope', 'findings', 'unevaluated'],
}

const VERDICTS = {
  type: 'object',
  properties: {
    verdicts: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string' },
          verdict: { type: 'string', enum: ['通った', '退け'] },
          reason: { type: 'string' },
          checked: { type: 'string' },
        },
        required: ['id', 'verdict', 'reason', 'checked'],
      },
    },
    unevaluated: { type: 'array', items: { type: 'string' } },
  },
  required: ['verdicts', 'unevaluated'],
}

const rules = `共通の約束
- リポジトリは /home/user/clipping-point（ブランチ dev）。日本語で作業し、日本語で報告する。
- 読むだけ。ファイルを書き換えない。作らない。gitの状態を変えない。
- 検証の道具（tools/ の下の .py）もテストも回さない。主のエージェントの検証と、出力先を取り合うため。
- shellを使えるときも、使ってよいのは読むだけの命令だけ：grep、wc、ls、cat、head、tail、git log、git diff、git show、git status。
- out/、dist/、.cache/（生成物とランタイムの写し）は見ない。
- サブエージェントは呼ばない。
- 言葉は docs/glossary.md の意味で読む。`

function reviewPrompt(lens) {
  return `あなたは、レースゲーム「CLIPPING POINT」の開発の「レビュー役」です。与えられた観点で読み、指摘を返します。

${rules}

【区切り】${A.step}
【見るもの】
${A.targets}
【照らす決まりの出どころ】
${A.basis}
【観点】${lens.title}
${lens.prompt}
${A.note ? '【主のエージェントからの注】\n' + A.note : ''}

指摘の書き方
- 起きる場合を書く。誤りなら「この入力・この状態 → この結果」。食い違いや決まりの破れなら「破る行（ファイル名と行番号、その文）」と「決まりの文（ファイル名と行番号、その文）」。書けないものは指摘にしない。
- 札を付ける。確かめた＝両方の文を実際に読んで突き合わせた、またはコードを最後まで追った。推測＝どこかが追い切れていない（caseの中に、どこが追い切れていないかを書く）。
- 重さを付ける。高＝詰む、永遠に果たせない、データや履歴が壊れる、後の区切りが必ず誤る。中＝読み違えや手戻りを生む。低＝直したほうがよいが、害は小さい。
- 好みの言い回しや、要らない行は、低だけにする。数は絞る。同じ原因の指摘は1件にまとめる。
- id は「${lens.key}-1」から順に振る。
- fix には、どこをどう直すかを1〜2文で書く。

返すもの
- scope：見た範囲。何を何件、どこまで読んだか。読んで問題が無かった所も書く。
- findings：指摘。無ければ空の配列。
- unevaluated：見られなかった所と理由。無ければ空の配列。`
}

function refutePrompt(lens, rev) {
  const list = rev.findings.map(f => `■ ${f.id}（重さ ${f.severity}、札 ${f.tag}）
所：${f.where}
起きる場合：${f.case}
直し方の案：${f.fix}`).join('\n\n')
  return `あなたは、レースゲーム「CLIPPING POINT」の開発の「反証役」です。レビュー役の指摘を、初めから「誤り」と見て確かめ直します。迷えば退けます。

${rules}

【区切り】${A.step}
【見るもの】
${A.targets}
【照らす決まりの出どころ】
${A.basis}
${A.note ? '【主のエージェントからの注】\n' + A.note : ''}

【指摘】（観点：${lens.title}）
${list}

確かめ方
- 指摘が引く文を、実際のファイルで自分で読む。行番号や引用が違っていないかを見る。
- 退ける型：引用が実物と違う／1つの文書しか読んでいない／既に別の所で決めてある／決めた方針を知らない／起きない場面／好みの問題で害が無い。
- 指摘の言うとおりで、放っておくと読み違えや手戻りが起きるものだけを「通った」とする。
- 直し方の案が誤っている（直すと別の食い違いが生まれる）ときは、verdictは事実に基づいて付け、reasonにその旨を書く。

返すもの
- verdicts：指摘ごとに、id、verdict（通った／退け）、reason（1〜2文）、checked（確かめたファイルと行）。すべての指摘に1つずつ付ける。
- unevaluated：確かめられなかった指摘と理由。無ければ空の配列。`
}

const results = await pipeline(
  lenses,
  lens => agent(reviewPrompt(lens), { label: `review:${lens.key}`, phase: 'レビュー', schema: FINDINGS, ...TYPE }),
  (rev, lens) => {
    if (!rev) return { key: lens.key, review: null, refute: null }
    if (!rev.findings.length) return { key: lens.key, review: rev, refute: { verdicts: [], unevaluated: [] } }
    return agent(refutePrompt(lens, rev), { label: `refute:${lens.key}`, phase: '反証', schema: VERDICTS, ...TYPE })
      .then(v => ({ key: lens.key, review: rev, refute: v }))
  }
)

const out = results.map((r, i) => r || { key: lenses[i].key, review: null, refute: null })
const n = out.reduce((s, r) => s + (r.review ? r.review.findings.length : 0), 0)
const passed = out.reduce((s, r) => s + (r.refute ? r.refute.verdicts.filter(v => v.verdict === '通った').length : 0), 0)
const missing = out.filter(r => !r.review || !r.refute).map(r => r.key)
log(`指摘 ${n} 件、反証を通った ${passed} 件、未評価の観点 ${missing.length ? missing.join(',') : '無し'}`)
return { step: A.step, results: out, counts: { findings: n, passed, unevaluated_lenses: missing } }
