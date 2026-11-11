import json, sys
SP='<scratchpad>'
k=sys.argv[1]
r=json.load(open(f'{SP}/spikes/{k}/RESULT.json',encoding='utf-8'))
print('## SUMMARY'); print(r['summary'])
print('## CONFIRMED')
for c in r['confirmed']: print('-', c['claim'], '\n    [根拠]', c['evidence'])
print('## RECOMMENDATIONS')
for c in r['recommendations']: print('-', c)
print('## NUMBERS')
for c in r['numbers']: print('-', c['what'], '=', c['value'], '|', c.get('conditions',''))
print('## UNVERIFIED')
for c in r['unverified']: print('-', c)
print('## ARTIFACTS')
for c in r.get('artifacts',[]): print('-', c)
