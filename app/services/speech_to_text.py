import asyncio
import contextlib
import inspect
import json
import logging
import os
import threading
from queue import Queue, Empty
from typing import Optional

# Google Cloud Speech-to-Text
from google.cloud import speech

# NEW: Import LLMService from our new module
from app.services.llm_service import LLMService

# Configure a logger specifically for this module
logger = logging.getLogger(__name__)

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
    llm_service_instance: Optional[LLMService] = None, # Changed from gemini_model_instance
):
    thread_logger = logging.getLogger(threading.current_thread().name) # Use thread name for logger
    try:
        if not credentials_ok:
            raise RuntimeError(
                "GOOGLE_APPLICATION_CREDENTIALS not set; cannot initialize SpeechClient."
            )

        client = speech.SpeechClient() # Instantiated here for the worker thread
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
            thread_logger.debug("Raw STT response: %s", response)

            if not response.results:
                loop.call_soon_threadsafe(
                    resp_async_q.put_nowait, {"type": "info", "message": "No STT results in current response."}
                )
                continue

            for result in response.results:
                if not result.alternatives:
                    continue
                transcript = result.alternatives[0].transcript
                is_final = bool(result.is_final)

                thread_logger.info("STT Transcript (%s): %s", "final" if is_final else "partial", transcript)

                loop.call_soon_threadsafe(
                    resp_async_q.put_nowait,
                    {"type": "transcript", "text": transcript, "is_final": is_final},
                )

                # NEW: Call LLMService with final transcript
                if is_final and llm_service_instance:
                    thread_logger.info("Calling LLMService with final transcript: '%s'", transcript)
                    try:
                        # Use loop.run_until_complete or asyncio.run_coroutine_threadsafe
                        # to call the async generate_response from this sync thread
                        # asyncio.run_coroutine_threadsafe is safer for long-running coroutines
                        future = asyncio.run_coroutine_threadsafe(
                            llm_service_instance.generate_response(transcript), loop
                        )
                        llm_text = future.result(timeout=30) # Wait for result, with a timeout
                        
                        if llm_text: # Check if LLM returned a response
                            thread_logger.info("LLM Response: %s", llm_text)
                            loop.call_soon_threadsafe(
                                resp_async_q.put_nowait,
                                {"type": "gemini_response", "text": llm_text},
                            )
                        else:
                            thread_logger.warning("LLMService returned no text for transcript: %s", transcript)

                    except Exception as llm_e:
                        thread_logger.exception("Error calling LLMService: %s", llm_e)
                        with contextlib.suppress(Exception): # Suppress errors on put_nowait if queue is full/closed
                            loop.call_soon_threadsafe(
                                resp_async_q.put_nowait, {"type": "info", "message": f"LLM error: {llm_e}"}
                            )


        thread_logger.info("Google streaming_recognize iterator ended.")
    except Exception as e:
        thread_logger.exception("STT worker error: %s", e)
        with contextlib.suppress(Exception):
            loop.call_soon_threadsafe(
                resp_async_q.put_nowait, {"type": "info", "message": f"STT worker critical error: {e}"}
            )
    finally:
        stop_event.set()
        thread_logger.info("STT worker exiting.")