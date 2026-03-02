# WisevoiceAgent

A voice-powered customer support agent for [Wise](https://wise.com) that answers questions from the **"Where is my money?"** FAQ section. It supports real-time voice conversations through a browser-based interface with two interchangeable backends — a cloud-hosted ElevenLabs solution and a fully local open-source stack.

## Features

- Real-time voice conversations via browser (WebSocket + Web Audio API)
- Workflow-driven responses defined in JSON — no hardcoded behavior
- Tool-calling support: the LLM selects the right workflow scenario based on user intent
- Handles transfer status, arrival times, delays, proof of payment, and banking references
- Graceful deflection to human agents for out-of-scope questions

## Architecture

```
Browser (Mic/Speaker)
        │
        ▼
   WebSocket Server
        │
        ├── ElevenLabs (Cloud)         ├── Pipecat (Local)
        │   Node.js + Express          │   Python + FastAPI
        │   ElevenLabs Convai API      │   Whisper STT (Docker)
        │                              │   Ollama LLM (Qwen2.5)
        │                              │   Kokoro TTS (Docker)
        ▼                              ▼
   Audio + Transcripts returned to browser
```

Both backends share the same browser frontend and workflow configuration.

## Project Structure

```
├── elevenlabs/              # Cloud-based implementation (Node.js)
│   ├── agent.js             # Express + WebSocket server
│   ├── workflow.js          # Workflow state management
│   └── public/index.html    # Web UI
├── pipecatIntegration/      # Local implementation (Python)
│   ├── agent.py             # Pipecat voice pipeline
│   ├── server.py            # FastAPI + WebSocket server
│   ├── workflow.py          # Workflow state management
│   ├── stt.py               # Whisper STT integration
│   ├── tts.py               # Kokoro TTS integration
│   ├── serializer.py        # Audio frame serialization
│   ├── runmodel.sh          # Docker startup for STT/TTS
│   └── models/              # Whisper & Kokoro Docker setup
├── prompt/
│   ├── system.md            # Agent system prompt
│   ├── workflows.md         # Workflow documentation
│   └── workflow.json        # Workflow definitions (5 scenarios)
├── .env                     # API keys & config
└── package.json
```

## Workflows

The agent handles these scenarios, defined in `prompt/workflow.json`:

| Scenario | Description |
|----------|-------------|
| **checkTransferStatus** | Guide users to check transfer status in their Wise account |
| **transferArrivalTime** | Explain expected arrival timelines |
| **transferCompleteNotArrived** | Handle "marked complete but not received" cases |
| **transferDelayed** | Explain common delay reasons and next steps |
| **proofOfPayment** | Explain proof of payment requirements and formats |
| **bankingPartnerReference** | Explain reference numbers for tracking |


## Preview 

[Preview](./assests/preview.png)

## Getting Started

### Option 1: ElevenLabs (Cloud)

**Prerequisites:** Node.js, ElevenLabs API key & Agent ID

```bash
# Install dependencies
npm install

# Configure environment
cp .env.example .env
# Set ELEVENLABS_API_KEY and ELEVENLABS_AGENT_ID in .env

# Start server
npm start
```

Open `http://localhost:8080` in your browser.

### Option 2: Pipecat (Local)

**Prerequisites:** Python 3.12+, Docker, Ollama

```bash
cd pipecatIntegration

# Install Python dependencies
pip install -e .

# Pull the LLM model
ollama pull qwen2.5:0.5b

# Start Whisper (STT) and Kokoro (TTS) containers
bash runmodel.sh

# Start the server
python server.py
```

Open `http://localhost:8000` in your browser.

See [models/Whisper/README.md](pipecatIntegration/models/Whisper/README.md) and [models/Kokoro/README.md](pipecatIntegration/models/Kokoro/README.md) for Docker build instructions.

## Tech Stack

| Component | Cloud (ElevenLabs) | Local (Pipecat) |
|-----------|--------------------|-----------------|
| **Backend** | Node.js, Express | Python, FastAPI |
| **Voice Pipeline** | ElevenLabs Convai API | Pipecat framework |
| **STT** | ElevenLabs (hosted) | Whisper (Docker) |
| **TTS** | ElevenLabs (hosted) | Kokoro (Docker) |
| **LLM** | OpenAI (via ElevenLabs) | Qwen2.5 (via Ollama) |
| **Frontend** | HTML5, Web Audio API | HTML5, Web Audio API |
| **Transport** | WebSocket | WebSocket |

## How It Works

1. User clicks **Start** in the browser and grants microphone access
2. Audio is captured at 16kHz and streamed to the server via WebSocket
3. Speech is transcribed to text (STT)
4. The LLM processes the text using the system prompt and workflow context
5. The LLM calls the `chooseScenario` tool to select the appropriate workflow
6. The response is converted to speech (TTS) and streamed back to the browser
7. Transcripts are displayed in real-time in the UI
