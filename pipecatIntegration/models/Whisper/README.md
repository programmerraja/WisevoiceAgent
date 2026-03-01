docker build -t whisper -f docker-cpu.dockerfile .

-v "$(pwd)/whisper_model/:/whisper_model/"

docker run -p 9800:9800 -v "$(pwd)/whisper_model/:/whisper_model/" whisper

