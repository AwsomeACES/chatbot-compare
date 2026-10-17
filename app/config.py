import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")
RUNTIME = Path(os.getenv("STUDIO_RUNTIME", str(ROOT / "runtime")))
for folder in ("uploads", "extracted", "reports", "logs", "work"):
    (RUNTIME / folder).mkdir(parents=True, exist_ok=True)
MAX_UPLOAD = int(os.getenv("MAX_UPLOAD_MB", "1024")) * 1024 * 1024
TIMEOUT = int(os.getenv("TEST_TIMEOUT_SECONDS", "60"))
MAX_CASES = int(os.getenv("MAX_TEST_CASES", "200"))
