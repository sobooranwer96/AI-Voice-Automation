import asyncio
import contextlib
import json
import logging
import os
import threading
from queue import Queue
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

# Import services from our refactored structure
from app.services import speech_to_text # Contains stt_worker and related functions
from app.services.llm_service import LLMService

# Create an API router specific for WebSocket routes
router = APIRouter()
logger = logging.getLogger(__name__)

# This global variable will be set by the startup event in main.py
llm_service_instance: Optional[LLMService] = None 

# WebSocket endpoint
@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    logger.info("WebSocket client connected: %s", ws.client)

    # Check credentials early for clear errors
    credentials_ok = bool(os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"))
    if not credentials_ok:
        msg = "Server missing GOOGLE_APPLICATION_CREDENTIALS; transcription will not work."
        logger.error(msg)
        await ws.send_text(json.dumps({"type": "info", "message": msg}))
    
    # Check if LLM service is initialized (it should be from startup event)
    if llm_service_instance is None:
        msg = "LLMService not initialized. Gemini LLM will not work."
        logger.error(msg)
        await ws.send_text(json.dumps({"type": "info", "message": msg}))

    audio_q: Queue = Queue(maxsize=100)          # audio chunks for STT worker
    responses_q: asyncio.Queue = asyncio.Queue() # messages back to browser
    stop_event = threading.Event()
    loop = asyncio.get_running_loop()

    # Launch STT worker in a dedicated thread
    # Pass the global llm_service_instance to the stt_worker
    stt_thread = threading.Thread(
        target=speech_to_text.stt_worker, # Call the refactored worker function
        name="STT-Thread",
        args=(audio_q, responses_q, stop_event, credentials_ok, loop, llm_service_instance), # Pass llm_service_instance
        daemon=True,
    )
    stt_thread.start()
    logger.info("STT worker thread started.")

    # Task to forward STT responses and Gemini responses back to the client
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
                    logger.debug("Received audio chunk: %d bytes", len(chunk))
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