const express = require("express");
const { WebSocketServer, WebSocket } = require("ws");
const { createServer } = require("http");
const dotenv = require("dotenv");
const axios = require("axios");
const path = require("path");
const workflow = require("../prompt/workflow.json");
const { BaseWorkflow } = require("./workflow");

dotenv.config();

const app = express();
const server = createServer(app);
const PORT = process.env.PORT || 8080;

app.use(express.static(path.join(__dirname, "public")));

const baseWorkflow = new BaseWorkflow(workflow);

const wss = new WebSocketServer({ noServer: true });

server.on("upgrade", (req, socket, head) => {
  const pathname = new URL(req.url, `http://${req.headers.host}`).pathname;
  if (pathname === "/ws") {
    wss.handleUpgrade(req, socket, head, (ws) => {
      wss.emit("connection", ws);
    });
  } else {
    socket.destroy();
  }
});

wss.on("connection", async (browserWs) => {
  console.log("Browser connected");

  let elevenWs = null;

  try {
    const { data } = await axios.get(
      `https://api.elevenlabs.io/v1/convai/conversation/get_signed_url?agent_id=${process.env.ELEVENLABS_AGENT_ID}`,
      { headers: { "xi-api-key": process.env.ELEVENLABS_API_KEY } },
    );

    elevenWs = new WebSocket(data.signed_url);

    elevenWs.on("open", () => {
      console.log("Connected to ElevenLabs");
      browserWs.send(JSON.stringify({ type: "connected" }));

      elevenWs.send(
        JSON.stringify({
          type: "conversation_initiation_client_data",
          dynamic_variables: {
            scenarios: baseWorkflow.getWorkflows(),
          },
        }),
      );
    });

    elevenWs.on("message", (data) => {
      const msg = JSON.parse(data);
      console.log("Received from ElevenLabs:", msg.type);
      switch (msg.type) {
        case "audio":
          const audio =
            msg.audio_event?.audio_base_64 || msg.audio?.chunk || null;
          if (audio) {
            browserWs.send(JSON.stringify({ type: "audio", audio }));
          }
          break;

        case "interruption":
          browserWs.send(JSON.stringify({ type: "interruption" }));
          break;

        case "ping":
          if (msg.ping_event?.event_id) {
            elevenWs.send(
              JSON.stringify({
                type: "pong",
                event_id: msg.ping_event.event_id,
              }),
            );
          }
          break;

        case "user_transcript":
          browserWs.send(
            JSON.stringify({
              type: "user_transcript",
              text: msg.user_transcription_event?.user_transcript,
            }),
          );
          break;

        case "agent_response":
          browserWs.send(
            JSON.stringify({
              type: "agent_response",
              text: msg.agent_response_event?.agent_response,
            }),
          );
          break;

        case "client_tool_call":
          // client_tool_call: {tool_name: 'chooseScenario', tool_call_id: 'chooseScenario_3d4181da2f2c45e3a4f2d2aa2cad4b4a', parameters: {…}, event_id: 31, expects_response: true}
          // {client_tool_call:{tool_name:"",tool_call_id:"",parameters:{}}}
          const clientToolCall = msg.client_tool_call;
          if (baseWorkflow[clientToolCall.tool_name]) {
            const prompt = baseWorkflow[clientToolCall.tool_name](clientToolCall.parameters);
            elevenWs.send(
              JSON.stringify({
                type: "client_tool_result",
                is_error:false,
                tool_call_id: clientToolCall.tool_call_id,
                result: prompt,
              }),
            );
          } else {
            elevenWs.send(
              JSON.stringify({
                type: "client_tool_result",
                is_error:true,
                tool_call_id: clientToolCall.tool_call_id,
                result: `${clientToolCall.tool_name} not found in workflow. Please check the tool name and try again.`,
              }),
            );
          }
          break;
        default:
          console.log("ElevenLabs:", msg.type);
      }
    });

    elevenWs.on("error", (err) =>
      console.error("ElevenLabs WebSocket error:", err),
    );

    elevenWs.on("close", () => {
      console.log("ElevenLabs disconnected");
      if (browserWs.readyState === WebSocket.OPEN) {
        browserWs.send(JSON.stringify({ type: "disconnected" }));
      }
    });
  } catch (err) {
    console.error("Failed to connect to ElevenLabs:", err.message);
    browserWs.send(
      JSON.stringify({ type: "error", message: "Failed to connect to agent" }),
    );
    browserWs.close();
    return;
  }

  browserWs.on("message", (data) => {
    const msg = JSON.parse(data);

    if (msg.type === "audio" && elevenWs?.readyState === WebSocket.OPEN) {
      elevenWs.send(JSON.stringify({ user_audio_chunk: msg.audio }));
    }
  });

  browserWs.on("close", () => {
    console.log("Browser disconnected");
    if (elevenWs?.readyState === WebSocket.OPEN) elevenWs.close();
  });

  browserWs.on("error", (err) =>
    console.error("Browser WebSocket error:", err),
  );
});

server.listen(PORT, () => {
  console.log(`Server running on http://localhost:${PORT}`);
});
