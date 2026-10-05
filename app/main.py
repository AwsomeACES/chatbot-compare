import asyncio
import shutil
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from . import database as db
from .config import ROOT, RUNTIME, MAX_UPLOAD
from .models import RunConfig
from .services.zip_handler import extract_zip
from .services.code_analyzer import analyze
from .services.test_runner import create_run, ACTIVE, now
from .services.report_generator import report_data

@asynccontextmanager
async def lifespan(app):
    for run in db.all_records('run'):
        if run['status'] in ('queued','running'):
            run.update(status='interrupted',stage='interrupted',finished_at=now())
            db.save('run',run)
    yield
    for stop in ACTIVE.values():
        stop.set()

app=FastAPI(title='AI Agent Testing Studio',lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=['127.0.0.1','localhost','::1','testserver'])

@app.middleware('http')
async def local_protection(request:Request,call_next):
    if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('x-studio-request')!='1':
        return JSONResponse({'detail':'Missing local Studio request header'},status_code=403)
    origin=request.headers.get('origin')
    if origin and origin != str(request.base_url).rstrip('/'):
        return JSONResponse({'detail':'Cross-origin access denied'},status_code=403)
    if int(request.headers.get('content-length','0') or 0) > MAX_UPLOAD+1024*1024:
        return JSONResponse({'detail':'Upload exceeds size limit'},status_code=413)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Referrer-Policy']='no-referrer'
    return response

def project_or_404(ident):
    project=db.get('project',ident)
    if not project:
        raise HTTPException(404,'Project not found')
    return project

def run_or_404(ident):
    run=db.get('run',ident)
    if not run:
        raise HTTPException(404,'Run not found')
    return run

@app.get('/api/health')
def health():
    return {'status':'ok','app':'AI Agent Testing Studio','execution_sandboxed':False,'max_upload_mb':MAX_UPLOAD//1024//1024}

@app.post('/api/projects/upload',status_code=201)
async def upload(file:UploadFile=File(...)):
    if not file.filename or not file.filename.lower().endswith('.zip'):
        raise HTTPException(400,'Only ZIP files are supported')
    ident=str(uuid.uuid4())
    archive=RUNTIME/'uploads'/f'{ident}.zip'
    dest=RUNTIME/'extracted'/ident
    size=0
    try:
        with archive.open('wb') as output:
            while chunk:=await file.read(65536):
                size+=len(chunk)
                if size>MAX_UPLOAD:
                    raise ValueError('Upload exceeds configured size limit')
                output.write(chunk)
        validation=await asyncio.to_thread(extract_zip,archive,dest)
        analysis=await asyncio.to_thread(analyze,dest)
        project={'id':ident,'name':Path(file.filename.replace('\\','/')).name,'created_at':now(),'size':size,'validation':validation,'analysis':analysis}
        db.save('project',project)
        return project
    except ValueError as exc:
        if dest.exists():
            shutil.rmtree(dest)
        raise HTTPException(400,str(exc)) from exc
    finally:
        archive.unlink(missing_ok=True)
        await file.close()

@app.get('/api/projects')
def projects():
    return db.all_records('project')

@app.get('/api/projects/{project_id}')
def get_project(project_id:uuid.UUID):
    return project_or_404(project_id)

@app.delete('/api/projects/{project_id}')
def delete_project(project_id:uuid.UUID):
    project_or_404(project_id)
    if any(r['project_id']==str(project_id) and r['id'] in ACTIVE for r in db.all_records('run')):
        raise HTTPException(409,'Stop active testing before removal')
    dest=RUNTIME/'extracted'/str(project_id)
    if dest.exists():
        shutil.rmtree(dest)
    for run in db.all_records('run'):
        if run['project_id']==str(project_id):
            for ext in ('.html','.json'):
                (RUNTIME/'reports'/(run['id']+ext)).unlink(missing_ok=True)
            db.delete('run',run['id'])
    db.delete('project',project_id)
    return {'deleted':True}

@app.post('/api/projects/{project_id}/analyze')
async def reanalyze(project_id:uuid.UUID):
    project=project_or_404(project_id)
    project['analysis']=await asyncio.to_thread(analyze,RUNTIME/'extracted'/str(project_id))
    db.save('project',project)
    return project

@app.post('/api/projects/{project_id}/tests/run',status_code=202)
async def run_tests(project_id:uuid.UUID,config:RunConfig):
    if ACTIVE:
        raise HTTPException(409,'One run at a time is supported; stop or wait for the active run')
    return create_run(project_or_404(project_id),config)

@app.get('/api/runs')
def runs():
    return db.all_records('run')

@app.get('/api/runs/{run_id}')
def get_run(run_id:uuid.UUID):
    return run_or_404(run_id)

@app.get('/api/runs/{run_id}/results')
def results(run_id:uuid.UUID):
    return run_or_404(run_id)['results']

@app.get('/api/runs/{run_id}/progress')
def progress(run_id:uuid.UUID):
    run=run_or_404(run_id)
    return {k:run[k] for k in ('id','status','stage','progress','logs','results','started_at')}

@app.post('/api/runs/{run_id}/stop')
def stop(run_id:uuid.UUID):
    run_or_404(run_id)
    if str(run_id) in ACTIVE:
        ACTIVE[str(run_id)].set()
    return {'stop_requested':True}

@app.get('/api/runs/{run_id}/report')
def report(run_id:uuid.UUID):
    run=run_or_404(run_id)
    return report_data(run,project_or_404(run['project_id']))

@app.get('/api/runs/{run_id}/report/download')
def download(run_id:uuid.UUID,format:str='html'):
    if format not in ('html','json'):
        raise HTTPException(422,'Format must be html or json')
    run_or_404(run_id)
    path=RUNTIME/'reports'/f'{run_id}.{format}'
    if not path.exists():
        raise HTTPException(409,'Report is not yet available')
    return FileResponse(path,filename=f'studio-report-{run_id}.{format}',media_type='text/html' if format=='html' else 'application/json')

app.mount('/',StaticFiles(directory=ROOT/'app'/'static',html=True),name='frontend')
