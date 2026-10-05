import io, zipfile, time
from fastapi.testclient import TestClient
from app.main import app
H={'X-Studio-Request':'1'}
def z():
 b=io.BytesIO()
 with zipfile.ZipFile(b,'w') as f:f.writestr('main.py','def hello():\n return "hello"')
 return b.getvalue()
def test_health_upload_run_report():
 with TestClient(app) as c:
  assert c.get('/api/health').status_code==200
  p=c.post('/api/projects/upload',headers=H,files={'file':('x.zip',z(),'application/zip')}); assert p.status_code==201
  project=p.json(); run=c.post(f"/api/projects/{project['id']}/tests/run",headers=H,json={'categories':['static','functional']}).json()
  for _ in range(100):
   run=c.get('/api/runs/'+run['id']).json()
   if run['status'] not in ('queued','running'): break
   time.sleep(.03)
  assert run['status']=='completed'
  assert c.get('/api/runs/'+run['id']+'/report').status_code==200
  assert c.get('/api/runs/'+run['id']+'/report/download?format=html').status_code==200

def test_invalid_zip():
 with TestClient(app) as c: assert c.post('/api/projects/upload',headers=H,files={'file':('x.zip',b'bad')}).status_code==400
