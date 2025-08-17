# main.py
#
# Run with:
#   python -m uvicorn main:app --reload
#
# Requires:
#   pip install fastapi uvicorn google-cloud-speech
# And set Google credentials:
#   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service_account.json
#
# This app exposes:
#   - GET  /    -> minimal HTML/JS client to stream mic audio over WebSocket and show live transcripts
#   - WS  /ws   -> receives 16 kHz, mono, 16-bit PCM (LINEAR16) audio bytes and streams to Google STT
#
# Notes:
#   - We bridge FastAPI's asyncio world with Google Cloud's blocking streaming_recognize by
#     pushing audio into a thread-safe queue and running the recognizer in a background thread.
#   - It auto-detects which google-cloud-speech streaming API signature your environment uses:
#       * Old style: client.streaming_recognize(config=StreamingRecognitionConfig, requests=audio_gen)
#       * New style: client.streaming_recognize(requests=req_gen_with_first_config_request)
#   - Logging is verbose to aid debugging of chunk sizes, API status, and raw responses.

import asyncio
import contextlib
import inspect
import json
import logging
import os
import threading
from queue import Queue, Empty
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

# Google Cloud Speech-to-Text
from google.cloud import speech

# ------------------------------------------------------------------------------
# Logging setup
# ------------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(threadName)s | %(name)s | %(message)s",
)
logger = logging.getLogger("voice-assistant")

# ------------------------------------------------------------------------------
# FastAPI app
# ------------------------------------------------------------------------------
app = FastAPI(title="Real-time Voice Assistant (FastAPI + Google STT)")

# ------------------------------------------------------------------------------
# HTML Client (embedded, self-contained)
# ------------------------------------------------------------------------------
HTML_CLIENT = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Real-time Voice Assistant Demo</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 2rem; }
    h1 { margin-top: 0; }
    button { padding: 0.6rem 1rem; margin-right: 0.5rem; border-radius: 8px; border: 1px solid #ccc; background: #f7f7f7; cursor: pointer; }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    #status { margin-top: 0.75rem; font-size: 0.95rem; color: #555; }
    #transcript { margin-top: 1rem; padding: 1rem; min-height: 120px; border: 1px solid #ddd; border-radius: 8px; background: #fafafa; white-space: pre-wrap; }
    .small { font-size: 0.85rem; color: #666; }
    .row { display: flex; gap: 0.5rem; align-items: center; flex-wrap: wrap; }
    code { background: #f0f0f0; padding: 0 0.25rem; border-radius: 4px; }
  </style>
</head>
<body>
  <h1>🎙️ Real-time Transcription</h1>
  <div class="row">
    <button id="startBtn">Start Listening</button>
    <button id="stopBtn" disabled>Stop Listening</button>
    <span id="status">Idle</span>
  </div>
  <div id="transcript" aria-live="polite"></div>
  <p class="small">
    This demo captures microphone audio, downsamples to <code>16 kHz</code>, encodes as
    <code>LINEAR16</code> (16-bit PCM), and streams it over a WebSocket to the server.
    Live transcriptions appear above (partial and final).
  </p>

<script>
(() => {
  let ws = null;
  let audioContext = null;
  let mediaStream = null;
  let sourceNode = null;
  let processorNode = null;
  let running = false;

  const startBtn = document.getElementById('startBtn');
  const stopBtn  = document.getElementById('stopBtn');
  const statusEl = document.getElementById('status');
  const transcriptEl = document.getElementById('transcript');

  function setStatus(msg) {
    statusEl.textContent = msg;
  }

  function setPartial(text) {
    // Show/replace a single partial line at the end
    const lines = transcriptEl.textContent.split("\\n");
    if (lines.length && lines[lines.length - 1].startsWith("[partial] ")) {
      lines[lines.length - 1] = "[partial] " + text;
      transcriptEl.textContent = lines.join("\\n");
    } else {
      transcriptEl.textContent += (transcriptEl.textContent ? "\\n" : "") + "[partial] " + text;
    }
  }

  function addFinal(text) {
    // Replace any trailing partial with final; else just append
    const lines = transcriptEl.textContent.split("\\n");
    if (lines.length && lines[lines.length - 1].startsWith("[partial] ")) {
      lines[lines.length - 1] = text;
      transcriptEl.textContent = lines.join("\\n");
    } else {
      transcriptEl.textContent += (transcriptEl.textContent ? "\\n" : "") + text;
    }
  }

  // Downsample Float32 @ input SR to Int16 @ 16kHz
  function downsampleTo16kHz(float32Array, inSampleRate) {
    const outSampleRate = 16000;
    if (inSampleRate === outSampleRate) {
      const int16 = new Int16Array(float32Array.length);
      for (let i = 0; i < float32Array.length; i++) {
        let s = Math.max(-1, Math.min(1, float32Array[i]));
        int16[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      }
      return int16.buffer;
    }

    const ratio = inSampleRate / outSampleRate;
    const newLength = Math.round(float32Array.length / ratio);
    const result = new Int16Array(newLength);
    let offset = 0;
    for (let i = 0; i < newLength; i++) {
      const nextOffset = Math.round((i + 1) * ratio);
      let sum = 0, count = 0;
      for (let j = offset; j < nextOffset && j < float32Array.length; j++) {
        sum += float32Array[j];
        count++;
      }
      const v = count ? (sum / count) : 0;
      const s = Math.max(-1, Math.min(1, v));
      result[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
      offset = nextOffset;
    }
    return result.buffer;
  }

  async function start() {
    if (running) return;
    running = true;
    transcriptEl.textContent = "";
    setStatus("Requesting microphone...");

    try {
      mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: false, noiseSuppression: false, autoGainControl: false },
        video: false
      });
    } catch (err) {
      console.error(err);
      setStatus("Microphone permission denied.");
      running = false;
      return;
    }

    audioContext = new (window.AudioContext || window.webkitAudioContext)({ latencyHint: "interactive" });
    const inputSampleRate = audioContext.sampleRate;
    sourceNode = audioContext.createMediaStreamSource(mediaStream);

    const bufferSize = 4096; // reasonable latency
    processorNode = audioContext.createScriptProcessor(bufferSize, 1, 1);

    processorNode.onaudioprocess = (event) => {
      if (!ws || ws.readyState !== WebSocket.OPEN) return;
      const input = event.inputBuffer.getChannelData(0);
      const pcm16 = downsampleTo16kHz(input, inputSampleRate);
      try { ws.send(pcm16); } catch (e) { console.error("WS send error:", e); }
    };

    sourceNode.connect(processorNode);
    processorNode.connect(audioContext.destination); // needed on some browsers

    ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      setStatus("WebSocket connected. Streaming audio…");
      startBtn.disabled = true;
      stopBtn.disabled = false;
    };

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data);
        if (msg.type === "transcript") {
          if (msg.is_final) addFinal(msg.text);
          else setPartial(msg.text);
        } else if (msg.type === "info") {
          setStatus(msg.message);
        }
      } catch {
        // non-JSON messages, ignore
      }
    };

    ws.onclose = () => { setStatus("WebSocket closed."); cleanup(); };
    ws.onerror = (e) => { console.error("WebSocket error:", e); setStatus("WebSocket error."); };
  }

  function stop() {
    if (!running) return;
    running = false;
    setStatus("Stopping…");

    try { if (ws && ws.readyState === WebSocket.OPEN) ws.close(); } catch {}
    cleanup();
  }

  function cleanup() {
    startBtn.disabled = false;
    stopBtn.disabled = true;

    if (processorNode) { try { processorNode.disconnect(); } catch {} processorNode.onaudioprocess = null; processorNode = null; }
    if (sourceNode) { try { sourceNode.disconnect(); } catch {} sourceNode = null; }
    if (audioContext) { try { audioContext.close(); } catch {} audioContext = null; }
    if (mediaStream) { for (const track of mediaStream.getTracks()) track.stop(); mediaStream = null; }
    if (ws) { try { ws.close(); } catch {} ws = null; }

    setStatus("Idle");
  }

  document.getElementById('startBtn').addEventListener('click', start);
  document.getElementById('stopBtn').addEventListener('click', stop);
})();
</script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
async def index():
    return HTML_CLIENT

# ------------------------------------------------------------------------------
# Google STT config builders
# ------------------------------------------------------------------------------
def build_streaming_config() -> speech.StreamingRecognitionConfig:
    """Builds a StreamingRecognitionConfig (with nested RecognitionConfig)."""
    rec_config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        sample_rate_hertz=16000,
        language_code="en-US",
        enable_automatic_punctuation=True,
    )
    streaming_config = speech.StreamingRecognitionConfig(
        config=rec_config,
        interim_results=True,
        single_utterance=False,
    )
    return streaming_config

# ------------------------------------------------------------------------------
# Request generators for both API styles
# ------------------------------------------------------------------------------
def audio_requests_only_generator(q: Queue):
    """Yields only audio_content requests (for old API that takes config as separate arg)."""
    while True:
        try:
            chunk = q.get(timeout=0.1)
        except Empty:
            continue
        if chunk is None:
            break
        yield speech.StreamingRecognizeRequest(audio_content=chunk)

def full_requests_generator(q: Queue, streaming_config: speech.StreamingRecognitionConfig):
    """Yields first a config request, then audio_content (for newer API style)."""
    # First config request
    yield speech.StreamingRecognizeRequest(streaming_config=streaming_config)
    # Then audio
    for req in audio_requests_only_generator(q):
        yield req

# ------------------------------------------------------------------------------
# Worker thread: run Google STT streaming and post results back via an asyncio queue
# ------------------------------------------------------------------------------
def stt_worker(
    audio_q: Queue,
    resp_async_q: asyncio.Queue,
    stop_event: threading.Event,
    credentials_ok: bool,
    loop: asyncio.AbstractEventLoop,
):
    thread_logger = logging.getLogger("stt-worker")
    try:
        if not credentials_ok:
            raise RuntimeError(
                "GOOGLE_APPLICATION_CREDENTIALS not set; cannot initialize SpeechClient."
            )

        client = speech.SpeechClient()
        streaming_config = build_streaming_config()

        # Detect which signature is available
        sig = inspect.signature(client.streaming_recognize)
        has_config_param = "config" in sig.parameters
        if has_config_param:
            thread_logger.info("Using OLD streaming_recognize signature: streaming_recognize(config=..., requests=...)")
            requests_iter = audio_requests_only_generator(audio_q)
        else:
            thread_logger.info("Using NEW streaming_recognize signature: streaming_recognize(requests=...) with initial config request")
            requests_iter = full_requests_generator(audio_q, streaming_config)

        thread_logger.info("Starting Google streaming_recognize...")
        # Invoke the API according to detected signature
        if has_config_param:
            responses = client.streaming_recognize(config=streaming_config, requests=requests_iter)
        else:
            responses = client.streaming_recognize(requests=requests_iter)

        # Iterate over responses (each response may contain multiple results)
        for response in responses:
            thread_logger.debug("Raw response: %s", response)

            if not response.results:
                loop.call_soon_threadsafe(
                    resp_async_q.put_nowait, {"type": "info", "message": "No results in current response."}
                )
                continue

            for result in response.results:
                if not result.alternatives:
                    continue
                transcript = result.alternatives[0].transcript
                is_final = bool(result.is_final)

                thread_logger.info("Transcript (%s): %s", "final" if is_final else "partial", transcript)

                loop.call_soon_threadsafe(
                    resp_async_q.put_nowait,
                    {"type": "transcript", "text": transcript, "is_final": is_final},
                )

        thread_logger.info("Google streaming_recognize iterator ended.")
    except Exception as e:
        thread_logger.exception("STT worker error: %s", e)
        with contextlib.suppress(Exception):
            loop.call_soon_threadsafe(
                resp_async_q.put_nowait, {"type": "info", "message": f"STT error: {e}"}
            )
    finally:
        stop_event.set()
        thread_logger.info("STT worker exiting.")

# ------------------------------------------------------------------------------
# WebSocket endpoint
# ------------------------------------------------------------------------------
@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    logger.info("WebSocket client connected: %s", ws.client)

    # Check credentials early for clear errors
    credentials_ok = bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
    if not credentials_ok:
        msg = "Server missing GOOGLE_APPLICATION_CREDENTIALS; transcription will not work."
        logger.error(msg)
        await ws.send_text(json.dumps({"type": "info", "message": msg}))

    audio_q: Queue = Queue(maxsize=100)          # audio chunks for STT worker
    responses_q: asyncio.Queue = asyncio.Queue() # messages back to browser
    stop_event = threading.Event()
    loop = asyncio.get_running_loop()

    # Launch STT worker in a dedicated thread
    stt_thread = threading.Thread(
        target=stt_worker,
        name="STT-Thread",
        args=(audio_q, responses_q, stop_event, credentials_ok, loop),
        daemon=True,
    )
    stt_thread.start()
    logger.info("STT worker thread started.")

    # Task to forward STT responses back to the client
    async def sender_task():
        try:
            while not stop_event.is_set():
                try:
                    msg = await asyncio.wait_for(responses_q.get(), timeout=0.2)
                except asyncio.TimeoutError:
                    continue
                try:
                    await ws.send_text(json.dumps(msg))
                except Exception as e:
                    logger.exception("Error sending WS message: %s", e)
                    break
        finally:
            logger.info("Sender task terminated.")

    sender = asyncio.create_task(sender_task())

    try:
        await ws.send_text(json.dumps({"type": "info", "message": "Ready to receive audio (16kHz LINEAR16)."}))

        # Receive loop: accept both bytes and text (for control)
        while True:
            try:
                data = await ws.receive()
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected by client.")
                break

            msg_type = data.get("type")
            if msg_type == "websocket.disconnect":
                logger.info("WebSocket disconnect event.")
                break

            if msg_type == "websocket.receive":
                if "bytes" in data and data["bytes"] is not None:
                    chunk: bytes = data["bytes"]
                    logger.info("Received audio chunk: %d bytes", len(chunk))
                    try:
                        audio_q.put_nowait(chunk)
                    except Exception:
                        logger.warning("Audio queue full; dropping a chunk of %d bytes", len(chunk))
                elif "text" in data and data["text"] is not None:
                    text = data["text"]
                    logger.info("Received WS text message: %s", text)
                    if text.strip().lower() in {"stop", "close", "eos"}:
                        break
                    await ws.send_text(json.dumps({"type": "info", "message": f"Server received text: {text}"}))
            else:
                logger.debug("Unhandled WS event: %s", msg_type)

    except Exception as e:
        logger.exception("WebSocket handler error: %s", e)
    finally:
        # Signal worker to stop by sending sentinel None
        with contextlib.suppress(Exception):
            audio_q.put_nowait(None)

        stop_event.set()

        # Wait briefly for worker to exit
        with contextlib.suppress(Exception):
            stt_thread.join(timeout=2.0)

        # Close sender task
        with contextlib.suppress(Exception):
            sender.cancel()
            await sender

        # Close the socket
        with contextlib.suppress(Exception):
            await ws.close()

        logger.info("WebSocket connection closed.")

# ------------------------------------------------------------------------------
# Startup log
# ------------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    cred = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if cred:
        logger.info("GOOGLE_APPLICATION_CREDENTIALS is set: %s", cred)
    else:
        logger.warning("GOOGLE_APPLICATION_CREDENTIALS is not set. STT will fail until configured.")
    logger.info("App started. Open http://127.0.0.1:8000 in your browser.")
