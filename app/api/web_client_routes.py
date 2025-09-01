from fastapi import APIRouter
from fastapi.responses import HTMLResponse

router = APIRouter()

HTML_CLIENT = """
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <title>Real-time Voice Assistant Demo</title>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <style>
    body { font-family: system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 2rem; background-color: #f0f2f5; color: #333; display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 100vh; }
    h1 { margin-top: 0; color: #2c3e50; }
    .container { background-color: #fff; padding: 2.5rem; border-radius: 12px; box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1); text-align: center; max-width: 500px; width: 90%; }
    .row { display: flex; gap: 0.5rem; align-items: center; justify-content: center; flex-wrap: wrap; margin-bottom: 1rem; }
    button { padding: 0.6rem 1rem; border-radius: 8px; border: 1px solid #ccc; background: #f7f7f7; cursor: pointer; transition: background-color 0.3s, transform 0.2s; }
    button:hover { background-color: #e9e9e9; transform: translateY(-1px); }
    button:disabled { opacity: 0.5; cursor: not-allowed; }
    #status { margin-top: 0.75rem; font-size: 0.95rem; color: #555; }
    #transcript { margin-top: 1rem; padding: 1rem; min-height: 120px; border: 1px solid #ddd; border-radius: 8px; background: #fafafa; white-space: pre-wrap; text-align: left; }
    .small { font-size: 0.85rem; color: #666; }
    code { background: #f0f0f0; padding: 0 0.25rem; border-radius: 4px; }
  </style>
</head>
<body>
  <div class="container">
    <h1>🎙️ Real-time AI Assistant</h1>
    <div class="row">
      <button id="startBtn">Start Listening</button>
      <button id="stopBtn" disabled>Stop Listening</button>
    </div>
    <span id="status">Idle</span>
    <div id="transcript" aria-live="polite"></div>
    <p class="small">
      This demo captures microphone audio, streams it to the server for transcription, and plays back the AI's response.
    </p>
  </div>

<script>
(() => {
    let ws = null;
    let audioContext = null;
    let mediaStream = null;
    let sourceNode = null;
    let processorNode = null;
    let running = false;
    let audioChunks = [];
    let playbackStarted = false;

    const startBtn = document.getElementById('startBtn');
    const stopBtn  = document.getElementById('stopBtn');
    const statusEl = document.getElementById('status');
    const transcriptEl = document.getElementById('transcript');

    function setStatus(msg) {
        statusEl.textContent = msg;
    }

    function setPartial(text) {
        const lines = transcriptEl.textContent.split("\\n");
        if (lines.length && lines[lines.length - 1].startsWith("[partial] ")) {
            lines[lines.length - 1] = "[partial] " + text;
            transcriptEl.textContent = lines.join("\\n");
        } else {
            transcriptEl.textContent += (transcriptEl.textContent ? "\\n" : "") + "[partial] " + text;
        }
    }

    function addFinal(text) {
        const lines = transcriptEl.textContent.split("\\n");
        if (lines.length && lines[lines.length - 1].startsWith("[partial] ")) {
            lines[lines.length - 1] = text;
            transcriptEl.textContent = lines.join("\\n");
        } else {
            transcriptEl.textContent += (transcriptEl.textContent ? "\\n" : "") + text;
        }
    }

    async function playAudioBlob() {
        if (audioChunks.length === 0) {
            playbackStarted = false;
            setStatus("AI has finished speaking.");
            return;
        }

        const audioBlob = new Blob(audioChunks, { type: 'audio/mpeg' });
        audioChunks = [];

        try {
            const arrayBuffer = await audioBlob.arrayBuffer();
            const audioBuffer = await audioContext.decodeAudioData(arrayBuffer);
            const source = audioContext.createBufferSource();
            source.buffer = audioBuffer;
            source.connect(audioContext.destination);
            source.start(0);

            source.onended = () => {
                playbackStarted = false;
                setStatus("AI has finished speaking.");
                stopBtn.disabled = false;
            };

        } catch (e) {
            console.error("Error decoding audio data:", e);
            playbackStarted = false;
            setStatus("An error occurred during playback.");
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
        startBtn.disabled = true;
        stopBtn.disabled = false;

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
        const bufferSize = 4096;
        processorNode = audioContext.createScriptProcessor(bufferSize, 1, 1);
        processorNode.onaudioprocess = (event) => {
            if (!ws || ws.readyState !== WebSocket.OPEN) return;
            const input = event.inputBuffer.getChannelData(0);
            const pcm16 = downsampleTo16kHz(input, inputSampleRate);
            try { ws.send(pcm16); } catch (e) { console.error("WS send error:", e); }
        };
        sourceNode.connect(processorNode);
        processorNode.connect(audioContext.destination);

        ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
        ws.binaryType = "arraybuffer";

        ws.onopen = () => {
            setStatus("WebSocket connected. Streaming audio…");
        };

        ws.onmessage = (event) => {
            if (typeof event.data === 'string') {
                try {
                    const msg = JSON.parse(event.data);
                    if (msg.type === "transcript") {
                        if (msg.is_final) {
                            addFinal("You: " + msg.text);
                            setStatus("AI is thinking...");
                        } else {
                            setPartial("[partial] " + msg.text);
                        }
                    } else if (msg.type === "gemini_response") {
                        addFinal("AI: " + msg.text);
                        setStatus("AI is speaking...");
                        playAudioBlob();
                    } else if (msg.type === "info") {
                        setStatus(msg.message);
                    }
                } catch (e) {
                    console.error("Failed to parse WebSocket text message:", e);
                }
            } else if (event.data instanceof ArrayBuffer) {
                audioChunks.push(event.data);
            }
        };

        ws.onclose = () => { setStatus("WebSocket closed."); cleanup(); };
        ws.onerror = (e) => { console.error("WebSocket error:", e); setStatus("WebSocket error."); };
    }

    function stop() {
        if (!running) return;
        running = false;
        setStatus("Stopping…");
        if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "stop" }));
        cleanup();
    }

    function cleanup() {
        startBtn.disabled = false;
        stopBtn.disabled = true;

        if (playbackStarted) {
            playbackStarted = false;
        }
        audioChunks = [];

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

@router.get("/", response_class=HTMLResponse)
async def get():
    return HTMLResponse(HTML_CLIENT)