docker build -t whisper -f docker-cpu.dockerfile .

-v "$(pwd)/whisper_model/:/whisper_model/"

docker run -p 9800:9800 -v "$(pwd)/whisper_model/:/whisper_model/" whisper

docker build -t klentyboopathi/fastapiwhisper:latest -f docker-gpu.dockerfile .

docker push klentyboopathi/fastapiwhisper:latest