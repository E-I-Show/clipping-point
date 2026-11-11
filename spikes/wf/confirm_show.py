import sys, json
BASE='/root/.claude/projects/-home-user/fd032c6f-4e26-5fb1-b09c-91f82e61fd90/subagents/workflows/'
SP='/tmp/claude-0/-home-user/fd032c6f-4e26-5fb1-b09c-91f82e61fd90/scratchpad'
allr={}
for run in sys.argv[1].split(','):
    lab={}; res={}
    try: lines=open(BASE+run+'/journal.jsonl',encoding='utf-8').read().splitlines()
    except Exception as e: print(run,'no journal'); continue
    for line in lines:
        try: j=json.loads(line)
        except Exception: continue
        if j.get('type')=='started': lab[j['agentId']]=j.get('label')
        if j.get('type')=='result': res[j['agentId']]=j.get('result')
    for a,l in lab.items():
        allr[l]=res.get(a)
json.dump(allr, open(SP+'/review/confirm1.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
only=sys.argv[2] if len(sys.argv)>2 else None
for l,r in allr.items():
    if only and only not in l: continue
    print('=====', l, 'done' if r else 'RUNNING')
    if not r: continue
    if 'items' in r:
        from collections import Counter
        print('  内訳:', dict(Counter(i['status'] for i in r['items'])))
        for i in r['items']:
            if i['status']!='解消':
                print(f"  [{i['id']}] {i['status']} @ {i['where']}\n     {i['note']}")
        print('  -- new_issues', len(r.get('new_issues',[])))
        for n in r.get('new_issues',[]):
            print(f"  * {n['where']}\n     場合: {n['case']}\n     直し: {n['fix']}")
    if 'issues' in r:
        for n in r['issues']:
            print(f"  [{n['id']}] {n['severity']} @ {n['where']}\n     場合: {n['case']}\n     直し: {n['fix']}")
    print('  unevaluated:', [u[:120] for u in r.get('unevaluated',[])][:6])
