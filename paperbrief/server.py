"""Start the app on 127.0.0.1 and open the default browser. Entry point for run.bat / run.sh."""
import threading
import webbrowser

import uvicorn
from fastapi import FastAPI

from paperbrief.app import create_app
from paperbrief.config import HOST, Settings


def make_config(app: FastAPI, settings: Settings) -> uvicorn.Config:
    return uvicorn.Config(app, host=HOST, port=settings.port, log_level="info")


def main() -> None:
    settings = Settings.load()
    server = uvicorn.Server(make_config(create_app(settings), settings))
    url = f"http://{HOST}:{settings.port}/"

    def open_when_ready() -> None:
        while not server.started and not server.should_exit:
            threading.Event().wait(0.1)
        if server.started:
            webbrowser.open(url)

    threading.Thread(target=open_when_ready, daemon=True).start()
    server.run()
