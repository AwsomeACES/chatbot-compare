import zipfile
from pathlib import Path

root = Path(__file__).resolve().parent.parent
with zipfile.ZipFile(root / "sample-chatbot.zip", "w", zipfile.ZIP_DEFLATED) as z:
    for p in (root / "sample_project").glob("*"):
        if p.is_file():
            z.write(p, "sample-chatbot/" + p.name)
print("Created sample-chatbot.zip")
