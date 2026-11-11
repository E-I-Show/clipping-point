import json, sys
SP='<scratchpad>'
k=sys.argv[1]; mode=sys.argv[2] if len(sys.argv)>2 else 'all'
lim=int(sys.argv[3]) if len(sys.argv)>3 else 100000
r=json.load(open(f'{SP}/spikes/{k}/RESULT.json',encoding='utf-8'))
if mode in ('all','claims'):
    print('## CONFIRMED (claims only)')
    for i,c in enumerate(r['confirmed']): print(f'{i+1}.', c['claim'][:lim])
if mode in ('all','rec'):
    print('## RECOMMENDATIONS')
    for c in r['recommendations']: print('-', c[:lim])
    print('## NUMBERS')
    for c in r['numbers']: print('-', c['what'], '=', c['value'], '|', c.get('conditions','')[:160])
    print('## UNVERIFIED')
    for c in r['unverified']: print('-', c[:lim])
    print('## ARTIFACTS')
    for c in r.get('artifacts',[]): print('-', c.replace(SP,'$SP'))
if mode=='summary': print(r['summary'])
