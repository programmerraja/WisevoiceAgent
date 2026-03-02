import json

from loguru import logger

from pipecat.adapters.schemas.function_schema import FunctionSchema
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.frames.frames import (
    Frame,
    LLMFullResponseEndFrame,
    LLMTextFrame,
    TranscriptionFrame,
    OutputTransportMessageFrame,
)
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.task import PipelineParams, PipelineTask
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.transports.websocket.fastapi import (
    FastAPIWebsocketParams,
    FastAPIWebsocketTransport,
)

from serializer import ElevenLabsFrameSerializer
from stt import WhisperWebSocketSTT
from tts import KokoroWebSocketTTS
from workflow import BaseWorkflow

SYSTEM_PROMPT = open("../prompt/system.md").read()

with open("../prompt/workflow.json") as f:
    WORKFLOW_CONFIG = json.load(f)

SAMPLE_RATE = 16000

choose_scenario_function = FunctionSchema(
    name="chooseScenario",
    description="Use when you identify what the caller needs",
    properties={
        "scenarioName": {
            "type": "string",
            "description": "a scenario name given in prompt",
        },
    },
    required=["scenarioName"],
)

tools = ToolsSchema(standard_tools=[choose_scenario_function])


class TranscriptForwarder(FrameProcessor):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._llm_response_buffer = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, TranscriptionFrame):
            await self.push_frame(
                OutputTransportMessageFrame(
                    message={
                        "type": "user_transcript",
                        "text": frame.text,
                    }
                )
            )

        elif isinstance(frame, LLMTextFrame):
            self._llm_response_buffer += frame.text

        elif isinstance(frame, LLMFullResponseEndFrame):
            if self._llm_response_buffer:
                await self.push_frame(
                    OutputTransportMessageFrame(
                        message={
                            "type": "agent_response",
                            "text": self._llm_response_buffer,
                        }
                    )
                )
                self._llm_response_buffer = ""

        await self.push_frame(frame, direction)


class VoiceAgent:
    def __init__(self, websocket):
        self.websocket = websocket
        self.workflow = BaseWorkflow(WORKFLOW_CONFIG)
        self.system_prompt = SYSTEM_PROMPT.replace(
            "{{scenarios}}", self.workflow.get_workflows()
        )

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
            model="qwen2.5:0.5b",
            base_url="http://localhost:11434/v1",
            api_key="not-needed",
        )

        tts = KokoroWebSocketTTS(
            ws_url="ws://localhost:8880/ws",
            sample_rate=24000,
        )

        context = OpenAILLMContext(
            messages=[{"role": "system", "content": self.system_prompt}],
            tools=tools,
        )
        context_aggregator = llm.create_context_aggregator(context)

        async def on_choose_scenario(params):
            logger.info("chooseScenario called with:", params.arguments)
            scenario_name = params.arguments.get("scenarioName", "")
            result = self.workflow.choose_scenario(scenario_name)
            await params.result_callback(result)

        llm.register_function("chooseScenario", on_choose_scenario)

        transcript_forwarder = TranscriptForwarder()

        pipeline = Pipeline(
            [
                transport.input(),
                stt,
                context_aggregator.user(),
                llm,
                transcript_forwarder,
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
                [OutputTransportMessageFrame(message={"type": "connected"})]
            )

        @transport.event_handler("on_client_disconnected")
        async def on_disconnected(t, client):
            logger.info("Client disconnected")
            await task.cancel()

        runner = PipelineRunner(handle_sigint=False)
        await runner.run(task)
