"""Open the Studio after health succeeds, without assuming an OS browser command."""

import os
import time
import urllib.request
import webbrowser

url = f"http://127.0.0.1:{os.getenv('PORT', '2708')}"
for _ in range(60):
    try:
        with urllib.request.urlopen(url + "/api/health", timeout=1) as response:
            if response.status == 200:
                webbrowser.open(url)
                break
    except OSError:
        time.sleep(1)
