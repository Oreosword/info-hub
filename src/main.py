import asyncio
import os
import sys
import webbrowser

os.environ.setdefault("NO_PROXY", "*")
os.environ.setdefault("no_proxy", "*")

# Support PyInstaller bundled path
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from starlette.types import Scope, Receive, Send

from app_info import APP_DESCRIPTION, APP_NAME, APP_VERSION
import database as db
import config
from scheduler import schedule_all, start as scheduler_start, shutdown as scheduler_shutdown
from routers import api, sse

app = FastAPI(title=APP_NAME, description=APP_DESCRIPTION, version=APP_VERSION)

# Include routers
app.include_router(api.router, prefix="/api")
app.include_router(sse.router, prefix="/api")

# Static files with no-cache headers
static_dir = os.path.join(BASE_DIR, "static")
exports_dir = db.EXPORT_ROOT
exports_dir.mkdir(parents=True, exist_ok=True)


class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> None:
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response


app.mount("/static", NoCacheStaticFiles(directory=static_dir), name="static")
app.mount("/exports", NoCacheStaticFiles(directory=str(exports_dir.parent)), name="exports")


@app.get("/")
async def root():
    response = FileResponse(os.path.join(static_dir, "index.html"))
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response


@app.get("/health")
async def health():
    return {"status": "ok", "service": "Info Hub", "version": APP_VERSION}


async def _initial_fetch():
    await asyncio.sleep(3)
    from scheduler import run_fetch
    for src in db.get_sources(enabled_only=True):
        try:
            await run_fetch(src)
        except Exception as e:
            print(f"[startup] Initial fetch failed for {src.name}: {e}")


@app.on_event("startup")
async def on_startup():
    db.init_db()
    config.ensure_defaults()
    schedule_all()
    scheduler_start()
    if os.environ.get("INFO_HUB_SKIP_INITIAL_FETCH") != "1":
        asyncio.create_task(_initial_fetch())
    url = "http://127.0.0.1:8000"
    print(f"[startup] AI Hub ready at {url}")
    if getattr(sys, "frozen", False) or os.environ.get("INFO_HUB_OPEN_BROWSER") == "1":
        try:
            webbrowser.open(url)
            print("[startup] Browser opened")
        except Exception:
            pass


@app.on_event("shutdown")
async def on_shutdown():
    scheduler_shutdown()


if __name__ == "__main__":
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=8000, reload=False))
    server.run()
