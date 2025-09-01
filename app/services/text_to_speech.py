# The stream_audio method should now simply yield the chunks directly.
import os
import logging
from typing import Iterator, Optional
from elevenlabs.client import ElevenLabs

logger = logging.getLogger(__name__)

class TTSService:
    def __init__(self, api_key: Optional[str] = None):
        if api_key is None:
            api_key = os.environ.get("VOICE_ASSISTANT_ELEVENLABS_API_KEY")

        if not api_key:
            logger.error("ElevenLabs API key not provided and VOICE_ASSISTANT_ELEVENLABS_API_KEY environment variable not set.")
            self.client = None
            raise ValueError("ElevenLabs API key is required to initialize TTSService.")
        
        try:
            self.client = ElevenLabs(api_key=api_key)
            logger.info("TTSService initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize ElevenLabs client: {e}", exc_info=True)
            self.client = None
            raise RuntimeError(f"Could not initialize ElevenLabs client: {e}")

    def stream_audio(self, text: str, voice_id: str = "JBFqnCBsd6RMkjVDRZzb") -> Iterator[bytes]:
        if self.client is None:
            logger.warning("ElevenLabs client not initialized. Cannot stream audio.")
            return iter([])
        
        try:
            audio_stream = self.client.text_to_speech.stream(
                text=text,
                voice_id=voice_id,
                model_id="eleven_multilingual_v2",
            )
            
            for chunk in audio_stream:
                if chunk:
                    yield chunk
        except Exception as e:
            logger.error(f"Error streaming audio from ElevenLabs: {e}", exc_info=True)
            return iter([])