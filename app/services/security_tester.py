import asyncio
import ctypes
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from ..config import RUNTIME, TIMEOUT

def terminate(process):
    if process.poll() is None:
        if os.name == 'nt':
            subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=10)
        else:
            process.kill()

def capture(args, cwd, stop, timeout=TIMEOUT):
    # Environment deliberately excludes API keys, user profile, PYTHONPATH and proxy settings.
    env={k:v for k,v in os.environ.items() if k.upper() in {'SYSTEMROOT','WINDIR','COMSPEC','PATHEXT'}}
    env.update({'PATH':str(Path(sys.executable).parent)+os.pathsep+str(Path(os.environ.get('SYSTEMROOT','C:/Windows'))/'System32'),'TEMP':str(cwd),'TMP':str(cwd),'PYTEST_DISABLE_PLUGIN_AUTOLOAD':'1','PYTHONIOENCODING':'utf-8'})
    log=Path(cwd)/'studio-process.log'
    start=time.monotonic()
    with log.open('wb') as output:
        proc=subprocess.Popen(args,cwd=cwd,env=env,stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        reason=None
        try:
            while proc.poll() is None:
                if stop.is_set() or time.monotonic()-start > timeout or log.stat().st_size > 1048576:
                    reason='Stopped, timed out, or exceeded 1 MB output limit'
                    terminate(proc)
                    break
                time.sleep(.1)
            proc.wait(timeout=10)
        finally:
            terminate(proc)
    # Do not return raw uploaded-code output: it can contain host file contents or secrets.
    return {'returncode':proc.returncode,'termination':reason,'output_bytes':log.stat().st_size,'duration_ms':round((time.monotonic()-start)*1000,2),'output_notice':'Raw subprocess output withheld to prevent accidental secret disclosure.'}

async def bandit(root, stop):
    with tempfile.TemporaryDirectory(dir=RUNTIME/'work') as work:
        result=await asyncio.to_thread(capture,[sys.executable,'-m','bandit','-r',str(root),'-f','json','-o',str(Path(work)/'bandit.json'),'-q','--ignore-nosec'],work,stop)
        report=Path(work)/'bandit.json'
        if not report.exists() or report.stat().st_size > 3000000:
            return {'status':'blocked','name':'Bandit security scan','actual':result,'evidence':['Bandit report unavailable.']}
        data=json.loads(report.read_text(encoding='utf-8'))
        findings=[{'rule':f['test_id'],'severity':f['issue_severity'],'confidence':f['issue_confidence'],'file':Path(f['filename']).relative_to(root).as_posix(),'line':f['line_number'],'detail':f['issue_text']} for f in data.get('results',[])]
        return {'name':'Bandit security scan','status':'needs_review' if findings else ('blocked' if data.get('errors') else 'passed'),'actual':{'findings':findings,'metrics':{'files':len(data.get('metrics',{}))-1},'scan_errors':len(data.get('errors',[]))},'evidence':['Static security candidates require contextual review. Source snippets are withheld.'],'duration_ms':result['duration_ms'],'recommendation':'Review cited rule and source location; no vulnerability-free guarantee.'}

async def existing_tests(root, config, stop):
    if not config.execution_consent:
        return {'name':'Existing pytest / coverage','status':'blocked','actual':'Explicit uploaded-code execution consent is required.'}
    if os.name=='nt' and ctypes.windll.shell32.IsUserAnAdmin():
        return {'name':'Existing pytest / coverage','status':'blocked','actual':'Refusing uploaded code because the host process is elevated. Restart from a non-administrator terminal.'}
    with tempfile.TemporaryDirectory(dir=RUNTIME/'work') as work:
        dest=Path(work)/'project'
        shutil.copytree(root,dest)
        while len(list(dest.iterdir())) == 1 and next(dest.iterdir()).is_dir():
            dest=next(dest.iterdir())
        args=[sys.executable,'-m','pytest','-o','addopts=','-q','--tb=no','-p','pytest_cov']
        if 'coverage' in config.categories:
            args += ['--cov=.','--cov-branch','--cov-report=json:studio-coverage.json']
        result=await asyncio.to_thread(capture,args,dest,stop)
        coverage=dest/'studio-coverage.json'
        if coverage.exists() and coverage.stat().st_size < 3000000:
            data=json.loads(coverage.read_text(encoding='utf-8'))['totals']
            statements=data.get('num_statements',0)
            branches=data.get('num_branches',0)
            result['coverage']={'statement_percent':100*data.get('covered_lines',0)/statements if statements else None,'branch_percent':100*data.get('covered_branches',0)/branches if branches else None,'statements':statements,'branches':branches,'missing_lines':data.get('missing_lines'),'missing_branches':data.get('missing_branches'),'provenance':'Uploaded pytest process; a malicious project can falsify this artifact.'}
        return {'name':'Existing pytest execution','status':'blocked' if result['termination'] or result['returncode']==5 else ('passed' if result['returncode']==0 else 'failed'),'actual':result,'duration_ms':result['duration_ms'],'evidence':['Temporary working copy; reduced environment; host interpreter; no dependency installation. Network and filesystem access are NOT sandboxed. Coverage includes the measured project tree, potentially including tests.'],'recommendation':'Use only trusted projects. Missing dependencies must be reviewed and installed manually into a dedicated environment.'}
