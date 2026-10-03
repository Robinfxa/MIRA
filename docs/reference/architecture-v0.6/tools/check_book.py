#!/usr/bin/env python3
"""Local documentation validation only. Does not execute product or upstream tests."""
from pathlib import Path
import hashlib,json,re,sys,subprocess
from urllib.parse import unquote
B=Path(__file__).resolve().parents[1];A=B/'docs/architecture';R=B/'docs/history/open-source-reference-v0.1';O=B/'docs/history/edition-v0.5'
checks=[]
def add(name,ok,detail=''):checks.append({'check':name,'passed':bool(ok),'detail':detail})
def txt(p):return p.read_text(encoding='utf-8')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def js(p):return json.loads(txt(p))
def jhash(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
m=js(B/'docs/reference/source-manifest.json');om=js(O/'source-manifest.json');pv=js(B/'integration-provenance.json')
add('edition_v06',m['edition']=='v0.6' and m['date']=='2026-10-03')
add('confirmed_decisions_exactly_retained',m['confirmed_decisions']==om['confirmed_decisions'])
add('last_product_decision_unchanged',m['last_decision']==om['last_decision'])
add('integration_instruction_exact',m['last_document_instruction']['user_text']=='把你的架构书和这个借鉴整合一下')
add('no_extra_adoption',not m['last_document_instruction']['specific_stack_adoption'])
for flag in ['product_tests_run','provider_calls_run','github_written','credentials_read','upstream_tests_run','external_sources_refetched_in_this_edition']:
 add('false:'+flag,m[flag] is False)
add('no_new_online_sources',m['public_docs_read_in_this_edition']==[])
for s in m['sources']:
 p=B/s['path'];add('source:'+s['path'],p.is_file() and p.stat().st_size==s['bytes'] and sha(p)==s['sha256'])
for r in pv['archival_files']:
 p=B/r['archived_path'];add('archive:'+r['archived_path'],p.is_file() and p.stat().st_size==r['bytes'] and sha(p)==r['sha256'])
adrs=list((A/'adr').glob('*.md'));add('eight_adrs',len(adrs)==8)
for p in adrs:
 old=O/'architecture-source/adr'/p.name
 add('adr_unchanged:'+p.name,p.read_bytes()==old.read_bytes())
modules=list((A/'modules').glob('*.md'));add('ten_modules',len(modules)==10)
for p in modules:
 if not p.name.startswith('10-'):add('reuse_section:'+p.name,'复用落点' in txt(p) and 'RI-' in txt(p))
cat=js(A/'appendices/acceptance-catalog.json');oldcat=js(O/'architecture-source/appendices/acceptance-catalog.json');ri=js(R/'reference-intake-cases.json')
add('164_unique_ids',len(cat)==164 and len(set(x['id'] for x in cat))==164)
add('146_original_exact_objects',cat[:146]==oldcat and jhash(cat[:146])==m['acceptance_inherited_146_sha256'])
add('all_not_run',all(x['execution_status']=='not_run' for x in cat))
add('18_RI_scenarios_assertions_exact',[(x['id'],x['scenario'],x['assertion']) for x in cat[146:]]==[(x['id'],x['area'],x['assertion']) for x in ri])
a2=txt(A/'appendices/A2-requirements-and-tests.md');add('all_test_ids_in_A2',all(f"| {x['id']} |" in a2 for x in cat))
reg=js(B/'docs/reference/opensource/reference-registry.json');orig=js(R/'reference-registry.json')
add('reference_registry_unchanged',reg==orig and (B/'docs/reference/opensource/reference-registry.json').read_bytes()==(R/'reference-registry.json').read_bytes())
add('16_projects_41_sources',len(reg['projects'])==16 and len(reg['sources'])==41)
add('10_key_source_projects',sum(x['evidence_level']=='key_source_read_at_pinned_commit' for x in reg['projects'])==10)
add('no_upstream_claim_promoted',all(not x['upstream_tests_run'] and not x['mira_integration_tests_run'] and not x['account_verified'] for x in reg['projects']))
a5=txt(A/'appendices/A5-open-source-evidence-and-licenses.md')
add('all_sources_scope_present',all(s['review_scope'] in a5 and s['url'] in a5 and f"OS-{s['id']}" in a5 for s in reg['sources']))
add('all_project_commits_present',all(not p.get('review_commit') or p['review_commit'] in a5 for p in reg['projects']))
m09=txt(A/'modules/09-provider-auth-usage-and-codex.md');a4=txt(A/'appendices/A4-integration-differences-and-boundaries.md')
add('IC01_not_silently_resolved',all(x in m09 for x in ['IC-01','本次未取得解除该限制的新决定','已有可定位实现','社区兼容承载']) and '待承载准入' in a4)
add('G03_A_maintained','采用G03已批准A模式' in m09)
add('no_auto_paid_fallback','api_fallback_requires_explicit_permission' in m09 and '不自动购买' in m09)
add('G04_semantic_resume_stays_off','默认关闭' in txt(A/'modules/04-permits-interruption-and-recovery.md'))
trace=js(A/'appendices/reuse-traceability.json');ids={x['id'] for x in cat}
add('RI_trace18',len(trace)==18 and {x['id'] for x in trace}=={x['id'] for x in cat[146:]})
add('related_cases_exist',all(all(i in ids for i in x['related_existing_case_ids']) for x in trace))
m10=txt(A/'modules/10-reuse-integration-and-work-packages.md')
add('eight_work_packages',all(f'### WP{i:02d}' in m10 for i in range(1,9)))
add('source_baseline_matches',sha(R/'baseline/MIRA_架构全书_v0.5.md')==sha(O/'MIRA_架构全书_v0.5.md'))
paths=[B/'README.md',B/'MIRA_架构全书_v0.6.md',B/'docs/reference/source-register.md']+list(A.rglob('*.md'))
broken=[];fences=[];stale=[];tokens=[]
for p in paths:
 t=txt(p)
 if t.count('```')%2:fences.append(str(p.relative_to(B)))
 if any(x in t for x in ['','ELLIPSIZATION','(truncated)']):tokens.append(str(p.relative_to(B)))
 if '/adr/' not in str(p) and p.name!='CHANGELOG.md':
  for x in ['本版共146条','本轮仅重新核查CX','本轮新核查CX','本版只更新文档、读取公开资料']:
   if x in t:stale.append([p.name,x])
 for label,url in re.findall(r'\[([^\]\n]+)\]\(([^)\n]+)\)',t):
  if url.startswith(('http:','https:','mailto:','#')):continue
  d=url.split('#',1)[0]
  if d and not (p.parent/unquote(d)).is_file():broken.append([str(p.relative_to(B)),url])
add('current_relative_links_resolve',not broken,str(broken));add('balanced_fences',not fences,str(fences));add('no_tool_tokens',not tokens,str(tokens));add('no_stale_current_counts_or_research_claims',not stale,str(stale))
book=txt(B/'MIRA_架构全书_v0.6.md');anc=re.findall(r'<a id="([^"]+)"',book)
add('29_anchor_ids_28_parts_and_toc',len(anc)==29 and len(set(anc))==29)
add('toc_resolves',all(i in anc for i in re.findall(r'\]\(#([^)]*)\)',book)))
add('no_distributed_fonts',not any(p.suffix.lower() in ['.ttf','.otf','.woff','.woff2'] for p in B.rglob('*')))
exports=['MIRA_架构全书_v0.6.md','MIRA_架构全书_v0.6.html','tools/book-parts.json'];before={n:sha(B/n) for n in exports}
for script in ['build_book.py','build_html.py']:
 subprocess.run([sys.executable,str(B/'tools'/script)],check=True,capture_output=True,text=True)
add('reproducible_exports',before=={n:sha(B/n) for n in exports})
report={'scope':'Local documentation consistency, immutable input archives, approved decision preservation, reference/test mappings and reproducible exports. NOT product/upstream/account/legal/performance validation.','passed':all(x['passed'] for x in checks),'checks':checks,'product_tests_executed':False,'upstream_tests_executed':False,'provider_calls_executed':False,'github_written':False}
(B/'document-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'passed':report['passed'],'checks':len(checks),'failed':[x for x in checks if not x['passed']]},ensure_ascii=False,indent=2))
sys.exit(0 if report['passed'] else 1)
