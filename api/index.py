import os
import sys

current_dir = os.path.dirname(os.path.abspath(__file__))
root_dir = os.path.dirname(current_dir)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)

from fastapi import Request
from server import app

@app.middleware("http")
async def fix_vercel_path(request: Request, call_next):
    # Restore original requested URL path if rewritten by Vercel
    for header in ("x-matched-path", "x-forwarded-uri", "x-vercel-matched-path", "x-invoke-path"):
        original_path = request.headers.get(header)
        if original_path and original_path != request.scope.get("path"):
            request.scope["path"] = original_path
            break
    return await call_next(request)
