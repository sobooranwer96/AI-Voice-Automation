from fastapi import APIRouter
from fastapi.responses import HTMLResponse

# Create an API router specific for web client routes
router = APIRouter()

# HTML for the client-side interface
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
        } else if (msg.type === "gemini_response") {
          addFinal("AI: " + msg.text);
          setStatus("AI responded.");
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

@router.get("/", response_class=HTMLResponse)
async def get_web_client():
    """Serves the main HTML/JavaScript client for the voice assistant."""
    return HTMLResponse(HTML_CLIENT)
