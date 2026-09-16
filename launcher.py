import asyncio
import os
import sys
import importlib.util

# Add .local to path for pip-installed packages
sys.path.append(os.path.expanduser("~/.local/lib/python3.11/site-packages"))

async def run_dashboard():
    import uvicorn
    from main import app
    config = uvicorn.Config(app, host="0.0.0.0", port=int(os.getenv("PORT", 3001)))
    server = uvicorn.Server(config)
    await server.serve()

async def run_bot():
    spec = importlib.util.spec_from_file_location("codex", "/home/container/CodeX.py")
    codex_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(codex_module)

async def main():
    await asyncio.gather(run_dashboard(), run_bot())

if __name__ == "__main__":
    asyncio.run(main())
