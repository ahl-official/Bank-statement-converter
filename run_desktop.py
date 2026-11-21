"""
Tally Smart Connector - 1-Click Desktop Launcher
Starts the local FastAPI backend, serves the modern React/Tailwind frontend,
and opens your default browser at http://127.0.0.1:8000.
"""

import sys
import time
import threading
import webbrowser
import uvicorn

def open_browser(url: str):
    time.sleep(1.2)
    print(f"\nOpening web browser at {url}...")
    webbrowser.open(url)

if __name__ == "__main__":
    url = "http://127.0.0.1:8000"
    print("=" * 65)
    print(" Bank Statement Converter")
    print(f" Local URL: {url}")
    print(" Offline & Private (Data stays on your machine)")
    print("=" * 65)

    threading.Thread(target=open_browser, args=(url,), daemon=True).start()

    # Run Uvicorn server on localhost
    uvicorn.run("server:app", host="127.0.0.1", port=8000, log_level="info", reload=False)

