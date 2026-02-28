import os
import traceback
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from agent import VoiceAgent

load_dotenv()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_DIR = Path(__file__).parent.parent / "pipecatIntegration" / "public"
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
async def root():
    return FileResponse(str(FRONTEND_DIR / "index.html"))


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    print("Browser connected to local pipeline")

    try:
        agent = VoiceAgent(websocket)
        await agent.run()
    except Exception as e:
        print(f"Error in pipeline: {e}")
        print(traceback.format_exc())


if __name__ == "__main__":
    port = int(os.getenv("PYTHON_PORT", "8000"))
    print(f"Local pipeline server running on http://localhost:{port}")
    print(f"ElevenLabs server runs separately on port 8080")
    uvicorn.run(app, host="0.0.0.0", port=port)
