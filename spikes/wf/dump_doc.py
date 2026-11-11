import sys, json, re, html
src, dst = sys.argv[1], sys.argv[2]
raw = open(src, encoding='utf-8').read()
try:
    j = json.loads(raw)
    xml = j.get('xml') or j.get('data', {}).get('xml') or raw
    meta = {k: v for k, v in j.items() if k != 'xml'}
except Exception:
    xml = raw; meta = {}
# block-ish tags to newline
x = xml
x = re.sub(r"<paragraph id='([^']*)'[^>]*heading='(\d)'[^>]*>", lambda m: "\n\n" + "#"*int(m.group(2)) + " [" + m.group(1) + "] ", x)
x = re.sub(r"<paragraph id='([^']*)'[^>]*>", lambda m: "\n[" + m.group(1) + "] ", x)
x = re.sub(r"<row[^>]*>", "\n| ", x)
x = re.sub(r"</cell>", " | ", x)
x = re.sub(r"<item[^>]*>", "\n- ", x)
x = re.sub(r"<(table|list|code|embed|pending)([^>]*)>", lambda m: "\n<" + m.group(1) + m.group(2)[:120] + ">", x)
x = re.sub(r"<[^>]+>", "", x) if False else re.sub(r"</?(text|cell|row|item|paragraph|doc|list|table|strong|em|link|mark)[^>]*>", "", x)
x = html.unescape(x)
open(dst, 'w', encoding='utf-8').write(json.dumps(meta, ensure_ascii=False)[:500] + "\n" + x)
print(len(x), x.count("\n"))
