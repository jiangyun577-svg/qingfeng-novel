#!/usr/bin/env python3
"""把 正文.md 按 `## 第N章 · 标题` 切章，生成静态阅读站。

用法：
    python3 tools/build_site.py                 # 输出到 site/，可直接发布到 GitHub Pages
    python3 tools/build_site.py --artifact      # 另外输出 site_artifact/，供 Artifact 预览用
    python3 tools/build_site.py --upto 20       # 只发布到第20章（不写就读 tools/publish_upto.txt）

tools/publish_upto.txt 里写一个数字 N，站点就只发布第1到第N章，后面写好但还不想公开的章节留在 正文.md 里不上线；
文件不存在或为空，就发布全部章节。

站点只包含章节正文，不含大纲/设定集/人物表等创作资料。
新章节只要按 `## 第N章 · 标题` 追加进 正文.md，重新构建就会自动出现。
章节页自带"编辑模式"（作者在页面上改字，修改只存在本机浏览器，点"提交修改"生成 GitHub Issue），
配套的反向同步工具见 tools/apply_page_edits.py。
只用标准库，没有外部依赖。
"""
import argparse
import hashlib
import html
import math
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / '正文.md'
UPTO_FILE = ROOT / 'tools' / 'publish_upto.txt'  # 只发布到第几章，见文件头说明

SITE_TITLE = '末世清风'
REPO = 'jiangyun577-svg/qingfeng-novel'  # "提交修改"生成的 Issue 发到这个仓库
READ_CPM = 450  # 每分钟阅读字数，用来估计阅读时长

HEAD_RE = re.compile(r'^## 第(\d+)章 · (.+?)\s*$')
SCENE_RE = re.compile(r'^[。.．…·•]{3,}$|^…+$')

NUMS = '零一二三四五六七八九'


def cn_num(n):
    if n < 10:
        return NUMS[n]
    if n < 20:
        return '十' + (NUMS[n - 10] if n > 10 else '')
    if n < 100:
        t, u = divmod(n, 10)
        return NUMS[t] + '十' + (NUMS[u] if u else '')
    return str(n)


# ───────────────────────── 解析 ─────────────────────────

def strip_tail_note(lines):
    """去掉章节末尾的 `---` 和 `> ...` 备注块（正文.md 里 1-11 章与后续新章之间的说明）。
    lines 是 (行号, 原文) 的列表。"""
    k = len(lines)
    while k and (not lines[k - 1][1].strip() or lines[k - 1][1].lstrip().startswith('>')):
        k -= 1
    if k and lines[k - 1][1].strip() == '---':
        k -= 1
    return lines[:k]


def para_hash(text):
    return hashlib.sha1(text.encode('utf-8')).hexdigest()[:8]


def para_ids(paras):
    """给一章里的每个 'p' 段落一个稳定编号：正文哈希前 8 位；同一章里完全相同的段落，第 2 个起加 ~序号。
    编辑模式和 tools/apply_page_edits.py 都用它来定位段落，行号变了也不影响。"""
    seen, out = {}, []
    for kind, t, _ln in paras:
        if kind != 'p':
            continue
        h = para_hash(t)
        k = seen.get(h, 0)
        seen[h] = k + 1
        out.append(h if k == 0 else '%s~%d' % (h, k))
    return out


def parse_chapters(text):
    chapters = []
    cur = None
    for ln, line in enumerate(text.split('\n'), 1):
        m = HEAD_RE.match(line)
        if m:
            cur = {'n': int(m.group(1)), 'title': m.group(2), 'lines': []}
            chapters.append(cur)
        elif cur is not None:
            cur['lines'].append((ln, line))
    for expected, ch in enumerate(chapters, 1):
        if ch['n'] != expected:
            sys.exit('章号不连续：第%d个章节标题写的是第%d章' % (expected, ch['n']))
        paras = []
        for ln, raw in strip_tail_note(ch['lines']):
            s = raw.strip()
            if not s:
                continue
            paras.append(('scene', '', ln) if SCENE_RE.match(s) else ('p', s, ln))
        # 章首章尾的场景分隔线不显示
        while paras and paras[0][0] == 'scene':
            paras.pop(0)
        while paras and paras[-1][0] == 'scene':
            paras.pop()
        ch['paras'] = paras
        ch['chars'] = sum(len(re.sub(r'\s', '', t)) for k, t, _ln in paras if k == 'p')
        ch['minutes'] = max(1, math.ceil(ch['chars'] / READ_CPM))
        del ch['lines']
    return chapters


def last_update():
    try:
        out = subprocess.run(['git', 'log', '-1', '--format=%cs', '--', '正文.md'],
                             cwd=ROOT, capture_output=True, text=True, timeout=20).stdout.strip()
        if re.match(r'^\d{4}-\d{2}-\d{2}$', out):
            return out
    except Exception:
        pass
    return date.today().isoformat()


# ───────────────────────── 样式与脚本 ─────────────────────────

CSS = r'''
/* 版式：左对齐的竖排书名 + 居中的阅读栏；紫色取自一阶进化的"紫气"，只用在进度、当前项和按钮上 */
:root{
  --bg:#EDF0EE; --surface:#F6F8F7; --ink:#1B2225; --ink-2:#434F51; --muted:#55625F;
  --rule:#CDD5D3; --rule-2:#AEB9B7; --accent:#5A3E9E; --accent-ink:#FFFFFF; --accent-soft:#E2DCF0;
  --sans:"PingFang SC","HarmonyOS Sans SC","Noto Sans CJK SC","Noto Sans SC","Source Han Sans SC","Microsoft YaHei","Hiragino Sans GB",sans-serif;
  --serif:"Noto Serif CJK SC","Noto Serif SC","Source Han Serif SC","Songti SC","STSong","SimSun",serif;
  --read-size:18px; --read-face:var(--sans);
  color-scheme:light;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --bg:#0F1417; --surface:#161C20; --ink:#D9E0DE; --ink-2:#B1BCBA; --muted:#8E9A9A;
    --rule:#263036; --rule-2:#3A464D; --accent:#B8A5F4; --accent-ink:#17102B; --accent-soft:#2A2340;
    color-scheme:dark;
  }
}
:root[data-theme="dark"]{
  --bg:#0F1417; --surface:#161C20; --ink:#D9E0DE; --ink-2:#B1BCBA; --muted:#8E9A9A;
  --rule:#263036; --rule-2:#3A464D; --accent:#B8A5F4; --accent-ink:#17102B; --accent-soft:#2A2340;
  color-scheme:dark;
}
:root[data-face="serif"]{ --read-face:var(--serif); }
*{ box-sizing:border-box; }
html{ -webkit-text-size-adjust:100%; }
body{
  margin:0; background:var(--bg); color:var(--ink); font-family:var(--sans);
  font-size:16px; line-height:1.7;
  padding-left:max(16px, env(safe-area-inset-left, 0px));
  padding-right:max(16px, env(safe-area-inset-right, 0px));
}
body::before{ content:""; position:fixed; inset:0 0 auto; height:env(safe-area-inset-top, 0px); background:var(--bg); z-index:30; }
[hidden]{ display:none !important; }
a{ color:inherit; }
:focus-visible{ outline:2px solid var(--accent); outline-offset:2px; border-radius:2px; }
.btn{
  font:inherit; font-size:.9rem; line-height:1.2; color:var(--ink); background:transparent;
  border:1px solid var(--rule-2); border-radius:6px; padding:.45rem .8rem; cursor:pointer; min-height:2.4rem;
}
.btn:hover{ border-color:var(--accent); }
.btn[aria-pressed="true"]{ background:var(--accent); border-color:var(--accent); color:var(--accent-ink); }
.wrap{ max-width:50rem; margin-inline:auto; }

/* 首页 */
.top{ display:flex; justify-content:space-between; align-items:baseline; padding-block:20px 0; color:var(--muted); font-size:.85rem; letter-spacing:.08em; }
.masthead{ display:flex; gap:clamp(20px,6vw,56px); align-items:flex-start; padding-block:clamp(28px,6vw,56px) clamp(32px,6vw,52px); }
.mark{
  margin:0; font-family:var(--serif); font-weight:700;
  font-size:clamp(3.2rem,13vw,6rem); line-height:1.12; color:var(--ink);
}
.mark span{ display:block; }
.intro{ min-width:0; align-self:flex-end; display:flex; flex-direction:column; gap:1.1rem; }
.stats{ margin:0; color:var(--muted); font-size:.9rem; font-variant-numeric:tabular-nums; }
.cta{
  align-self:flex-start; display:inline-block; text-decoration:none; background:var(--accent); color:var(--accent-ink);
  padding:.7rem 1.3rem; border-radius:6px; font-size:1rem; line-height:1.4;
}
.cta:hover{ filter:brightness(1.08); }
.cta small{ display:block; opacity:.82; font-size:.8rem; }
.toc-head{ display:flex; justify-content:space-between; align-items:baseline; border-bottom:1px solid var(--rule-2); padding-bottom:.6rem; margin:0; font-size:.85rem; color:var(--muted); letter-spacing:.08em; }
.toc{ list-style:none; margin:0; padding:0; }
.row{
  display:grid; grid-template-columns:5.2rem minmax(0,1fr) auto; gap:.8rem; align-items:baseline;
  padding:.95rem .3rem; text-decoration:none; border-bottom:1px solid var(--rule);
}
.row:hover{ background:var(--surface); }
.row .no{ color:var(--muted); font-size:.9rem; letter-spacing:.04em; }
.row .tt{ font-family:var(--serif); font-size:1.12rem; letter-spacing:.04em; overflow-wrap:anywhere; }
.row .ct{ color:var(--muted); font-size:.82rem; font-variant-numeric:tabular-nums; white-space:nowrap; }
.row[data-last] .no{ color:var(--accent); font-weight:600; }
.row[data-last] .tt::after{ content:"上次读到这里"; margin-left:.8rem; font-family:var(--sans); font-size:.75rem; letter-spacing:.02em; color:var(--accent); }
.row[data-seen] .tt{ color:var(--ink-2); }
.soon{ padding:.95rem .3rem; color:var(--muted); font-size:.9rem; border-bottom:1px solid var(--rule); }
.foot{ padding-block:28px 40px; color:var(--muted); font-size:.8rem; letter-spacing:.04em; display:flex; justify-content:space-between; gap:1rem; flex-wrap:wrap; }

/* 章节页 */
.bar{
  position:sticky; top:env(safe-area-inset-top, 0px); z-index:20; background:var(--bg);
  display:flex; align-items:center; gap:12px; padding-block:10px; border-bottom:1px solid var(--rule); margin-inline:calc(-1 * max(16px, env(safe-area-inset-left, 0px)));
  padding-left:max(16px, env(safe-area-inset-left, 0px), calc((100vw - 50rem) / 2)); padding-right:max(16px, env(safe-area-inset-right, 0px), calc((100vw - 50rem) / 2));
}
.bar .back{ text-decoration:none; color:var(--muted); font-size:.9rem; white-space:nowrap; }
.bar .back:hover{ color:var(--accent); }
.bar .cur{ flex:1; min-width:0; text-align:center; color:var(--muted); font-size:.85rem; letter-spacing:.04em; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.bar .aa{ position:relative; }
.progress{ position:fixed; top:env(safe-area-inset-top, 0px); left:0; right:0; height:2px; z-index:25; pointer-events:none; }
.progress i{ display:block; height:100%; width:0; background:var(--accent); }
.panel{
  position:absolute; right:0; top:calc(100% + 8px); width:min(17.5rem, 86vw); background:var(--surface);
  border:1px solid var(--rule-2); border-radius:8px; padding:14px; display:grid; gap:12px; text-align:left; z-index:40;
}
.panel .line{ display:flex; align-items:center; justify-content:space-between; gap:10px; font-size:.85rem; color:var(--muted); }
.panel .grp{ display:flex; gap:6px; }
.reader{ max-width:34em; margin-inline:auto; padding-block:clamp(28px,6vw,56px) 24px; }
.eyebrow{ margin:0 0 .5rem; color:var(--accent); font-size:.9rem; letter-spacing:.2em; }
.reader h1{ margin:0; font-family:var(--serif); font-weight:700; font-size:clamp(1.8rem,6vw,2.4rem); line-height:1.3; letter-spacing:.08em; text-wrap:balance; }
.meta{ margin:.9rem 0 0; color:var(--muted); font-size:.85rem; font-variant-numeric:tabular-nums; }
.text{ margin-top:clamp(24px,5vw,40px); font-family:var(--read-face); font-size:var(--read-size); line-height:1.95; }
.text p{ margin:0 0 .9em; text-indent:2em; text-align:justify; text-justify:inter-ideograph; overflow-wrap:break-word; line-break:strict; }
.scene{ border:0; height:6px; width:54px; margin:2.2em auto; background:radial-gradient(circle, var(--rule-2) 2.2px, transparent 2.8px) center/18px 6px repeat-x; }
.pager{ display:grid; grid-template-columns:1fr 1fr; gap:12px; max-width:34em; margin:16px auto 0; padding-bottom:12px; }
.pager > a, .pager > span{ display:block; min-width:0; padding:.9rem 1rem; border:1px solid var(--rule-2); border-radius:8px; text-decoration:none; }
.pager > a:hover{ border-color:var(--accent); background:var(--surface); }
.pager .l{ display:block; color:var(--muted); font-size:.78rem; letter-spacing:.06em; }
.pager .t{ display:block; font-family:var(--serif); font-size:1.02rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.pager .next{ text-align:right; }
.pager > span{ color:var(--muted); border-style:dashed; }
.pager > .gap{ visibility:hidden; border:0; }
@media (max-width:480px){
  .pager{ grid-template-columns:1fr; }
  .row{ grid-template-columns:4.4rem minmax(0,1fr) auto; gap:.5rem; }
  .row .ct{ font-size:.76rem; }
}
@media (prefers-reduced-motion:no-preference){
  .row, .btn, .cta{ transition:background-color .15s, border-color .15s, filter .15s; }
}

/* 编辑模式（作者用）：默认关闭，在 Aa 面板里开启；修改只存在本机，提交后由 Claude 同步进 正文.md */
.panel .hint{ margin:0; font-size:.76rem; line-height:1.5; color:var(--muted); }
.editing .text p{ cursor:text; }
.editing .text p:not(.x){ box-shadow:inset 2px 0 0 var(--rule); padding-left:.4em; }
.text p.edited{ background:var(--accent-soft); border-radius:3px; box-shadow:inset 2px 0 0 var(--accent); }
.ed{ margin:0 0 .9em; }
.ed textarea{ display:block; width:100%; min-height:6rem; font:inherit; font-size:max(16px, var(--read-size)); line-height:1.8; padding:.6rem .7rem; background:var(--surface); color:var(--ink); border:1px solid var(--accent); border-radius:6px; resize:vertical; }
.ed-act{ display:flex; gap:8px; margin-top:8px; flex-wrap:wrap; }
.text .ed-tip, .editing .text .ed-tip{ flex-basis:100%; margin:0; padding:0; text-indent:0; text-align:left; box-shadow:none; cursor:default; font-size:.76rem; line-height:1.5; color:var(--muted); }
.edbar{ position:fixed; left:0; right:0; bottom:0; z-index:35; background:var(--surface); border-top:1px solid var(--rule-2);
  padding:10px max(16px, env(safe-area-inset-right, 0px)) calc(10px + env(safe-area-inset-bottom, 0px)) max(16px, env(safe-area-inset-left, 0px));
  display:flex; gap:8px; align-items:center; flex-wrap:wrap; font-size:.85rem; color:var(--muted); }
.edbar .grow{ flex:1; min-width:9rem; }
.edbar .btn{ font-size:.85rem; padding:.4rem .7rem; min-height:2.2rem; }
.edbar .btn.go{ background:var(--accent); border-color:var(--accent); color:var(--accent-ink); }
.editing .pager{ margin-bottom:6rem; }
.edlg{ position:fixed; inset:0; z-index:50; background:rgba(0,0,0,.45); display:flex; align-items:center; justify-content:center; padding:16px; }
.edlg > div{ background:var(--surface); border:1px solid var(--rule-2); border-radius:10px; padding:16px; width:min(34rem,100%); display:grid; gap:10px; }
.edlg p{ margin:0; font-size:.85rem; color:var(--ink-2); }
.edlg textarea{ width:100%; height:12rem; font:inherit; font-size:14px; background:var(--bg); color:var(--ink); border:1px solid var(--rule-2); border-radius:6px; padding:8px; }
.edtoast{ position:fixed; left:50%; transform:translateX(-50%); bottom:calc(5.5rem + env(safe-area-inset-bottom, 0px)); z-index:60; max-width:min(30rem,92vw);
  background:var(--ink); color:var(--bg); padding:.6rem .9rem; border-radius:8px; font-size:.85rem; line-height:1.5; }
'''

# 在内容绘制前应用阅读偏好（主题 / 字体 / 字号），避免闪一下
PREF_JS = r'''
var QF=(function(){
  var K='qf:', SIZES=[15,16,17,18,20,22,24], DEF=3, de=document.documentElement;
  function get(k,d){try{var v=localStorage.getItem(K+k);return v?JSON.parse(v):d}catch(e){return d}}
  function set(k,v){try{localStorage.setItem(K+k,JSON.stringify(v))}catch(e){}}
  var prefs=get('prefs',{});
  function apply(){
    if(prefs.theme==='light'||prefs.theme==='dark')de.setAttribute('data-theme',prefs.theme);else de.removeAttribute('data-theme');
    if(prefs.face==='serif')de.setAttribute('data-face','serif');else de.removeAttribute('data-face');
    var i=typeof prefs.size==='number'?prefs.size:DEF; i=Math.max(0,Math.min(SIZES.length-1,i));
    de.style.setProperty('--read-size',SIZES[i]+'px');
  }
  apply();
  return {get:get,set:set,prefs:prefs,apply:apply,sizes:SIZES,def:DEF,save:function(){set('prefs',prefs)}};
})();
'''

INDEX_JS = r'''
(function(){
  var last=QF.get('last',null), seen=QF.get('read',[]);
  var rows=document.querySelectorAll('.row');
  for(var i=0;i<rows.length;i++){
    var n=+rows[i].getAttribute('data-n');
    if(seen.indexOf(n)>-1)rows[i].setAttribute('data-seen','');
    if(last&&last.n===n)rows[i].setAttribute('data-last','');
  }
  var cta=document.getElementById('cta');
  if(last&&cta){
    var row=document.querySelector('.row[data-n="'+last.n+'"]');
    if(row){
      cta.setAttribute('href',row.getAttribute('data-href')+(last.p>0.02?'#r':''));
      cta.innerHTML='继续阅读<small>'+row.getAttribute('data-label')+(last.p>0.02?'　已读 '+Math.round(last.p*100)+'%':'')+'</small>';
    }
  }
})();
'''

CHAPTER_JS = r'''
(function(){
  var ch=+document.body.getAttribute('data-ch'), total=+document.body.getAttribute('data-total');
  var de=document.documentElement, bar=document.querySelector('.progress i');
  function frac(){var h=de.scrollHeight-window.innerHeight;return h>0?Math.min(1,Math.max(0,window.pageYOffset/h)):1}
  var tick=false,saveT=null;
  function onScroll(){
    if(tick)return; tick=true;
    requestAnimationFrame(function(){
      tick=false; var f=frac(); bar.style.width=(f*100)+'%';
      clearTimeout(saveT); saveT=setTimeout(function(){
        QF.set('last',{n:ch,p:+f.toFixed(3)});
        if(f>0.9){var r=QF.get('read',[]); if(r.indexOf(ch)<0){r.push(ch);QF.set('read',r)}}
      },300);
    });
  }
  window.addEventListener('scroll',onScroll,{passive:true});
  window.addEventListener('resize',onScroll);
  if(location.hash==='#r'){
    var l=QF.get('last',null);
    if(l&&l.n===ch&&l.p>0.02){window.scrollTo(0,l.p*(de.scrollHeight-window.innerHeight))}
  } else { QF.set('last',{n:ch,p:0}); }
  onScroll();

  var btn=document.getElementById('aa'), panel=document.getElementById('panel');
  function sync(){
    var P=QF.prefs, i=typeof P.size==='number'?P.size:QF.def;
    document.getElementById('sz-').disabled=i<=0; document.getElementById('sz+').disabled=i>=QF.sizes.length-1;
    var f=P.face==='serif'?'serif':'sans', t=(P.theme==='light'||P.theme==='dark')?P.theme:'auto';
    ['sans','serif'].forEach(function(k){document.getElementById('f-'+k).setAttribute('aria-pressed',String(k===f))});
    ['auto','light','dark'].forEach(function(k){document.getElementById('t-'+k).setAttribute('aria-pressed',String(k===t))});
  }
  function setPref(k,v){QF.prefs[k]=v;QF.save();QF.apply();sync()}
  function size(d){var i=typeof QF.prefs.size==='number'?QF.prefs.size:QF.def;setPref('size',Math.max(0,Math.min(QF.sizes.length-1,i+d)))}
  btn.addEventListener('click',function(e){e.stopPropagation();var o=panel.hidden;panel.hidden=!o;btn.setAttribute('aria-expanded',String(o))});
  panel.addEventListener('click',function(e){e.stopPropagation()});
  document.addEventListener('click',function(){panel.hidden=true;btn.setAttribute('aria-expanded','false')});
  document.getElementById('sz-').addEventListener('click',function(){size(-1)});
  document.getElementById('sz+').addEventListener('click',function(){size(1)});
  document.getElementById('f-sans').addEventListener('click',function(){setPref('face','sans')});
  document.getElementById('f-serif').addEventListener('click',function(){setPref('face','serif')});
  document.getElementById('t-auto').addEventListener('click',function(){setPref('theme','auto')});
  document.getElementById('t-light').addEventListener('click',function(){setPref('theme','light')});
  document.getElementById('t-dark').addEventListener('click',function(){setPref('theme','dark')});
  document.addEventListener('keydown',function(e){
    if(e.key==='Escape'){panel.hidden=true;btn.setAttribute('aria-expanded','false');return}
    if(e.altKey||e.ctrlKey||e.metaKey||e.shiftKey||!panel.hidden)return;
    var a=e.key==='ArrowLeft'?document.querySelector('a[rel="prev"]'):e.key==='ArrowRight'?document.querySelector('a[rel="next"]'):null;
    if(a)a.click();
  });
  sync();
})();
'''

EDIT_JS = r'''
(function(){
  var REPO=document.body.getAttribute('data-repo'), ch=+document.body.getAttribute('data-ch');
  var text=document.querySelector('.text'), btn=document.getElementById('ed'), bar=document.getElementById('edbar');
  if(!text||!btn||!bar)return;
  var info=document.getElementById('edinfo'), ps=[].slice.call(text.querySelectorAll('p[data-h]'));
  var HEAD=12, BUDGET=7000, opened=null;
  ps.forEach(function(p){p._o=p.textContent});
  function load(){var d=QF.get('edits',{});return d&&typeof d==='object'&&!Array.isArray(d)?d:{}}
  function store(d){QF.set('edits',d)}
  function K(id){return ch+':'+id}
  function segs(v){return v.split(/\r?\n/).map(function(s){return s.trim()}).filter(Boolean)}
  function cps(s){return Array.from(s)}
  function diff(o,n){
    var a=cps(o),b=cps(n),m=Math.min(a.length,b.length),p=0,s=0;
    while(p<m&&a[p]===b[p])p++;
    while(s<m-p&&a[a.length-1-s]===b[b.length-1-s])s++;
    return [p,s,b.slice(p,b.length-s).join('')];
  }
  function toast(t,ms){
    var e=document.getElementById('edtoast');
    if(!e){e=document.createElement('div');e.id='edtoast';e.className='edtoast';e.setAttribute('role','status');document.body.appendChild(e)}
    e.textContent=t;e.hidden=false;clearTimeout(e._t);e._t=setTimeout(function(){e.hidden=true},ms||4500);
  }
  function pOf(el){
    var p=el.closest&&el.closest('p'); if(!p)return null;
    while(p&&!p.hasAttribute('data-h')){p=p.previousElementSibling}
    return p&&p.hasAttribute('data-h')?p:null;
  }
  function paint(){
    var d=load();
    [].slice.call(text.querySelectorAll('p.x')).forEach(function(e){e.parentNode.removeChild(e)});
    var live={};
    ps.forEach(function(p){
      var id=p.getAttribute('data-h'),r=d[K(id)];
      live[K(id)]=1; p.classList.remove('edited');
      if(!r){p.textContent=p._o;return}
      var a=r.n===''?[]:r.n.split('\n');
      p.classList.add('edited');
      if(!a.length){p.textContent=p._o;p.style.opacity='.45';p.style.textDecoration='line-through';return}
      p.style.opacity='';p.style.textDecoration='';
      p.textContent=a[0];
      var prev=p;
      for(var i=1;i<a.length;i++){
        var x=document.createElement('p');x.className='x edited';x.textContent=a[i];
        prev.parentNode.insertBefore(x,prev.nextSibling);prev=x;
      }
    });
    ps.forEach(function(p){if(!d[K(p.getAttribute('data-h'))]){p.style.opacity='';p.style.textDecoration=''}});
    status(d,live);
  }
  function status(d,live){
    var all=Object.keys(d),mine=0,orph=0;
    all.forEach(function(k){var r=d[k];if(r.ch===ch){mine++;if(!live[k])orph++}});
    var t=all.length?('共 '+all.length+' 处修改（本章 '+mine+' 处）'):'点任意一段开始修改';
    info.textContent=t;
    if(orph){
      var b=document.createElement('button');b.type='button';b.className='btn';b.textContent='清除 '+orph+' 条找不到原文的草稿';
      b.addEventListener('click',function(){var e=load();Object.keys(e).forEach(function(k){if(e[k].ch===ch&&!live[k])delete e[k]});store(e);paint()});
      info.appendChild(document.createTextNode('　'));info.appendChild(b);
    }
  }
  function closeEd(){
    if(!opened)return;
    var box=opened.box,p=opened.p;
    if(box.parentNode)box.parentNode.removeChild(box);
    p.hidden=false;
    var x=p.nextElementSibling;
    while(x&&x.classList.contains('x')){x.hidden=false;x=x.nextElementSibling}
    opened=null;paint();
  }
  function openEd(p){
    closeEd();
    var d=load(),id=p.getAttribute('data-h'),r=d[K(id)],cur=r?r.n:p._o;
    var box=document.createElement('div');box.className='ed';
    var ta=document.createElement('textarea');ta.value=cur;ta.lang='zh';ta.setAttribute('aria-label','编辑这一段');
    var act=document.createElement('div');act.className='ed-act';
    function mk(label,cls,fn){var b=document.createElement('button');b.type='button';b.className='btn '+cls;b.textContent=label;b.addEventListener('click',fn);act.appendChild(b);return b}
    mk('保存','go',save);
    mk('取消','',closeEd);
    mk('恢复原文','',function(){var e=load();delete e[K(id)];store(e);closeEd()});
    var tip=document.createElement('p');tip.className='ed-tip';tip.textContent='回车 = 另起一段；留空保存 = 删除这一段。Ctrl/⌘+回车保存，Esc 取消。';act.appendChild(tip);
    box.appendChild(ta);box.appendChild(act);
    p.hidden=true;var x=p.nextElementSibling;while(x&&x.classList.contains('x')){x.hidden=true;x=x.nextElementSibling}
    p.parentNode.insertBefore(box,p);
    opened={p:p,box:box};
    function fit(){ta.style.height='auto';ta.style.height=Math.max(96,ta.scrollHeight+4)+'px'}
    ta.addEventListener('input',fit);
    ta.addEventListener('keydown',function(e){
      if(e.key==='Escape'){e.stopPropagation();closeEd()}
      else if(e.key==='Enter'&&(e.ctrlKey||e.metaKey)){e.preventDefault();save()}
      else e.stopPropagation();
    });
    fit();ta.focus();ta.setSelectionRange(ta.value.length,ta.value.length);
    function save(){
      var a=segs(ta.value),n=a.join('\n'),e=load();
      if(n===p._o){delete e[K(id)];store(e);closeEd();return}
      if(!n&&!confirm('内容为空，要把这一段整段删除吗？（提交后会从正文里删掉）'))return;
      var df=n?diff(p._o,n):[0,0,null];
      e[K(id)]={ch:ch,i:+p.getAttribute('data-i'),id:id,head:cps(p._o).slice(0,HEAD).join(''),n:n,d:df};
      store(e);closeEd();
    }
  }
  function setEdit(on){
    QF.prefs.edit=!!on;QF.save();
    text.classList.toggle('editing',!!on);document.body.classList.toggle('editing',!!on);
    bar.hidden=!on;btn.setAttribute('aria-pressed',String(!!on));btn.textContent=on?'关闭':'开启';
    if(!on)closeEd();
  }
  btn.addEventListener('click',function(){setEdit(!QF.prefs.edit)});
  text.addEventListener('click',function(e){
    if(!QF.prefs.edit||e.target.closest('.ed'))return;
    var sel=window.getSelection&&window.getSelection().toString();if(sel)return;
    var p=pOf(e.target);if(p)openEd(p);
  });
  function list(){
    var d=load(),a=Object.keys(d).map(function(k){return d[k]});
    a.sort(function(x,y){return x.ch-y.ch||x.i-y.i});return a;
  }
  function mkBody(a,readable){
    var e=a.map(function(r){return [r.ch,r.i,r.id,r.d[0],r.d[1],r.d[2],r.head]});
    var lines=['<!-- qingfeng-page-edits v1 -->','【页面修改】共 '+a.length+' 处。下次开会话时由 Claude 同步进《正文.md》（tools/apply_page_edits.py）。',''];
    if(readable){
      a.forEach(function(r){
        var cut=function(s){s=cps(s);return s.length>14?s.slice(0,14).join('')+'…':s.join('')};
        var del=r.d[2]===null,mid=del?'':r.d[2].replace(/\n/g,'⏎');
        lines.push('- 第'+r.ch+'章第'+r.i+'段「'+r.head+'…」'+(del?'：删除整段':(r.d[0]+r.d[1]===0?'：整段改写':'：改动处 → 「'+cut(mid)+'」')));
      });
      lines.push('');
    }
    lines.push('```json',JSON.stringify({qf:1,e:e}),'```');
    return lines.join('\n');
  }
  function copyText(t){
    if(navigator.clipboard&&navigator.clipboard.writeText)return navigator.clipboard.writeText(t);
    return new Promise(function(res,rej){
      try{var ta=document.createElement('textarea');ta.value=t;ta.style.position='fixed';ta.style.opacity='0';document.body.appendChild(ta);ta.select();
        var ok=document.execCommand('copy');document.body.removeChild(ta);ok?res():rej()}catch(x){rej(x)}
    });
  }
  function dialog(t){
    var o=document.createElement('div');o.className='edlg';
    o.innerHTML='<div><p>没能自动复制。请手动全选下面的内容复制，然后贴给 Claude，或贴进 GitHub 的新 Issue。</p><textarea readonly></textarea><div class="ed-act"><button type="button" class="btn go">关闭</button></div></div>';
    o.querySelector('textarea').value=t;
    o.querySelector('button').addEventListener('click',function(){document.body.removeChild(o)});
    document.body.appendChild(o);var ta=o.querySelector('textarea');ta.focus();ta.select();
  }
  function today(){var d=new Date();return d.getFullYear()+'-'+('0'+(d.getMonth()+1)).slice(-2)+'-'+('0'+d.getDate()).slice(-2)}
  document.getElementById('ed-sub').addEventListener('click',function(){
    var a=list();if(!a.length){toast('还没有修改。点任意一段就能改。');return}
    var title='【页面修改】'+today()+' 共'+a.length+'处';
    var base='https://github.com/'+REPO+'/issues/new?title='+encodeURIComponent(title);
    var full=mkBody(a,true),mini=mkBody(a,false);
    var url=base+'&body='+encodeURIComponent(full);
    if(url.length>BUDGET)url=base+'&body='+encodeURIComponent(mini);
    if(url.length<=BUDGET){
      window.open(url,'_blank','noopener');
      toast('已打开 GitHub 的新 Issue 页：确认内容后点 Submit new issue 即提交。');
      return;
    }
    window.open(base,'_blank','noopener');
    copyText(mini).then(function(){toast('修改较多，超出链接长度：内容已复制，请粘贴到刚打开的 Issue 正文框再提交。',9000)},function(){dialog(mini)});
  });
  document.getElementById('ed-copy').addEventListener('click',function(){
    var a=list();if(!a.length){toast('还没有修改。');return}
    var t=mkBody(a,true);
    copyText(t).then(function(){toast('已复制 '+a.length+' 处修改，贴给 Claude 即可。')},function(){dialog(t)});
  });
  document.getElementById('ed-clr').addEventListener('click',function(){
    var d=load();if(!Object.keys(d).length){toast('没有草稿。');return}
    if(confirm('清除本机所有未同步的修改草稿？（已经提交并同步进正文之后再清除）')){store({});closeEd();paint()}
  });
  paint();setEdit(!!QF.prefs.edit);
})();
'''

FAVICON = ("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
           "%3Crect width='32' height='32' rx='6' fill='%235A3E9E'/%3E"
           "%3Cpath d='M6 12h13a3 3 0 1 0-3-3M5 17h19a3 3 0 1 1-3 3M8 23h9' fill='none' stroke='%23fff' "
           "stroke-width='2' stroke-linecap='round'/%3E%3C/svg%3E")


# ───────────────────────── 页面模板 ─────────────────────────

def esc(s):
    return html.escape(s, quote=True)


def doc(title, desc, head_extra, body, body_attrs='', fragment=False):
    """fragment=True 时输出不含 doctype/html/head/body 的片段（Artifact 首页会被平台套上外壳）。"""
    meta = (
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
        '<meta name="robots" content="noindex, nofollow">\n'
        '<meta name="description" content="%s">\n'
        '<meta property="og:title" content="%s">\n<meta property="og:description" content="%s">\n'
        '<meta name="theme-color" content="#0F1417" media="(prefers-color-scheme: dark)">\n'
        '<meta name="theme-color" content="#EDF0EE" media="(prefers-color-scheme: light)">\n'
        '<link rel="icon" href="%s">\n' % (esc(desc), esc(title), esc(desc), FAVICON)
    )
    if fragment:
        return ('<title>%s</title>\n<meta name="claude:viewport-fit-sides" content="cover">\n'
                '<meta name="robots" content="noindex, nofollow">\n<style>%s</style>\n'
                '<script>%s</script>\n%s\n' % (esc(title), CSS, PREF_JS, body))
    return ('<!doctype html>\n<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n<title>%s</title>\n%s'
            '<style>%s</style>\n<script>%s</script>\n%s</head>\n<body%s>\n%s\n</body>\n</html>\n'
            % (esc(title), meta, CSS, PREF_JS, head_extra, (' ' + body_attrs) if body_attrs else '', body))


def chapter_href(n, from_chapter_dir):
    name = 'chapters/%02d.html' % n
    return ('../' + name[len('chapters/'):]) if from_chapter_dir else name


def render_index(chapters, total_chars, updated, fragment=False):
    wan = round(total_chars / 10000, 1)
    first = chapters[0]
    rows = []
    for c in chapters:
        label = '第%s章　%s' % (cn_num(c['n']), c['title'])
        href = chapter_href(c['n'], False)
        rows.append(
            '<li><a class="row" href="%s" data-n="%d" data-href="%s" data-label="%s">'
            '<span class="no">第%s章</span><span class="tt">%s</span><span class="ct">%s 字</span></a></li>'
            % (href, c['n'], href, esc(label), cn_num(c['n']), esc(c['title']), format(c['chars'], ','))
        )
    body = '''<div class="wrap">
<div class="top"><span>连载中</span><span>最近更新 %(updated)s</span></div>
<header class="masthead">
<h1 class="mark" aria-label="%(site)s">%(chars)s</h1>
<div class="intro">
<p class="stats">已更 %(count)d 章 · 约 %(wan)s 万字</p>
<a class="cta" id="cta" href="%(first)s">从第一章读起<small>第%(fn)s章　%(ft)s</small></a>
</div>
</header>
<main>
<p class="toc-head"><span>目录</span><span>共 %(count)d 章</span></p>
<ol class="toc">
%(rows)s
</ol>
<div class="soon">后续章节更新中</div>
</main>
<footer class="foot"><span>《%(site)s》</span><span>在浏览器里记住你的字号、主题和读到的位置</span></footer>
</div>
<script>%(js)s</script>''' % {
        'site': esc(SITE_TITLE), 'chars': ''.join('<span aria-hidden="true">%s</span>' % esc(c) for c in SITE_TITLE), 'count': len(chapters), 'wan': wan,
        'updated': esc(updated), 'first': chapter_href(first['n'], False), 'fn': cn_num(first['n']),
        'ft': esc(first['title']), 'rows': '\n'.join(rows), 'js': INDEX_JS}
    return doc(SITE_TITLE, '《%s》连载在线阅读，已更 %d 章。' % (SITE_TITLE, len(chapters)), '', body, fragment=fragment)


def render_chapter(ch, prev, nxt, total, home_href):
    n = ch['n']
    parts = []
    ids = iter(para_ids(ch['paras']))
    idx = 0
    for kind, t, _ln in ch['paras']:
        if kind == 'scene':
            parts.append('<hr class="scene">')
        else:
            idx += 1
            parts.append('<p data-i="%d" data-h="%s">%s</p>' % (idx, next(ids), esc(t)))
    if prev:
        pl = '<a class="prev" rel="prev" href="%s"><span class="l">← 上一章</span><span class="t">第%s章　%s</span></a>' % (
            '%02d.html' % prev['n'], cn_num(prev['n']), esc(prev['title']))
    else:
        pl = '<span class="gap"></span>'
    if nxt:
        pr = '<a class="next" rel="next" href="%s"><span class="l">下一章 →</span><span class="t">第%s章　%s</span></a>' % (
            '%02d.html' % nxt['n'], cn_num(nxt['n']), esc(nxt['title']))
    else:
        pr = '<span class="next"><span class="l">已是最新</span><span class="t">后续章节更新中</span></span>'
    body = '''<div class="progress" aria-hidden="true"><i></i></div>
<header class="bar">
<a class="back" href="%(home)s">← 目录</a>
<span class="cur">第%(cn)s章　%(title)s</span>
<span class="aa">
<button class="btn" id="aa" type="button" aria-expanded="false" aria-controls="panel" aria-label="阅读设置">Aa</button>
<div class="panel" id="panel" hidden>
<div class="line"><span>字号</span><span class="grp"><button class="btn" id="sz-" type="button" aria-label="减小字号">A−</button><button class="btn" id="sz+" type="button" aria-label="增大字号">A+</button></span></div>
<div class="line"><span>字体</span><span class="grp"><button class="btn" id="f-sans" type="button" aria-pressed="true">黑体</button><button class="btn" id="f-serif" type="button" aria-pressed="false">宋体</button></span></div>
<div class="line"><span>主题</span><span class="grp"><button class="btn" id="t-auto" type="button" aria-pressed="true">自动</button><button class="btn" id="t-light" type="button" aria-pressed="false">日间</button><button class="btn" id="t-dark" type="button" aria-pressed="false">夜间</button></span></div>
<div class="line"><span>编辑（作者用）</span><span class="grp"><button class="btn" id="ed" type="button" aria-pressed="false">开启</button></span></div>
<p class="hint">开启后点任意一段就能改字。修改只保存在这台设备的浏览器里，点“提交修改”才会发给作者。</p>
</div>
</span>
</header>
<main class="reader">
<p class="eyebrow">第%(cn)s章</p>
<h1>%(title)s</h1>
<p class="meta">%(chars)s 字 · 约 %(min)d 分钟</p>
<article class="text">
%(text)s
</article>
</main>
<nav class="pager" aria-label="章节导航">%(pl)s%(pr)s</nav>
<footer class="foot wrap"><span>《%(site)s》</span><a href="%(home)s">回到目录</a></footer>
<div class="edbar" id="edbar" hidden>
<span class="grow" id="edinfo">点任意一段开始修改</span>
<button class="btn go" id="ed-sub" type="button">提交修改</button>
<button class="btn" id="ed-copy" type="button">复制</button>
<button class="btn" id="ed-clr" type="button" title="清除本机所有未同步的修改草稿">清除</button>
</div>
<script>%(js)s</script>''' % {
        'home': home_href, 'cn': cn_num(n), 'title': esc(ch['title']), 'chars': format(ch['chars'], ','),
        'min': ch['minutes'], 'text': '\n'.join(parts), 'pl': pl, 'pr': pr, 'site': esc(SITE_TITLE), 'js': CHAPTER_JS + EDIT_JS}
    t = '第%s章 %s · %s' % (cn_num(n), ch['title'], SITE_TITLE)
    return doc(t, '《%s》第%s章 %s' % (SITE_TITLE, cn_num(n), ch['title']), '', body,
               body_attrs='data-ch="%d" data-total="%d" data-repo="%s"' % (n, total, esc(REPO)))


# ───────────────────────── 输出 ─────────────────────────

def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def publish_upto():
    """读 tools/publish_upto.txt 里的章号；没有这个文件或内容为空就返回 None（全部发布）。"""
    if not UPTO_FILE.exists():
        return None
    s = UPTO_FILE.read_text(encoding='utf-8').strip()
    if not s:
        return None
    if not s.isdigit():
        sys.exit('tools/publish_upto.txt 里只能写一个章号数字，现在是：%r' % s)
    return int(s)


def build(out, fragment_index=False, home_for_chapters='../index.html', upto=None):
    chapters = parse_chapters(SRC.read_text(encoding='utf-8'))
    if not chapters:
        sys.exit('正文.md 里没有找到 `## 第N章 · 标题`')
    if upto is not None:
        held = [c for c in chapters if c['n'] > upto]
        chapters = [c for c in chapters if c['n'] <= upto]
        if held:
            print('暂不发布：' + '、'.join('第%d章' % c['n'] for c in held))
    total_chars = sum(c['chars'] for c in chapters)
    updated = last_update()
    out.mkdir(parents=True, exist_ok=True)
    write(out / 'index.html', render_index(chapters, total_chars, updated, fragment=fragment_index))
    for i, c in enumerate(chapters):
        prev = chapters[i - 1] if i else None
        nxt = chapters[i + 1] if i + 1 < len(chapters) else None
        write(out / 'chapters' / ('%02d.html' % c['n']), render_chapter(c, prev, nxt, len(chapters), home_for_chapters))
    write(out / 'robots.txt', 'User-agent: *\nDisallow: /\n')
    write(out / '.nojekyll', '')
    print('%s：%d 章，共 %d 字' % (out.relative_to(ROOT) if out.is_relative_to(ROOT) else out, len(chapters), total_chars))
    for c in chapters:
        print('  第%2d章 %-6s %5d 字' % (c['n'], c['title'], c['chars']))


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=str(ROOT / 'site'))
    ap.add_argument('--artifact', action='store_true', help='另外生成 site_artifact/（首页为片段，章节页回目录用 ARTIFACT_HOME）')
    ap.add_argument('--artifact-home', default='../index.html', help='Artifact 预览里章节页"回目录"的链接')
    ap.add_argument('--upto', type=int, default=None, help='只发布到第几章；不写就读 tools/publish_upto.txt')
    a = ap.parse_args()
    upto = a.upto if a.upto is not None else publish_upto()
    build(Path(a.out), upto=upto)
    if a.artifact:
        build(ROOT / 'site_artifact', fragment_index=True, home_for_chapters=a.artifact_home, upto=upto)
