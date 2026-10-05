import html
import json
from collections import Counter
from ..config import RUNTIME

LIMITATIONS = ['Local single-user MVP. Uploaded code execution is not a sandbox: host filesystem and network access are not isolated.', 'Only loopback HTTP targets are supported. Uploaded application startup and dependency installation are intentionally unavailable.', 'Static findings are candidates, not proof of exploitable vulnerabilities. Dependency CVE auditing and JS/TS execution/coverage are unavailable.', 'LLM judgments are estimates requiring review. No universal quality score is calculated.', 'Injection results are text observations; attack success, policy violation, unauthorized action, sensitive exposure and safe recovery rates require instrumented ground truth and are unavailable.', 'Natural-language citation verification, full JSON Schema, tool trace validation and conversation state isolation are not implemented. Functional cases support required fields, field types and exact field values.', 'Reports can contain target responses and user-supplied datasets. Review before sharing. API keys are never stored in run configuration.']

def score_for(items):
    passed=sum(r.get('status')=='passed' for r in items)
    failed=sum(r.get('status')=='failed' for r in items)
    total=passed+failed
    return round(passed*100/total,1) if total else None

def report_data(run,project):
    results=run['results']
    counts=dict(Counter(r['status'] for r in results))
    categories={c:dict(Counter(r['status'] for r in results if r['category']==c)) for c in run['config']['categories']}
    category_scores={c:score_for([r for r in results if r['category']==c]) for c in run['config']['categories']}
    return {'project':project,'run':run,'summary':counts,'score_percent':score_for(results),'category_scores_percent':category_scores,'category_findings':categories,'severity_findings':dict(Counter(r['severity'] for r in results)),'coverage':[r['actual'].get('coverage') for r in results if isinstance(r.get('actual'),dict) and r['actual'].get('coverage')],'limitations':LIMITATIONS,'formulas':{'score_percent':'passed / (passed + failed) * 100; blocked, needs_review and not_tested are excluded. Null means no scored cases.'},'recommendations':[{'test_id':r['id'],'recommendation':r.get('recommendation','Inspect evidence and configure the missing inputs.')} for r in results if r['status']!='passed']}
def generate(run,project):
    data=report_data(run,project)
    path=RUNTIME/'reports'/run['id']
    path.with_suffix('.json').write_text(json.dumps(data,indent=2,ensure_ascii=False),encoding='utf-8')
    esc=lambda v:html.escape(str(v))
    cards=''.join(f'<details data-status="{esc(r["status"])}"><summary>{esc(r["category"])} Â· {esc(r["name"])} â€” {esc(r["status"])}</summary><pre>{esc(json.dumps(r,indent=2,ensure_ascii=False))}</pre></details>' for r in run['results'])
    document='<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>AI Agent Testing Studio report</title><style>body{font:16px system-ui;background:#f5f7fb;color:#17243e;max-width:1100px;margin:40px auto;padding:20px}details,section{padding:20px;background:white;border:1px solid #ddd;border-radius:12px;margin:12px 0}summary{cursor:pointer;font-weight:600}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px monospace}select{padding:10px}</style><h1>AI Agent Testing Studio</h1><p>'+esc(project['name'])+' Â· '+esc(run['id'])+'</p><section><h2>Summary</h2><pre>'+esc(json.dumps({k:v for k,v in data.items() if k not in ('project','run')},indent=2,ensure_ascii=False))+'</pre></section><section><h2>Analysis, configuration and environment</h2><pre>'+esc(json.dumps({'analysis':project['analysis'],'config':run['config'],'environment':run['environment'],'started_at':run['started_at'],'finished_at':run.get('finished_at')},indent=2,ensure_ascii=False))+'</pre></section><label>Filter results <select id="filter"><option value="">All</option><option>passed</option><option>failed</option><option>blocked</option><option>needs_review</option><option>not_tested</option></select></label>'+cards+'<script>document.querySelector("#filter").onchange=e=>document.querySelectorAll("details").forEach(d=>d.hidden=!!e.target.value&&d.dataset.status!==e.target.value)</script></html>'
    path.with_suffix('.html').write_text(document,encoding='utf-8')
    return {'json':path.with_suffix('.json').name,'html':path.with_suffix('.html').name}

