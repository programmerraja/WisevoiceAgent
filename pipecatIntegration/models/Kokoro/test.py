import asyncio
import websockets
import json
import wave
import time
from typing import Optional


async def test_kokoro_websocket():
    """Test the Kokoro WebSocket server"""

    uri = "wss://8880-dep-01k14ndxtah61z42ymyr6p2v8b-d.cloudspaces.litng.ai/ws"

    try:
        async with websockets.connect(
            uri,
            extra_headers={
                "Authorization": "Bearer 72dc0bce-f2da-4585-a6df-6f1160980dc0"
            },
        ) as websocket:
            print("Connected to Kokoro WebSocket server")

            # Test 1: Simple text message
            print("\n=== Test 1: Simple text ===")
            text = "Hello, this is a test of the Kokoro text-to-speech system. "

            start_time = time.time()
            await websocket.send(text)

            # Collect audio data
            audio_chunks = []
            async for response in websocket:
                if isinstance(response, bytes):
                    if response.startswith(b"ERROR:"):
                        break
                    if response.endswith(b"END"):
                        break
                    audio_bytes = response
                else:
                    if response.startswith("ERROR:"):
                        break
                    if response.endswith("END"):
                        break

                    audio_bytes = response.encode("utf-8")
                if audio_bytes:
                    audio_chunks.append(audio_bytes)

            processing_time = time.time() - start_time
            total_bytes = sum(len(chunk) for chunk in audio_chunks)
            print(f"Received {len(audio_chunks)} audio chunks ({total_bytes} bytes)")
            print(f"Processing time: {processing_time:.3f} seconds")

            # Save audio to file
            if audio_chunks:
                with open("test_output_1.wav", "wb") as f:
                    # Write WAV header
                    f.write(
                        wave.struct.pack(
                            "<4sI4s4sIHHIIHH4sI",
                            b"RIFF",
                            36 + total_bytes,
                            b"WAVE",
                            b"fmt ",
                            16,
                            1,
                            1,
                            24000,
                            48000,
                            2,
                            16,
                            b"data",
                            total_bytes,
                        )
                    )
                    # Write audio data
                    for chunk in audio_chunks:
                        f.write(chunk)
                print("Saved audio to test_output_1.wav")

            # Test 2: JSON configuration
            # print("\n=== Test 2: JSON configuration ===")
            # config_message = {
            #     "text": "This is a test with custom configuration.",
            #     "config": {
            #         "voice": "af_bella",
            #         "speed": 1.2,
            #         "lang_code": "a",
            #         "volume_multiplier": 1.5,
            #     },
            # }

            # start_time = time.time()
            # await websocket.send(json.dumps(config_message))

            # # Collect audio data
            # audio_chunks = []
            # async for message in websocket:
            #     if message.startswith(b"ERROR"):
            #         print(f"Error: {message.decode()}")
            #         break
            #     audio_chunks.append(message)
            #     if len(audio_chunks) > 10:  # Limit chunks for demo
            #         break

            # processing_time = time.time() - start_time
            # total_bytes = sum(len(chunk) for chunk in audio_chunks)
            # print(f"Received {len(audio_chunks)} audio chunks ({total_bytes} bytes)")
            # print(f"Processing time: {processing_time:.3f} seconds")

            # # Save audio to file
            # if audio_chunks:
            #     with open("test_output_2.wav", "wb") as f:
            #         # Write WAV header
            #         f.write(
            #             wave.struct.pack(
            #                 "<4sI4s4sIHHIIHH4sI",
            #                 b"RIFF",
            #                 36 + total_bytes,
            #                 b"WAVE",
            #                 b"fmt ",
            #                 16,
            #                 1,
            #                 1,
            #                 24000,
            #                 48000,
            #                 2,
            #                 16,
            #                 b"data",
            #                 total_bytes,
            #             )
            #         )
            #         # Write audio data
            #         for chunk in audio_chunks:
            #             f.write(chunk)
            #     print("Saved audio to test_output_2.wav")

            print("\nTests completed successfully!")

    except websockets.exceptions.ConnectionRefused:
        print(
            "Error: Could not connect to WebSocket server. Make sure the server is running."
        )
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    print("Kokoro WebSocket Client Test")
    print("Make sure the server is running on ws://localhost:9801")
    print("=" * 50)

    asyncio.run(test_kokoro_websocket())
