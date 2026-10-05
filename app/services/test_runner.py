import asyncio
import os
import platform
import threading
import time
import uuid
from datetime import datetime, timezone
from .. import database as db
from ..config import RUNTIME, MAX_CASES
from .functional_tester import functional, target
from .security_tester import bandit, existing_tests
from .performance_tester import performance
from .ai_evaluator import evaluate
from .report_generator import generate

ACTIVE={}
def now():
    return datetime.now(timezone.utc).isoformat()

def redact(value, key=''):
    if isinstance(value,dict):
        return {k:('[REDACTED]' if any(s in k.lower() for s in ('password','api_key','authorization','access_token','secret')) else redact(v,key)) for k,v in value.items()}
    if isinstance(value,list):
        return [redact(v,key) for v in value]
    if isinstance(value,str):
        for secret in (key,os.getenv('OPENAI_API_KEY','')):
            if secret:
                value=value.replace(secret,'[REDACTED]')
        return value[:30000]
    return value

def create_run(project,config):
    ident=str(uuid.uuid4())
    clean=config.model_dump(exclude={'api_key'})
    run={'id':ident,'project_id':project['id'],'status':'queued','stage':'queued','progress':0,'started_at':now(),'finished_at':None,'config':redact(clean),'results':[],'logs':[],'environment':{'python':platform.python_version(),'os':platform.system(),'network_isolated':False,'uploaded_code_sandboxed':False}}
    db.save('run',run)
    stop=threading.Event()
    ACTIVE[ident]=stop
    asyncio.create_task(execute(run,project,config,stop))
    return run

async def execute(run,project,config,stop):
    root=RUNTIME/'extracted'/project['id']
    run['status']='running'
    key=config.api_key.get_secret_value() if config.api_key else ''
    def log(message):
        run['logs'].append({'timestamp':now(),'message':message})
        db.save('run',run)
    def add(category,result):
        if len(run['results']) >= MAX_CASES:
            return
        result={'id':str(uuid.uuid4()),'category':category,'name':category,'input':None,'expected':None,'actual':None,'status':'needs_review','severity':'info','duration_ms':0,'evidence':[],**result}
        if result['status']=='failed' and result['severity']=='info':
            result['severity']='medium'
        run['results'].append(redact(result,key))
        log(f'{category}: {result["name"]} — {result["status"]}')
    try:
        for index,category in enumerate(config.categories):
            if stop.is_set():
                for remaining in config.categories[index:]:
                    add(remaining,{'name':'Execution cancelled','status':'not_tested','actual':'Stopped by user'})
                break
            run['stage']=category
            run['progress']=round(index/len(config.categories)*100)
            log('Starting '+category)
            start=time.perf_counter()
            if len(run['results']) >= MAX_CASES:
                log('Configured test-case limit reached; remaining categories not executed.')
                break
            if category=='static':
                analysis=project['analysis']
                errors=[f for f in analysis['findings'] if f['rule']=='syntax']
                add(category,{'name':'Python AST and source inspection','status':'failed' if errors else ('passed' if analysis['languages'] else 'blocked'),'actual':{'files_analyzed':len(analysis['files']),'functions_discovered':len(analysis['functions']),'tests_discovered':len(analysis['tests']),'syntax_errors':errors},'evidence':['Python AST parsing; JS/TS detections use heuristics. No JS/TS compiler checks performed.']})
                for finding in analysis['findings']:
                    if finding['rule']!='syntax':
                        add(category,{'name':finding['rule'],'status':'needs_review','severity':finding['severity'],'actual':finding,'evidence':[f"{finding['file']}:{finding['line']}"],'recommendation':finding['detail']})
            elif category=='security':
                if 'Python' in project['analysis']['languages']:
                    add(category,await bandit(root,stop))
                else:
                    add(category,{'name':'Bandit','status':'blocked','actual':'Bandit supports Python only.'})
                add(category,{'name':'Dependency vulnerability audit','status':'blocked','actual':{'manifests':project['analysis']['manifests'],'reason':'Dependency inventory detected; advisory-database audit is not implemented. No dependency security score.'}})
            elif category in ('unit','coverage'):
                if category=='coverage' and 'unit' in config.categories and any(r['category']=='unit' for r in run['results']):
                    previous=next(r for r in run['results'] if r['category']=='unit')
                    coverage=previous.get('actual',{}).get('coverage') if isinstance(previous.get('actual'),dict) else None
                    add(category,{'name':'Coverage metrics','status':'passed' if coverage else 'blocked','actual':coverage or 'Coverage unavailable; inspect pytest result.','evidence':['Coverage measures executed code, not correctness or security.']})
                elif 'Python' not in project['analysis']['languages'] or not project['analysis']['tests']:
                    add(category,{'name':'Existing project tests','status':'blocked','actual':'No supported Python test files found. JS/TS execution and coverage unavailable.'})
                else:
                    add(category,await existing_tests(root,config,stop))
            elif not config.target_url:
                add(category,{'name':'Target configuration','status':'blocked','actual':'Configure an explicit local target URL, endpoint and JSON fields.'})
            else:
                try:
                    target(config)
                except ValueError as exc:
                    add(category,{'name':'Target validation','status':'blocked','actual':str(exc)})
                    continue
                if category=='functional':
                    async for result in functional(config):
                        if stop.is_set() or len(run['results'])>=MAX_CASES:
                            break
                        add(category,result)
                elif category=='performance':
                    if not config.performance_consent:
                        add(category,{'name':'Load-test consent','status':'blocked','actual':'Confirm authorization for the target and configured workload.'})
                    else:
                        result=await performance(config,stop)
                        add(category,{'name':'Controlled HTTP workload','status':'failed' if result['failed_requests'] else ('passed' if result['total_requests'] else 'blocked'),'actual':result,'duration_ms':round(result['elapsed_seconds']*1000),'evidence':['Success means HTTP 2xx only. No latency SLO supplied; no latency pass claim.']})
                else:
                    async for result in evaluate(category,config):
                        if stop.is_set() or len(run['results'])>=MAX_CASES:
                            break
                        add(category,result)
            run.setdefault('category_duration_ms',{})[category]=round((time.perf_counter()-start)*1000,2)
        run['status']='stopped' if stop.is_set() else 'completed'
    except Exception as exc:
        run['status']='error'
        log(f'Execution error ({type(exc).__name__}); review configuration. Exception text withheld to protect secrets.')
    finally:
        run['finished_at']=now()
        run['progress']=100 if run['status']=='completed' else run['progress']
        run['stage']=run['status']
        try:
            run['report']=generate(run,project)
        except Exception:
            run['logs'].append({'timestamp':now(),'message':'Report generation failed.'})
        db.save('run',run)
        ACTIVE.pop(run['id'],None)
