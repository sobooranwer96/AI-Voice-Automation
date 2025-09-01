import asyncio
import contextlib
import inspect
import logging
import threading
from queue import Queue, Empty
from typing import Optional

from google.cloud import speech

from app.services.llm_service import LLMService
from app.services.text_to_speech import TTSService

logger = logging.getLogger(__name__)

def build_streaming_config() -> speech.StreamingRecognitionConfig:
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

def audio_requests_only_generator(q: Queue):
    while True:
        try:
            chunk = q.get(timeout=0.1)
        except Empty:
            continue
        if chunk is None:
            break
        yield speech.StreamingRecognizeRequest(audio_content=chunk)

def full_requests_generator(q: Queue, streaming_config: speech.StreamingRecognitionConfig):
    yield speech.StreamingRecognizeRequest(streaming_config=streaming_config)
    for req in audio_requests_only_generator(q):
        yield req

def stt_worker(
    audio_q: Queue,
    resp_async_q: asyncio.Queue,
    stop_event: threading.Event,
    credentials_ok: bool,
    loop: asyncio.AbstractEventLoop,
    llm_service_instance: Optional[LLMService] = None,
    tts_service_instance: Optional[TTSService] = None,
):
    thread_logger = logging.getLogger(threading.current_thread().name)
    try:
        if not credentials_ok:
            raise RuntimeError(
                "GOOGLE_APPLICATION_CREDENTIALS not set; cannot initialize SpeechClient."
            )

        client = speech.SpeechClient()
        streaming_config = build_streaming_config()

        sig = inspect.signature(client.streaming_recognize)
        has_config_param = "config" in sig.parameters
        if has_config_param:
            thread_logger.info("Using OLD streaming_recognize signature: streaming_recognize(config=..., requests=...)")
            requests_iter = audio_requests_only_generator(audio_q)
        else:
            thread_logger.info("Using NEW streaming_recognize signature: streaming_recognize(requests=...) with initial config request")
            requests_iter = full_requests_generator(audio_q, streaming_config)

        thread_logger.info("Starting Google streaming_recognize...")
        if has_config_param:
            responses = client.streaming_recognize(config=streaming_config, requests=requests_iter)
        else:
            responses = client.streaming_recognize(requests=requests_iter)

        for response in responses:
            thread_logger.debug("Raw STT response: %s", response)
            if not response.results:
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
                
                if is_final and llm_service_instance:
                    thread_logger.info("Calling LLMService with final transcript: '%s'", transcript)
                    try:
                        llm_text = asyncio.run(llm_service_instance.generate_response(transcript))
                        
                        if llm_text:
                            thread_logger.info("LLM Response: %s", llm_text)
                            
                            if tts_service_instance:
                                thread_logger.info("Streaming audio from ElevenLabs...")
                                for chunk in tts_service_instance.stream_audio(llm_text):
                                    loop.call_soon_threadsafe(
                                        resp_async_q.put_nowait,
                                        {"type": "audio_chunk", "data": chunk},
                                    )
                            loop.call_soon_threadsafe(
                                resp_async_q.put_nowait,
                                {"type": "gemini_response", "text": llm_text},
                            )
                        else:
                             loop.call_soon_threadsafe(
                                resp_async_q.put_nowait, {"type": "info", "message": "Gemini could not generate a response."}
                             )

                    except Exception as llm_e:
                        thread_logger.exception("Error calling LLMService or TTSService: %s", llm_e)
                        with contextlib.suppress(Exception):
                            loop.call_soon_threadsafe(
                                resp_async_q.put_nowait, {"type": "info", "message": f"LLM/TTS error: {llm_e}"}
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