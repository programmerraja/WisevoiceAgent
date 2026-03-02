"""
NeuTTS-Air WebSocket + REST Server — CPU-optimized.
Model: NeuTTS-Air Q8 GGUF (0.5B, Apache 2.0) with NeuCodec.
Audio: 24kHz mono PCM16 via WebSocket, WAV via REST.
Supports streaming inference via llama-cpp-python GGUF backend.
"""

import os, json, time, asyncio, io
import numpy as np
import torch
import soundfile as sf
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
from loguru import logger
import uvicorn

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, UploadFile, File
from fastapi.responses import HTMLResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from neutts import NeuTTS


# ───────────── Config ─────────────

BACKBONE = os.environ.get("BACKBONE", "neuphonic/neutts-air-q8-gguf")
CODEC = os.environ.get("CODEC", "neuphonic/neucodec-onnx-decoder")
WORKERS = int(os.environ.get("TTS_WORKERS", "1"))
MAX_TEXT_LEN = int(os.environ.get("MAX_TEXT_LEN", "2000"))
SAMPLES_DIR = os.environ.get("SAMPLES_DIR", "/app/samples")


# ───────────── Engine ─────────────


class NeuTTSEngine:
    def __init__(self):
        self.tts: Optional[NeuTTS] = None
        self.executor = ThreadPoolExecutor(max_workers=WORKERS)
        self.sample_rate = 24000
        # Cache for pre-encoded reference voices
        self.ref_cache: dict[str, torch.Tensor] = {}

    def load(self):
        logger.info(f"Loading backbone={BACKBONE} codec={CODEC}")
        self.tts = NeuTTS(
            backbone_repo=BACKBONE,
            backbone_device="cpu",
            codec_repo=CODEC,
            codec_device="cpu",
        )
        self.sample_rate = self.tts.sample_rate
        logger.info(f"Model loaded. sample_rate={self.sample_rate}")

        # Pre-load bundled reference voices
        self._load_bundled_refs()

    def _load_bundled_refs(self):
        if not os.path.isdir(SAMPLES_DIR):
            return
        for f in os.listdir(SAMPLES_DIR):
            if f.endswith(".pt"):
                name = f.replace(".pt", "")
                path = os.path.join(SAMPLES_DIR, f)
                try:
                    self.ref_cache[name] = torch.load(path, weights_only=True)
                    logger.info(f"Loaded ref voice: {name}")
                except Exception as e:
                    logger.warning(f"Failed to load {path}: {e}")

    def _get_ref_codes(self, voice: str) -> Optional[torch.Tensor]:
        if voice in self.ref_cache:
            return self.ref_cache[voice]
        # Try loading .pt file from samples dir
        pt_path = os.path.join(SAMPLES_DIR, f"{voice}.pt")
        if os.path.exists(pt_path):
            codes = torch.load(pt_path, weights_only=True)
            self.ref_cache[voice] = codes
            return codes
        return None

    def _get_ref_text(self, voice: str) -> str:
        txt_path = os.path.join(SAMPLES_DIR, f"{voice}.txt")
        if os.path.exists(txt_path):
            return open(txt_path, "r").read().strip()
        return ""

    def synthesize_sync(self, text: str, voice: str = "jo") -> np.ndarray:
        """Blocking full synthesis — voice clones from a reference."""
        ref_codes = self._get_ref_codes(voice)
        ref_text = self._get_ref_text(voice)
        wav = self.tts.infer(text, ref_codes, ref_text)
        return wav

    def stream_sync(self, text: str, voice: str = "jo"):
        """Blocking streaming synthesis — yields numpy chunks."""
        ref_codes = self._get_ref_codes(voice)
        ref_text = self._get_ref_text(voice)
        for chunk in self.tts.infer_stream(text, ref_codes, ref_text):
            yield chunk

    async def synthesize(self, text: str, voice: str = "jo") -> np.ndarray:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self.executor, self.synthesize_sync, text, voice
        )

    def shutdown(self):
        self.executor.shutdown(wait=False)


engine = NeuTTSEngine()


# ───────────── Lifespan ─────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting — loading NeuTTS-Air...")
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, engine.load)

    # Warmup
    logger.info("Warming up...")
    try:
        await engine.synthesize("Hello.", "jo")
        logger.info("Warmup done.")
    except Exception as e:
        logger.warning(f"Warmup failed: {e}")

    logger.info("Server ready.")
    yield
    engine.shutdown()


app = FastAPI(title="NeuTTS-Air Server", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


# ───────────── REST ─────────────


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "model": BACKBONE,
        "sample_rate": engine.sample_rate,
        "voices": list(engine.ref_cache.keys()),
    }


@app.get("/voices")
async def list_voices():
    voices = {}
    for name in engine.ref_cache:
        txt = engine._get_ref_text(name)
        voices[name] = {"ref_text": txt[:80] + "..." if len(txt) > 80 else txt}
    return {"voices": voices, "note": "Upload custom voice via POST /voices/upload"}


@app.get("/tts")
async def tts_rest(
    text: str = Query(..., max_length=MAX_TEXT_LEN),
    voice: str = Query("jo"),
):
    """Returns a WAV file."""
    try:
        wav = await engine.synthesize(text, voice)
        buf = io.BytesIO()
        sf.write(buf, wav, engine.sample_rate, format="WAV", subtype="PCM_16")
        buf.seek(0)
        return Response(
            content=buf.read(),
            media_type="audio/wav",
            headers={"Content-Disposition": 'inline; filename="neutts.wav"'},
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/voices/upload")
async def upload_voice(
    name: str = Query(...),
    ref_text: str = Query(...),
    audio: UploadFile = File(...),
):
    """Upload a custom reference voice (WAV, 3-15s)."""
    try:
        os.makedirs(SAMPLES_DIR, exist_ok=True)
        wav_path = os.path.join(SAMPLES_DIR, f"{name}.wav")
        txt_path = os.path.join(SAMPLES_DIR, f"{name}.txt")
        pt_path = os.path.join(SAMPLES_DIR, f"{name}.pt")

        content = await audio.read()
        with open(wav_path, "wb") as f:
            f.write(content)
        with open(txt_path, "w") as f:
            f.write(ref_text)

        # Encode reference
        loop = asyncio.get_running_loop()
        ref_codes = await loop.run_in_executor(
            None, engine.tts.encode_reference, wav_path
        )
        torch.save(ref_codes, pt_path)
        engine.ref_cache[name] = ref_codes

        return {"status": "ok", "voice": name}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ───────────── WebSocket ─────────────


@app.websocket("/ws")
async def websocket_tts(ws: WebSocket):
    await ws.accept()
    client = ws.client.host if ws.client else "unknown"
    logger.info(f"WS connected: {client}")

    try:
        while True:
            raw = await ws.receive_text()

            try:
                data = json.loads(raw)
                text = data.get("text", "").strip()
                voice = data.get("voice", "jo")
                streaming = data.get("stream", True)
            except (json.JSONDecodeError, TypeError):
                text = raw.strip()
                voice = "jo"
                streaming = True

            if not text:
                await ws.send_text(json.dumps({"error": "empty text"}))
                continue

            if len(text) > MAX_TEXT_LEN:
                await ws.send_text(
                    json.dumps({"error": f"text too long (max {MAX_TEXT_LEN})"})
                )
                continue

            t0 = time.perf_counter()
            logger.info(f"Generating: voice={voice} stream={streaming} len={len(text)}")

            try:
                if streaming:
                    # Stream chunks from worker thread via queue
                    queue = asyncio.Queue()
                    loop = asyncio.get_running_loop()

                    def _produce():
                        try:
                            for chunk in engine.stream_sync(text, voice):
                                pcm = (chunk * 32767).astype(np.int16).tobytes()
                                loop.call_soon_threadsafe(queue.put_nowait, pcm)
                        except Exception as e:
                            loop.call_soon_threadsafe(queue.put_nowait, e)
                        finally:
                            loop.call_soon_threadsafe(queue.put_nowait, None)

                    engine.executor.submit(_produce)

                    chunk_count = 0
                    total_samples = 0
                    while True:
                        item = await queue.get()
                        if item is None:
                            break
                        if isinstance(item, Exception):
                            await ws.send_text(json.dumps({"error": str(item)}))
                            break
                        await ws.send_bytes(item)
                        chunk_count += 1
                        total_samples += len(item) // 2

                else:
                    # Non-streaming: full generation then send
                    wav = await engine.synthesize(text, voice)
                    pcm = (wav * 32767).astype(np.int16).tobytes()
                    CHUNK = 8192
                    chunk_count = 0
                    total_samples = len(wav)
                    for i in range(0, len(pcm), CHUNK):
                        await ws.send_bytes(pcm[i : i + CHUNK])
                        chunk_count += 1

                await ws.send_bytes(b"END")

                elapsed = time.perf_counter() - t0
                audio_dur = total_samples / engine.sample_rate
                rtf = elapsed / audio_dur if audio_dur > 0 else 0
                logger.info(
                    f"Done: {chunk_count} chunks, "
                    f"{audio_dur:.1f}s audio in {elapsed:.2f}s (RTF={rtf:.3f})"
                )

            except Exception as e:
                logger.error(f"TTS error: {e}")
                await ws.send_text(json.dumps({"error": str(e)}))

    except WebSocketDisconnect:
        logger.info(f"WS disconnected: {client}")
    except Exception as e:
        logger.error(f"WS handler error: {e}")


# ───────────── Web UI ─────────────


@app.get("/", response_class=HTMLResponse)
async def web_ui():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "client.html")
    if os.path.exists(path):
        return HTMLResponse(open(path).read())
    return HTMLResponse("<h1>NeuTTS-Air</h1>")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8880"))
    uvicorn.run("server:app", host="0.0.0.0", port=port, log_level="info")
