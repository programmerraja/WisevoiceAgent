docker run --gpus all -p 8880:8880 ghcr.io/remsky/kokoro-fastapi-gpu:latest

docker run -p 8880:8880 ghcr.io/remsky/kokoro-fastapi-cpu:v0.2.4


docker build -t kokoro-cpu -f kokoro-cpu.dockerfile .

docker run -v "$(pwd)/kokoro_model/:/kokoro_model/" -p 8880:8880 kokoro-cpu

