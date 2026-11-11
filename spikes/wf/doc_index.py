import sys, json, re
src=sys.argv[1]
raw=open(src,encoding='utf-8').read()
try:
    arr=json.loads(raw)
    txt=''.join(x.get('text','') for x in arr) if isinstance(arr,list) else raw
except Exception:
    txt=raw
try:
    j=json.loads(txt[:txt.rfind('}')+1]) if txt.lstrip().startswith('{') else None
except Exception:
    j=None
xml = (j or {}).get('data',{}).get('xml') if j else None
if xml is None:
    m=re.search(r'"xml":"(.*?)","complete"', txt, re.S)
    xml=json.loads('"'+m.group(1)+'"') if m else txt
rev=re.search(r"<doc node='[^']*' rev='(\d+)'", xml)
print('rev', rev.group(1) if rev else '?', 'len', len(xml))
open(sys.argv[2],'w',encoding='utf-8').write(xml)
# top-level blocks: headings, tables, lists with ids and hashes, plus first text
pos=0
depth=0
for m in re.finditer(r"<(paragraph|table|list|embed|codeBlock)\b([^>]*)>", xml):
    tag, attrs = m.group(1), m.group(2)
    # only top-level: check not inside table/list by scanning a cheap stack
    pre=xml[:m.start()]
    if pre.count('<table')-pre.count('</table>')>0 or pre.count('<list ')-pre.count('</list>')>0: continue
    i=re.search(r"id='([^']*)'", attrs); h=re.search(r"h='([^']*)'", attrs); hd=re.search(r"heading='(\d)'", attrs)
    seg=xml[m.end():m.end()+400]
    t=re.sub(r'<[^>]+>','',seg)[:46]
    if tag=='paragraph' and not hd and '--all' not in sys.argv: 
        continue
    print(tag, i.group(1) if i else '', h.group(1) if h else '', ('H'+hd.group(1)) if hd else '', '|', t.replace('\n',' '))
