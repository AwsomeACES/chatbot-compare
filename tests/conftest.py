import os
import shutil
import tempfile

_runtime = tempfile.mkdtemp(prefix="studio-tests-")
os.environ["STUDIO_RUNTIME"] = _runtime


def pytest_sessionfinish(session, exitstatus):
    from app import database

    database.close()
    shutil.rmtree(_runtime, ignore_errors=True)
