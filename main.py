import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from google.cloud import speech_v1p1beta1 as speech
import json
import logging # ADDED: Import logging module

# ADDED: Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

app = FastAPI()

# --- Configuration for Google Cloud Speech-to-Text ---
RATE = 16000 # Sample rate in Hz
CHANNELS = 1 # Mono audio
ENCODING = speech.RecognitionConfig.AudioEncoding.LINEAR16 # Raw PCM

# HTML for the client-side interface
html = """
<!DOCTYPE html>
<html>
<head>
    <title>Real-time Voice Assistant</title>
    <style>
        body { font-family: 'Inter', sans-serif; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; margin: 0; background-color: #f0f2f5; color: #333; }
        .container { background-color: #fff; padding: 2.5rem; border-radius: 12px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1); text-align: center; max-width: 500px; width: 90%; }
        h1 { color: #2c3e50; margin-bottom: 1.5rem; }
        button { background-color: #4CAF50; color: white; padding: 0.8rem 1.5rem; border: none; border-radius: 8px; cursor: pointer; font-size: 1rem; transition: background-color 0.3s ease, transform 0.2s ease; margin: 0.5rem; box-shadow: 0 2px 5px rgba(0, 0, 0, 0.2); }
        button:hover { background-color: #45a049; transform: translateY(-2px); }
        button:active { transform: translateY(0); box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2); }
        button:disabled { background-color: #cccccc; cursor: not-allowed; box-shadow: none; }
        #status { margin-top: 1.5rem; font-size: 1.1rem; color: #555; }
        #transcription { margin-top: 1rem; padding: 1rem; background-color: #e9ecef; border-radius: 8px; min-height: 50px; text-align: left; word-wrap: break-word; overflow-wrap: break-word; }
        .message { margin-bottom: 0.5rem; padding: 0.5rem; border-radius: 6px; }
        .user-message { background-color: #d1e7dd; text-align: right; }
        .ai-message { background-color: #f8d7da; text-align: left; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Real-time Voice Assistant</h1>
        <button id="startButton">Start Listening</button>
        <button id="stopButton" disabled>Stop Listening</button>
        <p id="status">Click "Start Listening" to begin.</p>
        <div id="transcription"></div>
    </div>

    <script>
        let ws;
        let mediaRecorder;
        let audioChunks = [];
        let isRecording = false;

        const startButton = document.getElementById('startButton');
        const stopButton = document.getElementById('stopButton');
        const statusDisplay = document.getElementById('status');
        const transcriptionDisplay = document.getElementById('transcription');

        // Function to update UI state
        function updateUI(recording) {
            isRecording = recording;
            startButton.disabled = recording;
            stopButton.disabled = !recording;
            statusDisplay.textContent = recording ? "Listening..." : "Click 'Start Listening' to begin.";
            if (!recording) {
                transcriptionDisplay.textContent = ''; // Clear transcription when stopped
            }
        }

        // Start WebSocket connection
        function connectWebSocket() {
            if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
                console.log("WebSocket already open or connecting.");
                return;
            }
            ws = new WebSocket("ws://localhost:8000/ws");

            ws.onopen = (event) => {
                console.log("WebSocket connected:", event);
                updateUI(false); // UI ready to start recording
                statusDisplay.textContent = "Ready. Click 'Start Listening'.";
            };

            ws.onmessage = (event) => {
                const data = JSON.parse(event.data);
                if (data.type === 'transcription') {
                    transcriptionDisplay.textContent = data.text; // Display the latest transcription
                } else {
                    console.log("Received unknown message type:", data);
                }
            };

            ws.onclose = (event) => {
                console.log("WebSocket closed:", event);
                updateUI(false);
                statusDisplay.textContent = "WebSocket disconnected. Refresh page to reconnect.";
            };

            ws.onerror = (error) => {
                console.error("WebSocket error:", error);
                updateUI(false);
                statusDisplay.textContent = "WebSocket error. Check console.";
            };
        }

        // Request microphone access and start recording
        async function startRecording() {
            try {
                const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
                // We will use AudioContext to ensure 16kHz sample rate and LINEAR16 PCM format
                const audioContext = new (window.AudioContext || window.webkitAudioContext)();
                const source = audioContext.createMediaStreamSource(stream);
                const processor = audioContext.createScriptProcessor(4096, 1, 1); // Buffer size, input channels, output channels

                source.connect(processor);
                processor.connect(audioContext.destination);

                // This function will be called repeatedly with audio data
                processor.onaudioprocess = (event) => {
                    if (ws.readyState === WebSocket.OPEN) {
                        // Get 16-bit PCM data
                        const inputBuffer = event.inputBuffer.getChannelData(0);
                        const pcm16 = new Int16Array(inputBuffer.length);
                        for (let i = 0; i < inputBuffer.length; i++) {
                            pcm16[i] = Math.max(-1, Math.min(1, inputBuffer[i])) * 0x7FFF; // Convert float to 16-bit int
                        }
                        ws.send(pcm16.buffer); // Send as binary data
                    }
                };

                // Store MediaRecorder and stream to stop them later
                mediaRecorder = { stream, processor, source, audioContext }; // Store references to stop
                updateUI(true);
                statusDisplay.textContent = "Listening...";
                transcriptionDisplay.textContent = ''; // Clear previous transcription

            } catch (error) {
                console.error("Error accessing microphone:", error);
                statusDisplay.textContent = "Error: Microphone access denied or not available.";
                updateUI(false);
            }
        }

        // Stop recording and close microphone stream
        function stopRecording() {
            if (mediaRecorder) {
                mediaRecorder.processor.disconnect();
                mediaRecorder.source.disconnect();
                mediaRecorder.audioContext.close();
                mediaRecorder.stream.getTracks().forEach(track => track.stop());
                mediaRecorder = null;
            }
            // Send a signal to the server that recording has stopped (optional, but good for state management)
            if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: 'stop_recording' }));
            }
            updateUI(false);
            statusDisplay.textContent = "Recording stopped. Processing transcription...";
        }

        // Event Listeners
        startButton.addEventListener('click', startRecording);
        stopButton.addEventListener('click', stopRecording);

        // Initial WebSocket connection attempt
        connectWebSocket();
    </script>
</body>
</html>
"""

@app.get("/")
async def get():
    # MODIFIED: Changed print to logging.info
    logging.info("Root route accessed!") 
    return HTMLResponse(html)

# Google Cloud Speech-to-Text client
# Kept outside the endpoint for now, as it was in your connecting version
client = speech.SpeechClient()

# Configuration for the streaming recognition request
config = speech.RecognitionConfig(
    encoding=ENCODING,
    sample_rate_hertz=RATE,
    language_code="en-US",
)
streaming_config = speech.StreamingRecognitionConfig(
    config=config,
    interim_results=True, # Set to True to get real-time partial results
    single_utterance=False, # Set to True if you want to stop after one detected utterance
)

# WebSocket endpoint for real-time audio transcription
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    # MODIFIED: Changed print to logging.info
    logging.info("WebSocket connection accepted.")

    # Create a queue to hold incoming audio chunks
    audio_queue: asyncio.Queue = asyncio.Queue()
    # Flag to signal when to stop processing audio (e.g., client disconnected)
    stop_audio_processing = asyncio.Event()

    async def consume_websocket_audio():
        """Consumes audio data from the WebSocket and puts it into the queue."""
        try:
            while True:
                # Receive bytes (audio data) or text (control messages)
                message = await websocket.receive()
                if "bytes" in message:
                    audio_chunk = message["bytes"]
                    # MODIFIED: Changed print to logging.info
                    logging.info(f"Received audio chunk of size: {len(audio_chunk)} bytes")
                    await audio_queue.put(audio_chunk)
                elif "text" in message:
                    control_message = json.loads(message["text"])
                    if control_message.get("type") == "stop_recording":
                        # MODIFIED: Changed print to logging.info
                        logging.info("Client sent stop_recording signal.")
                        stop_audio_processing.set() # Signal to stop the audio processing
                        await audio_queue.put(None) # Put a sentinel value to unblock the generator
                        break
        except WebSocketDisconnect:
            # MODIFIED: Changed print to logging.info
            logging.info("WebSocket disconnected by client.")
        except Exception as e:
            # MODIFIED: Changed print to logging.error
            logging.error(f"Error consuming websocket audio: {e}")
        finally:
            stop_audio_processing.set() # Ensure processing stops on any error/disconnect
            if audio_queue.empty(): # Only put None if not already processing
                await audio_queue.put(None) # Ensure the generator is unblocked

    async def generate_audio_requests():
        """Generates StreamingRecognizeRequest objects from audio chunks."""
        while not stop_audio_processing.is_set():
            chunk = await audio_queue.get()
            if chunk is None: # Sentinel value to stop generator
                break
            yield speech.StreamingRecognizeRequest(audio_content=chunk)
        # MODIFIED: Changed print to logging.info
        logging.info("Audio request generator stopped.")


    # Start consuming audio from the WebSocket in a background task
    consumer_task = asyncio.create_task(consume_websocket_audio())

    try:
        # Start the Google Speech-to-Text streaming recognition
        # The first request in the stream must contain the streaming_config
        requests = [speech.StreamingRecognizeRequest(streaming_config=streaming_config)]

        # Add the audio content to the requests stream from our generator
        audio_requests_generator = generate_audio_requests()
        async for request in audio_requests_generator:
            requests.append(request)

        # This call sends the requests and receives responses in real-time
        # MODIFIED: Changed print to logging.info for transcription
        responses = client.streaming_recognize(iter(requests)) # Use iter() to make it an async iterable

        async for response in responses:
            if not response.results:
                continue

            # The first result in the list is the most relevant
            result = response.results[0]
            if not result.alternatives:
                continue

            # The first alternative is the most likely transcription
            transcript = result.alternatives[0].transcript

            # Only send back final results for now, or interim results if enabled
            if result.is_final or streaming_config.interim_results:
                # MODIFIED: Changed print to logging.info
                logging.info(f"Transcription: {transcript}")
                # Send the transcription back to the client
                await websocket.send_json({"type": "transcription", "text": transcript})

    except asyncio.CancelledError:
        # MODIFIED: Changed print to logging.info
        logging.info("Streaming recognition cancelled.")
    except Exception as e:
        # MODIFIED: Changed print to logging.error
        logging.error(f"Error during streaming recognition: {e}")
    finally:
        # Clean up: cancel the consumer task and close the WebSocket
        consumer_task.cancel()
        await websocket.close()
        # MODIFIED: Changed print to logging.info
        logging.info("WebSocket connection closed.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
