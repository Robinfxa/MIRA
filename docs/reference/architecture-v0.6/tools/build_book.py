#!/usr/bin/env python3
"""Compile the MIRA architecture + reuse reading edition from the sole current chapters.
No network, account access or product execution. Python 3.10+.
"""
from pathlib import Path
import os, re, json
B=Path(__file__).resolve().parents[1]
A=B/'docs/architecture'
def chapters():
    return ([A/'00-master-design-book.md']+sorted((A/'modules').glob('*.md'))
        +sorted((A/'adr').glob('*.md'))+sorted((A/'appendices').glob('A*.md'))
        +[A/'pending/implementation-and-access-gates.md',A/'CHANGELOG.md',B/'docs/reference/source-register.md'])

def build():
    parts=chapters()
    if not all(p.is_file() for p in parts):raise FileNotFoundError('A chapter is missing.')
    lookup={p.resolve():f'book-part-{i:02}' for i,p in enumerate(parts)}
    intro='''# MIRA 实时多模态互动场景产品 · 架构与开源复用整合书

**v0.6｜2026-10-03｜架构合同 × 现成实现 × 适配差分 × 验收**

基线：架构书v0.5＋开源实现借鉴书v0.1。已确认G01–G06、Codex usage优先及API预留保持不变；本次不新增技术栈批准。

每个模块按“合同→复用入口→差分→工作包→验收”阅读。16个项目、10个固定提交关键源码项目的记录沿用借鉴书；本版不宣称重新核查上游。首联调组合是建议，不是依赖安装锁。M09／A4显式保留IC-01承载边界分歧，不把它靠编辑默默消除。

原146条验收＋18条RI接入记录＝164条，全部未执行且有重叠，不是独立样本量。旧架构、借鉴书、ADR和来源按原字节保留。当前分章是唯一维护入口；本阅读版自动生成，不是产品代码、账户准入或性能结论。

<a id="book-toc"></a>
## 全书目录

'''
    ordered=[]
    for p in parts:
        title=p.read_text(encoding='utf-8').splitlines()[0].lstrip('# ')
        intro+=f'- [{title}](#{lookup[p.resolve()]})\n'
    content=[intro]
    for p in parts:
        t=p.read_text(encoding='utf-8')
        def link(m):
            label,target=m.group(1),m.group(2)
            if target.startswith(('http:','https:','mailto:','#')):return m[0]
            path,sep,fragment=target.partition('#')
            dst=(p.parent/path).resolve()
            if dst in lookup and not fragment:return f'[{label}](#{lookup[dst]})'
            dest=Path(os.path.relpath(dst,B)).as_posix()+(('#'+fragment) if sep else '')
            return f'[{label}]({dest})'
        t=re.sub(r'\[([^\]\n]+)\]\(([^)\n]+)\)',link,t)
        ident=lookup[p.resolve()];rel=p.relative_to(B).as_posix()
        content.append(f'\n---\n\n<a id="{ident}"></a>\n\n'+t+f'\n*分章来源：`{rel}` · [返回目录](#book-toc)*\n')
        ordered.append({'id':ident,'path':rel,'title':t.splitlines()[0].lstrip('# '),'markdown':t})
    (B/'MIRA_架构全书_v0.6.md').write_text('\n'.join(content),encoding='utf-8')
    (B/'tools/book-parts.json').write_text(json.dumps(ordered,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'parts':len(ordered),'characters':len('\n'.join(content)),'scope':'document_only'},ensure_ascii=False))
if __name__=='__main__':build()
