import json
from typing import AsyncGenerator, Optional

from loguru import logger

from pipecat.frames.frames import (
    CancelFrame,
    EndFrame,
    ErrorFrame,
    Frame,
    StartFrame,
    TTSAudioRawFrame,
    TTSStartedFrame,
    TTSStoppedFrame,
)
from pipecat.services.tts_service import InterruptibleTTSService

try:
    from websockets.asyncio.client import connect as websocket_connect
    from websockets.protocol import State
except ImportError:
    from websockets import connect as websocket_connect, State


class KokoroWebSocketTTS(InterruptibleTTSService):
    """
    TTS service that streams audio from a Kokoro WebSocket server.

    Protocol:
      - Send: { "text": "..." }
      - Receive: raw PCM bytes, followed by "END" (bytes or str) to signal completion.
    """

    def __init__(
        self,
        *,
        ws_url: str = "ws://localhost:8880/ws",
        sample_rate: int = 24000,
        **kwargs,
    ):
        super().__init__(
            push_stop_frames=True,
            pause_frame_processing=True,
            sample_rate=sample_rate,
            **kwargs,
        )
        self._ws_url = ws_url
        self._receive_task = None

        self._context_id: Optional[str] = None

    def can_generate_metrics(self) -> bool:
        return True

    async def start(self, frame: StartFrame):
        await super().start(frame)
        await self._connect()

    async def stop(self, frame: EndFrame):
        await super().stop(frame)
        await self._disconnect()

    async def cancel(self, frame: CancelFrame):
        await super().cancel(frame)
        await self._disconnect()

    async def _connect(self):
        await super()._connect()
        await self._connect_websocket()
        if self._websocket and not self._receive_task:
            self._receive_task = self.create_task(
                self._receive_task_handler(self._report_error)
            )

    async def _disconnect(self):
        await super()._disconnect()
        if self._receive_task:
            await self.cancel_task(self._receive_task)
            self._receive_task = None
        await self._disconnect_websocket()

    async def _connect_websocket(self):
        try:
            if self._websocket and self._websocket.state is State.OPEN:
                return
            logger.info(f"Connecting to Kokoro TTS at {self._ws_url}")
            self._websocket = await websocket_connect(self._ws_url)
            logger.info("Connected to Kokoro TTS")
            await self._call_event_handler("on_connected")
        except Exception as e:
            logger.error(f"Kokoro TTS connection failed: {e}")
            self._websocket = None
            await self._call_event_handler("on_connection_error", str(e))

    async def _disconnect_websocket(self):
        try:
            await self.stop_all_metrics()
            if self._websocket:
                logger.info("Disconnecting from Kokoro TTS")
                await self._websocket.close()
        except Exception as e:
            logger.error(f"Error disconnecting from Kokoro TTS: {e}")
        finally:
            self._context_id = None
            self._websocket = None
            await self._call_event_handler("on_disconnected")

    def _get_websocket(self):
        if self._websocket:
            return self._websocket
        raise Exception("Kokoro WebSocket not connected")

    async def _receive_messages(self):
        async for data in self._get_websocket():
            if isinstance(data, bytes):
                if data.startswith(b"ERROR:"):
                    await self.push_frame(ErrorFrame(data.decode()))
                    return

                if data == b"END" or data.endswith(b"\x00END"):
                    await self.push_frame(TTSStoppedFrame(context_id=self._context_id))
                    continue
                await self.stop_ttfb_metrics()
                await self.push_frame(
                    TTSAudioRawFrame(
                        audio=data,
                        sample_rate=self.sample_rate,
                        num_channels=1,
                        context_id=self._context_id,
                    )
                )
            else:
                if data.startswith("ERROR:"):
                    await self.push_frame(ErrorFrame(data))
                    return  # actual server error — bail out
                if data.strip() == "END":
                    await self.push_frame(TTSStoppedFrame(context_id=self._context_id))
                    continue  # stay connected for the next request

    async def run_tts(self, text: str, context_id: str) -> AsyncGenerator[Frame, None]:
        logger.debug(f"Kokoro TTS: [{text}]")

        try:
            if not self._websocket or self._websocket.state is State.CLOSED:
                await self._connect()

            try:
                await self.start_ttfb_metrics()
                self._context_id = context_id
                yield TTSStartedFrame(context_id=context_id)
                await self._get_websocket().send(json.dumps({"text": text}))
                await self.start_tts_usage_metrics(text)
            except Exception as e:
                yield ErrorFrame(error=f"Kokoro TTS error: {e}")
                yield TTSStoppedFrame(context_id=context_id)
                await self._disconnect()
                await self._connect()
                return

            yield None

        except Exception as e:
            yield ErrorFrame(error=f"Kokoro TTS error: {e}")
