docker run -p 9800:9800 -v "$(pwd)/models/Whisper/whisper_model/:/whisper_model/" whisper &
docker run -v "$(pwd)/models/Kokoro/kokoro_model/:/kokoro_model/" -p 8880:8880 kokoro-cpu 
