import copy
import asyncio, importlib.util, json, stat, uuid, zipfile
from contextlib import asynccontextmanager
from pathlib import PurePosixPath
from fastapi import FastAPI, HTTPException, Request, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from . import database as db
from .config import ROOT,RUNTIME,MAX_UPLOAD
from .blackbox.schema import Settings,CATEGORIES,CATEGORY_DETAILS
from .blackbox.runner import ACTIVE,TASKS,make_run,execute,save,aggregate,now
from .blackbox.reports import generate_pdf
from .blackbox import pricing,metering
from .blackbox.cost_summary import estimate,summarize
from .blackbox.catalog import build_cases

@asynccontextmanager
async def lifespan(app):
 metering.recover_interrupted()
 for run in db.all_records('blackbox'):
  if run['status'] in ('queued','running'):
   run.update(status='interrupted',finished_at=now(),stage='interrupted')
   for c in run['cases']:
    for r in c['results']:
     if r['reason']=='Pending execution.':r['reason']='Application restarted before this case ran.'
   save(aggregate(run))
 yield
 for event in ACTIVE.values():event.set()
 for task in list(TASKS):task.cancel()
 if TASKS:await asyncio.gather(*list(TASKS),return_exceptions=True)

app=FastAPI(title='AI Agent Studio — Black-box Judge',lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','::1','testserver'])
@app.middleware('http')
async def protect(request:Request,call_next):
 if request.method not in ('GET','HEAD','OPTIONS'):
  if request.headers.get('x-studio-request')!='1':return JSONResponse({'detail':'Missing Studio request header'},403)
  if request.headers.get('origin') and request.headers['origin']!=str(request.base_url).rstrip('/'):return JSONResponse({'detail':'Cross-origin request denied'},403)
  try:length=int(request.headers.get('content-length','0'))
  except ValueError:return JSONResponse({'detail':'Invalid content length'},400)
  limit=MAX_UPLOAD+1048576 if request.url.path=='/api/blackbox/upload' else 1048576
  if length>limit:return JSONResponse({'detail':'Request too large'},413)
 response=await call_next(request)
 response.headers.update({'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer','Cache-Control':'no-store'})
 return response

@app.get('/api/health')
def health():return {'status':'ok','mode':'blackbox','source_execution':False}
@app.get('/api/blackbox/capabilities')
def capabilities():
 return {'categories':CATEGORIES,'category_details':CATEGORY_DETAILS,'minimum_cases':30,'max_upload_mb':MAX_UPLOAD//1048576,'zip_sandbox':False,'zip_reason':'No verified isolated ZIP runner is configured. Uploaded code is never executed on the host.','packages':{p:bool(importlib.util.find_spec(p)) for p in ('deepeval','deepteam','garak','transformers','torch','playwright','reportlab')},'judge':'Configure a local OpenAI-compatible server. Package installation does not mean a model is ready.'}
@app.get('/api/blackbox/defaults')
def easy_defaults():
 from .blackbox.easy_setup import public_defaults
 return public_defaults()
@app.get('/api/cost/settings')
def cost_settings():
 snap=pricing.snapshot()
 return {'settings':pricing.settings(),'snapshot':{k:snap[k] for k in ('id','source','date')},'model_count':len(snap['models'])}
@app.put('/api/cost/settings')
def update_cost_settings(data:dict):
 try:return pricing.save_settings(data)
 except (ValueError,TypeError,ArithmeticError) as exc:raise HTTPException(422,str(exc))
@app.post('/api/cost/prices/update')
async def update_prices():
 try:snap=await pricing.refresh()
 except Exception:raise HTTPException(502,'Could not refresh price source. The previous snapshot is unchanged.')
 return {k:snap[k] for k in ('id','source','date')}
@app.post('/api/cost/estimate')
def estimate_cost(config:Settings):
 from .blackbox.easy_setup import judge_defaults
 if not config.judge_model:config.judge_model=judge_defaults()['model']
 config.price_snapshot_id='';config.cost_settings_snapshot={}
 for target in config.targets:
  if not target.model_alias:target.model_alias=pricing.settings()['aliases'].get(target.name,'')
 return estimate(config,build_cases(config))
@app.post('/api/blackbox/easy-run')
async def easy_run(config:Settings):
 from .blackbox.easy_setup import prepare
 if ACTIVE:raise HTTPException(409,'An evaluation is already running.')
 try:config,notes=await prepare(config)
 except ValueError as exc:raise HTTPException(422,str(exc))
 result=await start(config)
 return {**result,'setup_notes':notes}
@app.post('/api/blackbox/runs')
async def start(config:Settings):
 if ACTIVE:raise HTTPException(409,'One evaluation is already running; stop it before starting another.')
 for target in config.targets:
  if target.kind=='zip':
   try:ident=str(uuid.UUID(target.archive_id))
   except ValueError:raise HTTPException(422,'Upload a ZIP first.')
   if not db.get('blackbox_archive',ident):raise HTTPException(404,'ZIP not found.')
 for target in config.targets:
  if not target.model_alias:target.model_alias=pricing.settings()['aliases'].get(target.name,'')
 # New runs pin server-side saved prices; caller-supplied internal snapshots are not trusted.
 config.price_snapshot_id='';config.cost_settings_snapshot={}
 run=make_run(config);save(run,config);ACTIVE[run['id']]=asyncio.Event()
 task=asyncio.create_task(execute(run,config));TASKS.add(task);task.add_done_callback(TASKS.discard)
 return {'id':run['id'],'planned_cases':len(run['cases']),'mode':'compare' if len(config.targets)==2 else 'single'}
@app.post('/api/blackbox/runs/{ident}/resume')
async def resume_run(ident:uuid.UUID,config:Settings):
 if ACTIVE:raise HTTPException(409,'Another evaluation is running.')
 run=get_run(ident)
 config.price_snapshot_id=run['config'].get('price_snapshot_id','')
 config.cost_settings_snapshot=run['config'].get('cost_settings_snapshot',{})
 if not config.price_snapshot_id:
  raise HTTPException(422,'This run predates cost tracking. Start a new run to meter all calls consistently.')
 for key in ('categories','references','policy','scope','judge_url','judge_model'):
  if getattr(config,key)!=run['config'].get(key):raise HTTPException(422,'Resume must use the same cases, policy and judge as the original run.')
 if [t.model_dump(exclude={'token'}) for t in config.targets]!=run['targets']:raise HTTPException(422,'Resume must use the same target configuration.')
 pending=0
 for case in run['cases']:
  if any(r['status']=='not_tested' for r in case['results']):
   case.setdefault('previous_attempts',[]).append(copy.deepcopy({'results':case['results'],'pair':case['pair']}))
   case['completed']=False;pending+=1
 run['cases'].sort(key=lambda c:int(c['id'].rsplit('-',1)[-1]))
 run.update(status='queued',stage='Resuming missing cases with slower pacing',resumed_at=now(),finished_at=None)
 run['progress']=round(100*sum(c.get('completed',False) for c in run['cases'])/len(run['cases']),1)
 run['config']['request_pause_seconds']=config.request_pause_seconds
 run['config']['max_minutes']=config.max_minutes
 save(run,config);ACTIVE[run['id']]=asyncio.Event()
 task=asyncio.create_task(execute(run,config));TASKS.add(task);task.add_done_callback(TASKS.discard)
 return {'id':run['id'],'pending_cases':pending}
@app.get('/api/blackbox/runs')
def list_runs():return [{k:r.get(k) for k in ('id','status','started_at','targets','progress','summary')} for r in db.all_records('blackbox')]
def get_run(ident):
 run=db.get('blackbox',str(ident))
 if not run:raise HTTPException(404,'Run not found.')
 run['costs']=summarize(run)
 return run
@app.get('/api/blackbox/runs/{ident}')
def result(ident:uuid.UUID):return get_run(ident)
@app.post('/api/blackbox/runs/{ident}/stop')
def stop(ident:uuid.UUID):
 get_run(ident)
 if str(ident) in ACTIVE:ACTIVE[str(ident)].set()
 return {'stop_requested':True}
@app.get('/api/blackbox/runs/{ident}/download')
def download(ident:uuid.UUID,format:str='json'):
 run=get_run(ident)
 if format=='json':return Response(json.dumps(run,ensure_ascii=False,indent=2),media_type='application/json',headers={'Content-Disposition':f'attachment; filename="blackbox-{ident}.json"'})
 if format=='pdf':
  if run['status'] in ('queued','running'):raise HTTPException(409,'Wait for the run to finish before creating the PDF.')
  return FileResponse(generate_pdf(run),filename=f'blackbox-{ident}.pdf',media_type='application/pdf')
 raise HTTPException(422,'Choose json or pdf.')
@app.get('/api/blackbox/history')
def history():return {'notice':'Historical results use earlier scoring and may include retired source checks. They are not black-box benchmark scores.','runs':db.all_records('run'),'comparisons':db.all_records('comparison')}
@app.post('/api/blackbox/upload')
async def upload(file:UploadFile=File(...)):
 if not file.filename or not file.filename.lower().endswith('.zip'):raise HTTPException(422,'Upload a ZIP archive.')
 ident=str(uuid.uuid4());path=RUNTIME/'uploads'/f'{ident}.zip';size=0
 try:
  with path.open('wb') as out:
   while data:=await file.read(1048576):
    size+=len(data)
    if size>MAX_UPLOAD:raise ValueError('ZIP exceeds configured upload size limit.')
    out.write(data)
  with zipfile.ZipFile(path) as archive:
   entries=archive.infolist()
   if len(entries)>100000:raise ValueError('Too many archive entries.')
   expanded=0
   for e in entries:
    p=PurePosixPath(e.filename.replace('\\','/'))
    if p.is_absolute() or '..' in p.parts or ':' in e.filename:raise ValueError('Unsafe archive path.')
    if e.flag_bits&1:raise ValueError('Encrypted ZIPs are unsupported. Upload an unencrypted archive.')
    if e.file_size/max(e.compress_size,1)>200:raise ValueError('Suspicious archive expansion ratio.')
    expanded+=e.file_size
    if expanded>4*1024**3:raise ValueError('Archive expands beyond 4 GB limit.')
  record={'id':ident,'name':file.filename,'size':size,'entries':len(entries),'status':'stored_not_executed','reason':'No verified isolated sandbox is configured. ZIP is stored without extraction or execution.'}
  db.save('blackbox_archive',record);return record
 except (ValueError,zipfile.BadZipFile) as e:
  path.unlink(missing_ok=True);raise HTTPException(422,str(e))
 finally:await file.close()
@app.post('/api/projects/{rest:path}')
def retired(rest:str):raise HTTPException(410,'Source-code testing is retired. Use the black-box evaluation screen.')
app.mount('/',StaticFiles(directory=ROOT/'app'/'blackbox_static',html=True),name='frontend')
