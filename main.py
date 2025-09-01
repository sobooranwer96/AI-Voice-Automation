# main.py
#
# Run with:
#   python -m uvicorn main:app --reload
#
# Requires:
#   pip install fastapi uvicorn google-cloud-speech google-generativeai
# And set Google credentials:
#   export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service_account.json
#   export VOICE_ASSISTANT_GEMINI_API_KEY=YOUR_GEMINI_API_KEY
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
import json
import logging
import os
import threading
from queue import Queue
from typing import Optional

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse

# Import modules from our refactored structure
from app.api import web_client_routes
from app.api import websocket_routes
from app.services import speech_to_text
from app.services.llm_service import LLMService
import google.generativeai as genai

# ------------------------------------------------------------------------------
# Logging setup
# ------------------------------------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s | %(levelname)s | %(threadName)s | %(name)s | %(message)s",
)
logger = logging.getLogger("voice-assistant-main")

# ------------------------------------------------------------------------------
# FastAPI app
# ------------------------------------------------------------------------------
app = FastAPI(title="Real-time Voice Assistant (FastAPI + Google STT + Gemini)")

app.include_router(web_client_routes.router)
app.include_router(websocket_routes.router)

# ------------------------------------------------------------------------------
# Global LLM Service Instance (initialized on startup)
# ------------------------------------------------------------------------------
llm_service_instance: Optional[LLMService] = None

# ------------------------------------------------------------------------------
# Startup log and LLM Service Initialization
# ------------------------------------------------------------------------------
@app.on_event("startup")
async def on_startup():
    global llm_service_instance

    cred = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if cred:
        logger.info("GOOGLE_APPLICATION_CREDENTIALS is set: %s", cred)
    else:
        logger.warning("GOOGLE_APPLICATION_CREDENTIALS is not set. STT will fail until configured.")
    
    gemini_api_key = os.environ.get("VOICE_ASSISTANT_GEMINI_API_KEY")
    if gemini_api_key:
        logger.info("VOICE_ASSISTANT_GEMINI_API_KEY is set. Attempting to initialize LLMService.")
        try:
            llm_service_instance = LLMService(api_key=gemini_api_key, model_name='gemini-2.5-flash')
            websocket_routes.llm_service_instance = llm_service_instance
            logger.info("LLMService initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize LLMService: {e}", exc_info=True)
            llm_service_instance = None
    else:
        logger.warning("VOICE_ASSISTANT_GEMINI_API_KEY is not set. LLMService will not be initialized.")
        llm_service_instance = None

    logger.info("App started. Open http://127.0.0.1:8000 in your browser.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)