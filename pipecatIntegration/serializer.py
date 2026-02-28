import base64
import json
from typing import Literal, Optional

from loguru import logger
from pydantic import BaseModel

from pipecat.audio.utils import create_default_resampler
from pipecat.frames.frames import (
    Frame,
    InputAudioRawFrame,
    LLMTextFrame,
    OutputAudioRawFrame,
    StartFrame,
    TranscriptionFrame,
    TransportMessageFrame,
    TransportMessageUrgentFrame,
)
from pipecat.serializers.base_serializer import FrameSerializer


class ElevenLabsFrameSerializer(FrameSerializer):
    """
    Converts between Pipecat frames and the ElevenLabs WebSocket protocol.
    Also accepts the browser's { type: "audio", audio: "..." } format.
    """

    class InputParams(BaseModel):
        sample_rate: int = 16000
        num_channels: int = 1
        audio_format: Literal["pcm", "ulaw"] = "pcm"

    def __init__(self, params: Optional[InputParams] = None):
        self._params = params or ElevenLabsFrameSerializer.InputParams()
        self._sample_rate = self._params.sample_rate
        self._num_channels = self._params.num_channels
        self._resampler = create_default_resampler()

    async def setup(self, frame: StartFrame):
        frame.audio_in_sample_rate = self._params.sample_rate
        self._sample_rate = self._params.sample_rate

    async def serialize(self, frame: Frame) -> str | bytes | None:

        if isinstance(frame, OutputAudioRawFrame):
            # Resample if TTS output rate differs from what the browser expects
            audio = frame.audio
            if frame.sample_rate != self._params.sample_rate:
                audio = await self._resampler.resample(
                    audio, frame.sample_rate, self._params.sample_rate
                )
            message = {
                "type": "audio",
                "audio_event": {
                    "audio_base_64": base64.b64encode(audio).decode("utf-8"),
                    "event_id": 1,
                },
            }
            return json.dumps(message)

        elif isinstance(frame, TranscriptionFrame):
            message = {
                "type": "user_transcript",
                "user_transcription_event": {"user_transcript": frame.text},
            }
            return json.dumps(message)

        elif isinstance(frame, LLMTextFrame):
            message = {
                "type": "agent_response",
                "agent_response_event": {"agent_response": frame.text},
            }
            return json.dumps(message)

        elif isinstance(frame, (TransportMessageFrame, TransportMessageUrgentFrame)):
            return json.dumps(frame.message)

        return None

    async def deserialize(self, data: str | bytes) -> Frame | None:
        """JSON string from the browser → Pipecat frame."""
        if isinstance(data, bytes):
            data = data.decode()

        try:
            message = json.loads(data)
        except Exception as e:
            logger.warning(f"Failed to parse message: {e}")
            return None

        if "user_audio_chunk" in message:
            audio_bytes = base64.b64decode(message["user_audio_chunk"])
            return InputAudioRawFrame(
                audio=audio_bytes,
                sample_rate=self._sample_rate,
                num_channels=self._num_channels,
            )

        if message.get("type") == "audio" and "audio" in message:
            audio_bytes = base64.b64decode(message["audio"])
            return InputAudioRawFrame(
                audio=audio_bytes,
                sample_rate=self._sample_rate,
                num_channels=self._num_channels,
            )

        return None
