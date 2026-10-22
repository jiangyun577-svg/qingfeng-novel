#!/usr/bin/env python3
"""把阅读站"编辑模式 → 提交修改"产生的内容，反向同步回 正文.md。

修改内容来自 GitHub Issue 正文（标题以【页面修改】开头）或作者复制给 Claude 的文本；里面有一段
```json {"qf":1,"e":[[章, 段序, 段落编号, 前缀长, 后缀长, 替换的中间部分, 原文开头], ...]} ```。

用法：
    python3 tools/apply_page_edits.py issue1.txt [issue2.txt ...]          # 只预览，不改文件
    python3 tools/apply_page_edits.py issue1.txt --write                   # 写入 正文.md
    python3 tools/apply_page_edits.py - < issue_body.txt                   # 从标准输入读
    python3 tools/apply_page_edits.py x.txt --src /path/to/正文.md          # 指定别的正文文件（测试用）

规则（保守）：
- 段落用 build_site.para_ids 的编号精确定位（正文哈希，行号变了也能找到）；找不到的一律不改，只报告。
- "新文字" = 原段落[:前缀长] + 中间部分 + 原段落[len-后缀长:]，用的是 Unicode 码点位置；中间部分里的换行 = 另起一段。
- 中间部分为 null 表示删除整段。
- 拒绝会破坏正文结构的内容：以 # 或 > 开头的段、单独的 ---、场景分隔线。
- 同一段在一次运行里被改两次，且结果不同，则整体报错，不写入。
只用标准库。写入后请：重新构建站点、核对段落，并按 WORKFLOW 的"④ 同步页面修改"流程检查 canon、追加变更记录。
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_site as bs  # noqa: E402


def extract(text):
    """从一段文本里取出所有 {"qf":1,...} JSON 对象。"""
    dec = json.JSONDecoder()
    out, i = [], 0
    while True:
        j = text.find('{"qf":', i)
        if j < 0:
            return out
        try:
            obj, k = dec.raw_decode(text, j)
        except ValueError:
            i = j + 1
            continue
        if isinstance(obj, dict) and obj.get('qf') == 1 and isinstance(obj.get('e'), list):
            out.append(obj)
        i = k


def bad_segment(s):
    t = s.strip()
    return (not t or t.startswith('#') or t.startswith('>') or t == '---' or bool(bs.SCENE_RE.match(t))
            or any(ord(c) < 32 for c in t))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('files', nargs='+', help='含修改 JSON 的文本文件；- 表示标准输入')
    ap.add_argument('--write', action='store_true', help='真正写入 正文.md（默认只预览）')
    ap.add_argument('--src', default=str(bs.SRC), help='正文文件路径（默认仓库里的 正文.md）')
    a = ap.parse_args()

    payloads = []
    for f in a.files:
        txt = sys.stdin.read() if f == '-' else Path(f).read_text(encoding='utf-8')
        found = extract(txt)
        if not found:
            print('！%s：没找到 {"qf":1,...} 修改内容' % f)
        payloads += found
    entries = [e for p in payloads for e in p['e']]
    if not entries:
        sys.exit('没有可处理的修改。')

    src = Path(a.src)
    text = src.read_text(encoding='utf-8')
    lines = text.split('\n')
    chapters = {c['n']: c for c in bs.parse_chapters(text)}
    index = {}   # (章, 编号) -> (行号, 原文)
    for n, c in chapters.items():
        ps = [p for p in c['paras'] if p[0] == 'p']
        for pid, (_k, t, ln) in zip(bs.para_ids(c['paras']), ps):
            index[(n, pid)] = (ln, t)

    plan, problems, seen = {}, [], {}
    for e in entries:
        try:
            ch, i, pid, pre, suf, mid, head = e
            assert isinstance(ch, int) and isinstance(pid, str) and isinstance(pre, int) and isinstance(suf, int)
            assert mid is None or isinstance(mid, str)
        except Exception:
            problems.append('格式不对，跳过：%r' % (e,))
            continue
        label = '第%d章第%s段「%s…」' % (ch, i, head)
        hit = index.get((ch, pid))
        if not hit:
            near = [(n2, ln2) for (n2, _), (ln2, t2) in index.items() if n2 == ch and t2.startswith(head)] if head else []
            problems.append('%s：找不到原文（可能已被改过，或已经同步过）%s' % (
                label, ('；开头相同的段落在 正文.md 第 %s 行，请人工核对' % '、'.join(str(l) for _, l in near)) if near else ''))
            continue
        ln, orig = hit
        o = list(orig)
        if pre < 0 or suf < 0 or pre + suf > len(o):
            problems.append('%s：前后缀长度越界，跳过' % label)
            continue
        if mid is None:
            segs = []
        else:
            new = ''.join(o[:pre]) + mid + ''.join(o[len(o) - suf:] if suf else [])
            segs = [s.strip() for s in new.replace('\r', '').split('\n') if s.strip()]
            if not segs:
                problems.append('%s：改完是空的（要删整段请用删除），跳过' % label)
                continue
            if any(bad_segment(s) for s in segs):
                problems.append('%s：改后内容含会破坏正文结构的行（# 开头 / > 开头 / --- / 场景线），跳过' % label)
                continue
        if segs == [orig]:
            problems.append('%s：改完与原文相同，无需处理' % label)
            continue
        if ln in seen and seen[ln] != segs:
            sys.exit('！%s 在多条修改里被改成了不同结果，请人工合并后再处理。' % label)
        seen[ln] = segs
        plan[ln] = (label, orig, segs)

    print('共 %d 条修改，可应用 %d 条，需人工处理 %d 条。\n' % (len(entries), len(plan), len(problems)))
    for ln in sorted(plan):
        label, orig, segs = plan[ln]
        print('[可应用] %s（正文第 %d 行）' % (label, ln))
        print('  原：%s' % orig)
        if not segs:
            print('  新：（删除整段）')
        for k, s in enumerate(segs):
            print('  新%s：%s' % ('' if len(segs) == 1 else '(%d/%d)' % (k + 1, len(segs)), s))
        print()
    for p in problems:
        print('[需人工] ' + p)

    if not a.write:
        print('\n（预览，没有改动文件。确认无误后加 --write。）')
        return
    if not plan:
        sys.exit('没有可写入的修改。')
    for ln in sorted(plan, reverse=True):
        _label, _orig, segs = plan[ln]
        if segs:
            lines[ln - 1] = '\n\n'.join(segs)
        else:
            del lines[ln - 1]
            if ln - 1 < len(lines) and not lines[ln - 1].strip():
                del lines[ln - 1]
    src.write_text('\n'.join(lines), encoding='utf-8')
    print('\n已写入 %s（%d 处）。接着：重新构建站点并核对、检查 canon 影响、追加变更记录。' % (src, len(plan)))


if __name__ == '__main__':
    main()
