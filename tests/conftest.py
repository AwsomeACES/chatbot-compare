import os
import tempfile
import shutil
_runtime=tempfile.mkdtemp(prefix='studio-tests-')
os.environ['STUDIO_RUNTIME']=_runtime
def pytest_sessionfinish(session,exitstatus):
    shutil.rmtree(_runtime,ignore_errors=True)
