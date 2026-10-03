#!/usr/bin/env python3
"""Offline HTML documentation layout checks; no product, network or real-device tests."""
from pathlib import Path
import shutil,json
from playwright.sync_api import sync_playwright
B=Path(__file__).resolve().parents[1];OUT=B/'document-previews';OUT.mkdir(exist_ok=True)
chromium=shutil.which('chromium') or shutil.which('chromium-browser')
if not chromium:raise SystemExit('Local Chromium required; browser download is not performed.')
content=(B/'MIRA_架构全书_v0.6.html').read_text(encoding='utf-8');parts=json.loads((B/'tools/book-parts.json').read_text());n=len(parts)
checks=[]
with sync_playwright() as p:
 browser=p.chromium.launch(executable_path=chromium,headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
 for label,w,h in [('desktop',1440,1000),('mobile',390,844)]:
  context=browser.new_context(viewport={'width':w,'height':h},device_scale_factor=1)
  context.route('**/*',lambda r:r.abort())
  page=context.new_page();page.set_content(content,wait_until='load');page.add_style_tag(content='html{scroll-behavior:auto!important}')
  page.screenshot(path=str(OUT/f'cover_{label}.png'))
  d=page.evaluate('''() => ({width:innerWidth,scrollWidth:document.documentElement.scrollWidth,chapters:document.querySelectorAll('.chapter').length,navLinks:document.querySelectorAll('aside a').length,missing:[...document.querySelectorAll('a[href^="#"]')].map(a=>a.hash.slice(1)).filter(id=>!document.getElementById(id)),tables:document.querySelectorAll('.table-wrap').length})''')
  d['viewport_label']=label;d['passed']=d['scrollWidth']<=w and d['chapters']==n and d['navLinks']==n and not d['missing']
  screenshots=[('h3:has-text("13.2 CLIProxyAPI")','codex_source'),('h2:has-text("12. 复用落点：语音基础设施")','voice_reuse'),('h3:has-text("WP01 订阅文本桥接")','work_package')]
  for selector,name in screenshots:
   page.locator(selector).first.evaluate('(el)=>el.scrollIntoView({block:"start"})')
   page.screenshot(path=str(OUT/f'{name}_{label}.png'))
  if label=='desktop':
   page.locator('#filter').fill('IC-01');page.wait_for_timeout(50)
   matching=page.locator('.chapter:visible').count();d['filter_ic01_matches']=matching
   page.locator('#filter').fill('no-such-mira-keyword-12345');page.wait_for_timeout(50)
   d['filter_empty_works']=page.locator('.chapter:visible').count()==0
   page.locator('#clear-filter').click();page.wait_for_timeout(50)
   d['filter_reset_works']=page.locator('.chapter:visible').count()==n
   d['passed']=d['passed'] and 0<matching<n and d['filter_empty_works'] and d['filter_reset_works']
  else:
   page.locator('#book-toc').scroll_into_view_if_needed()
   page.locator('.mobile-nav summary').click()
   d['mobile_nav_works']=page.locator('.mobile-nav a:visible').count()==n
   page.locator('.mobile-nav a').filter(has_text='M09 后端').first.click();page.wait_for_timeout(50)
   d['mobile_link_works']=page.evaluate('location.hash')==('#'+next(x['id'] for x in parts if '/09-provider-' in x['path']))
   d['passed']=d['passed'] and d['mobile_nav_works'] and d['mobile_link_works']
  checks.append(d);context.close()
 browser.close()
report={'scope':'Offline static documentation at desktop/mobile simulated browser viewports. Network requests blocked; NOT real-device or product verification.','passed':all(x['passed'] for x in checks),'viewports':checks,'screenshots':[p.relative_to(B).as_posix() for p in sorted(OUT.glob('*.png'))],'product_tests_executed':False,'real_device_tests_executed':False}
(B/'document-render-check.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
if not report['passed']:raise SystemExit(1)
