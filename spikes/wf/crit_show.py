import sys, json, os, glob
SP='/tmp/claude-0/-home-user/fd032c6f-4e26-5fb1-b09c-91f82e61fd90/scratchpad'
BASE='/root/.claude/projects/-home-user/fd032c6f-4e26-5fb1-b09c-91f82e61fd90/subagents/workflows/'
runs=sys.argv[1].split(',')
only=sys.argv[2] if len(sys.argv)>2 else None
mode=sys.argv[3] if len(sys.argv)>3 else 'full'
allr={}
for run in runs:
    lab={}; res={}
    for line in open(BASE+run+'/journal.jsonl',encoding='utf-8'):
        try: j=json.loads(line)
        except Exception: continue
        if j.get('type')=='started': lab[j['agentId']]=j.get('label')
        if j.get('type')=='result': res[j['agentId']]=j.get('result')
    for a,l in lab.items():
        if a in res: allr[l]=res[a]
json.dump(allr, open(SP+'/review/round1.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
lenses=sorted({l.split(':')[1] for l in allr})
for lens in lenses:
    if only and lens!=only: continue
    rv=allr.get('review:'+lens); rf=allr.get('refute:'+lens)
    print('=====', lens, '| review:', 'ok' if rv else 'none', '| refute:', 'ok' if rf else 'pending')
    if not rv: continue
    if isinstance(rv,str):
        try: rv=json.loads(rv)
        except Exception: print(rv[:500]); continue
    vd={}
    if rf:
        if isinstance(rf,str):
            try: rf=json.loads(rf)
            except Exception: rf={}
        for v in rf.get('verdicts',[]): vd[v['id']]=v
    if mode!='brief': print('scope:', rv.get('scope','')[:300])
    for f in rv.get('findings',[]):
        v=vd.get(f['id'])
        print(f"\n[{f['id']}] {f['severity']}/{f['tag']} @ {f['where']}  => {'反証:'+v['verdict'] if v else '反証待ち'}")
        if mode=='brief':
            print('  ', f['case'][:160])
        else:
            print('  場合:', f['case'])
            print('  直し:', f['fix'])
            if v: print('  反証:', v['reason'], '| 確かめ:', v['checked'][:300])
    if mode!='brief': print('unevaluated:', rv.get('unevaluated'))
