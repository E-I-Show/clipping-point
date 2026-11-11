import json, sys, os
SP='<scratchpad>'
D='<session>/subagents/workflows'
done=[]
for w in ['wf_7435c7e2-9bd','wf_a60b5423-2ec','wf_98910349-e55']:
    labels={}
    p=f'{D}/{w}/journal.jsonl'
    if not os.path.exists(p): continue
    for line in open(p,encoding='utf-8'):
        o=json.loads(line)
        if o.get('type')=='started': labels[o['agentId']]=o.get('label','').replace('spike:','')
        if o.get('type')=='result':
            k=labels.get(o['agentId'],'?'); r=o.get('result')
            if r:
                os.makedirs(f'{SP}/spikes/{k}',exist_ok=True)
                json.dump(r, open(f'{SP}/spikes/{k}/RESULT.json','w',encoding='utf-8'), ensure_ascii=False, indent=1)
                done.append((k, len(json.dumps(r,ensure_ascii=False))))
            else: done.append((k,'EMPTY'))
print('done:', done)
