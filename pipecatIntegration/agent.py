from loguru import logger

from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import TransportMessageUrgentFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from serializer import ElevenLabsFrameSerializer
from stt import WhisperWebSocketSTT
from tts import KokoroWebSocketTTS

SYSTEM_PROMPT = open("../prompt/system.md").read()

# Browser captures at 16kHz PCM — match this throughout
SAMPLE_RATE = 16000


class VoiceAgent:
    def __init__(self, websocket):
        self.websocket = websocket
        self.system_prompt = SYSTEM_PROMPT

    async def run(self):
        transport = FastAPIWebsocketTransport(
            websocket=self.websocket,
            params=FastAPIWebsocketParams(
                audio_in_enabled=True,
                audio_out_enabled=True,
                add_wav_header=False,
                vad_analyzer=SileroVADAnalyzer(sample_rate=SAMPLE_RATE),
                serializer=ElevenLabsFrameSerializer(
                    params=ElevenLabsFrameSerializer.InputParams(
                        sample_rate=SAMPLE_RATE,
                        audio_format="pcm",
                    )
                ),
            ),
        )

        stt = WhisperWebSocketSTT(
            ws_url="ws://localhost:9800/ws",
            sample_rate=SAMPLE_RATE,
        )

        llm = OpenAILLMService(
            model="smollm:latest",
            base_url="http://localhost:11434/v1",
            api_key="not-needed",
        )

        tts = KokoroWebSocketTTS(
            ws_url="ws://localhost:8880/ws",
            sample_rate=24000,
        )

        context = OpenAILLMContext(
            messages=[{"role": "system", "content": self.system_prompt}]
        )
        context_aggregator = llm.create_context_aggregator(context)

        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                context_aggregator.user(),
                llm,
                tts,
                transport.output(),
                context_aggregator.assistant(),
            ]
        )

        task = PipelineTask(
            pipeline,
            params=PipelineParams(allow_interruptions=True),
        )

        @transport.event_handler("on_client_connected")
        async def on_connected(t, client):
            logger.info("Client connected to local pipeline")
            await task.queue_frames(
                [TransportMessageUrgentFrame(message={"type": "connected"})]
            )

        @transport.event_handler("on_client_disconnected")
        async def on_disconnected(t, client):
            logger.info("Client disconnected")
            await task.cancel()

        runner = PipelineRunner(handle_sigint=False)
        await runner.run(task)
