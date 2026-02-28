import asyncio
from typing import AsyncGenerator, Optional

import websockets
from websockets.connection import State

from loguru import logger

from pipecat.audio.resamplers.soxr_resampler import SOXRAudioResampler
from pipecat.frames.frames import ErrorFrame, Frame, TranscriptionFrame
from pipecat.services.stt_service import SegmentedSTTService
from pipecat.transcriptions.language import Language
from pipecat.utils.time import time_now_iso8601


class WhisperWebSocketSTT(SegmentedSTTService):
    def __init__(
        self,
        *,
        ws_url: str = "ws://localhost:9800/ws",
        language: Language = Language.EN,
        sample_rate: int = 16000,
        no_speech_prob: float = 0.4,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._ws_url = ws_url
        self._language = language
        self._sample_rate = sample_rate
        self._no_speech_prob = no_speech_prob
        self._ws: Optional[websockets.WebSocketClientProtocol] = None

        asyncio.get_event_loop().create_task(self._connect())

    async def _connect(self):
        try:
            logger.info(f"Connecting to Whisper STT at {self._ws_url}")
            self._ws = await websockets.connect(self._ws_url)
            logger.info("Connected to Whisper STT")
        except Exception as e:
            logger.error(f"Failed to connect to Whisper STT: {e}")
            self._ws = None

    async def close(self):
        if self._ws:
            await self._ws.close()

    def can_generate_metrics(self) -> bool:
        return True

    def _is_ws_closed(self) -> bool:
        if self._ws is None:
            return True
        if hasattr(self._ws, "state"):

            return self._ws.state != State.OPEN
        return getattr(self._ws, "closed", True)

    async def run_stt(self, audio: bytes) -> AsyncGenerator[Frame, None]:
        """Send audio to Whisper WS server, yield TranscriptionFrame."""
        if self._is_ws_closed():
            logger.warning("Whisper WS not connected, reconnecting...")
            await self._connect()
            if self._is_ws_closed():
                yield ErrorFrame("Whisper STT connection failed")
                return

        await self.start_processing_metrics()
        await self.start_ttfb_metrics()

        try:
            # Resample to 24kHz which Whisper expects
            resampled = await SOXRAudioResampler().resample(
                audio, self._sample_rate, 24000
            )
            await self._ws.send(resampled)

            result = await self._ws.recv()

            if isinstance(result, bytes):
                result = result.decode("utf-8")

            if result.startswith("ERROR:"):
                yield ErrorFrame(result)
                return

            text = result.strip()
            if text:
                logger.debug(f"Whisper transcript: [{text}]")
                yield TranscriptionFrame(text, "", time_now_iso8601(), self._language)

        except Exception as e:
            logger.exception(f"Whisper STT error: {e}")
            yield ErrorFrame(f"Whisper STT failed: {e}")

        await self.stop_ttfb_metrics()
        await self.stop_processing_metrics()
