"""Offline AST viewer for HW2/HW3 JSON; Python 3.10+, standard library only."""
import argparse
import html
import json
from pathlib import Path
import sys
import webbrowser

PAGE = r"""<!doctype html>
<html lang="ru"><meta charset="utf-8">
<title>Funny — просмотр AST</title>
<style>
body{font:15px system-ui;margin:0;background:#f5f7fb;color:#182339}
header{position:sticky;top:0;background:white;padding:18px 24px;border-bottom:1px solid #ccd5e0;z-index:1}
h1{font-size:22px;margin:0 0 12px}button,input{padding:8px;margin:3px;border:1px solid #b8c4d5;border-radius:5px}
main{padding:20px 28px}details{margin:5px 0 5px 18px;border-left:1px solid #ccd5e0;padding-left:12px}
summary{cursor:pointer;padding:5px;border-radius:5px}summary:hover{background:#e6edf7}
.kind{font-weight:650}.type{color:#075c44;background:#d9f4e8;padding:2px 7px;border-radius:5px;margin-left:8px}
.pos{color:#68758b;margin-left:8px}.field{color:#725022;margin-right:8px}.leaf{margin:5px 0 5px 35px;font-family:monospace;white-space:pre-wrap;overflow-wrap:anywhere}
.hit{background:#fff0a5!important}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:white;padding:15px;border-radius:8px}
#status{color:#53637c}#errors{color:#922222}#raw{display:none}
</style>
<header><h1>Funny — дерево AST</h1>
<button id="expand">Раскрыть всё</button><button id="collapse">Свернуть всё</button>
<button id="toggle">JSON / дерево</button><input id="search" placeholder="Поиск: Ident, int, имя…" aria-label="Поиск по дереву">
<div id="status"></div></header>
<main><section id="errors"></section><section id="tree"></section><pre id="raw"></pre></main>
<script id="payload" type="application/json">__DATA__</script>
<script>
const data=JSON.parse(document.getElementById('payload').textContent);
const wrapped=data&&typeof data==='object'&&Object.hasOwn(data,'ast');
const ast=wrapped?data.ast:data, diagnostics=wrapped?(data.diagnostics||[]):[];
const tree=document.getElementById('tree'); let count=0;
function text(tag,value,cls){const el=document.createElement(tag);el.textContent=value;if(cls)el.className=cls;return el;}
function draw(value,key,parent,depth){
 if(value!==null&&typeof value==='object'){
   const d=document.createElement('details');d.open=depth<3;
   const s=document.createElement('summary');
   if(key!==null)s.append(text('span',key+':','field'));
   const kind=Array.isArray(value)?'['+value.length+']':(value.node||value.kind||'object');
   s.append(text('span',kind,'kind'));
   if(value.node||value.kind)count++;
   for(const field of ['name','op','value'])if(Object.hasOwn(value,field)&&typeof value[field]!=='object')s.append(text('span',' '+JSON.stringify(value[field])));
   if(value.type!=null)s.append(text('span',String(value.type),'type'));
   if(value.pos!=null)s.append(text('span','@'+String(value.pos),'pos'));
   d.append(s);parent.append(d);
   for(const [field,child] of Object.entries(value)){
     if(!Array.isArray(value)&&['node','kind','type','pos','name','op','value'].includes(field)&&
         (child===null||typeof child!=='object'))continue;
     draw(child,field,d,depth+1);
   }
 }else parent.append(text('div',(key===null?'':key+': ')+JSON.stringify(value),'leaf'));
}
if(ast===null||ast===undefined)tree.append(text('p','AST отсутствует: исправьте лексические или синтаксические ошибки.'));
else draw(ast,null,tree,0);
document.getElementById('status').textContent='Узлов: '+count+' · Диагностик: '+diagnostics.length+
 (wrapped&&data.ok===false?' · Программа содержит ошибки':'');
for(const e of diagnostics){document.getElementById('errors').append(text('pre',typeof e==='string'?e:
 (e.code||'error')+': '+(e.message||JSON.stringify(e))+' @'+(e.line||'?')+':'+(e.col||'?')));}
document.getElementById('raw').textContent=JSON.stringify(data,null,2);
document.getElementById('expand').onclick=()=>tree.querySelectorAll('details').forEach(d=>d.open=true);
document.getElementById('collapse').onclick=()=>tree.querySelectorAll('details').forEach(d=>d.open=false);
document.getElementById('toggle').onclick=()=>{const raw=document.getElementById('raw');const show=raw.style.display!=='block';raw.style.display=show?'block':'none';tree.style.display=show?'none':'block';};
document.getElementById('search').oninput=e=>{
 const q=e.target.value.trim().toLowerCase();
 tree.querySelectorAll('summary,.leaf').forEach(el=>{
  const hit=q!==''&&el.textContent.toLowerCase().includes(q);el.classList.toggle('hit',hit);
  if(hit){let p=el.parentElement;while(p&&p!==tree){if(p.tagName==='DETAILS')p.open=true;p=p.parentElement;}}
 });
};
</script></html>"""


def render(data):
    if not isinstance(data, dict):
        raise ValueError('Ожидается JSON-объект: AST или результат main.py --json')
    if 'ast' not in data and 'node' not in data and 'kind' not in data:
        raise ValueError('В JSON нет поля ast, node или kind')
    # Escaping '<' prevents closing the embedded script element from JSON text.
    payload = json.dumps(data, ensure_ascii=False).replace('<', chr(92) + 'u003c')
    return PAGE.replace('__DATA__', payload)


def main(argv=None):
    parser=argparse.ArgumentParser(description='Просмотр AST Funny в автономном HTML')
    parser.add_argument('json_file',help='JSON от HW3 main.py --json либо непосредственно AST HW2')
    parser.add_argument('-o','--output',default='ast.html',help='HTML-файл (по умолчанию ast.html)')
    parser.add_argument('--open',action='store_true',help='Открыть результат в браузере')
    args=parser.parse_args(argv)
    try:
        data=json.loads(Path(args.json_file).read_text(encoding='utf-8-sig'))
        page=render(data)
        output=Path(args.output)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(page,encoding='utf-8')
    except (OSError,ValueError) as exc:
        print(f'error: {exc}',file=sys.stderr)
        return 1
    print(f'Создан HTML: {output}')
    if args.open:
        webbrowser.open(output.resolve().as_uri())
    return 0


if __name__=='__main__':
    raise SystemExit(main())
