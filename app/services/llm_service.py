import asyncio
import os
import logging
import google.generativeai as genai
from typing import Optional, AsyncGenerator

logger = logging.getLogger(__name__)

class LLMService:
    """
    A service class to encapsulate interactions with the Gemini Large Language Model.
    Initializes the Gemini API and provides methods for generating content.
    """
    def __init__(self, api_key: Optional[str] = None, model_name: str = 'gemini-2.5-flash', tts_service=None):
        """
        Initializes the LLMService.

        Args:
            api_key (Optional[str]): The Gemini API key. If None, it attempts to read
                                      from VOICE_ASSISTANT_GEMINI_API_KEY environment variable.
            model_name (str): The name of the Gemini model to use.
            tts_service: The Text-to-Speech service instance.
        """
        if api_key is None:
            api_key = os.environ.get("VOICE_ASSISTANT_GEMINI_API_KEY")

        if not api_key:
            logger.error("Gemini API key not provided and VOICE_ASSISTANT_GEMINI_API_KEY environment variable not set.")
            self.model = None
            raise ValueError("Gemini API key is required to initialize LLMService.")
        
        try:
            genai.configure(api_key=api_key)
            self.model = genai.GenerativeModel(model_name)
            self.tts_service = tts_service # Store the TTS service instance
            logger.info(f"LLMService initialized with model: {model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini model '{model_name}': {e}", exc_info=True)
            self.model = None
            raise RuntimeError(f"Could not initialize Gemini model: {e}")

    async def generate_response(self, prompt: str) -> Optional[str]:
        """
        Generates a text response from the Gemini model based on the given prompt.

        Args:
            prompt (str): The input text prompt for the LLM.

        Returns:
            Optional[str]: The generated text response, or None if an error occurred.
        """
        if self.model is None:
            logger.warning("LLMService model not initialized. Cannot generate response.")
            return None
        
        try:
            response = self.model.generate_content(prompt) 
            if hasattr(response, 'text'):
                logger.debug(f"Gemini raw response: {response}")
                return response.text
            else:
                logger.warning(f"Gemini response did not contain text. Blocked reason: {response.prompt_feedback.block_reason if response.prompt_feedback else 'N/A'}")
                return "I'm sorry, I couldn't generate a response for that."
        except Exception as e:
            logger.error(f"Error generating content from Gemini: {e}", exc_info=True)
            return f"An error occurred while getting AI response: {e}"

    async def stream_tts_response(self, prompt: str) -> AsyncGenerator[bytes, None]:
        """
        Generates an LLM response and then streams the audio of that response
        using the TTS service.
        """
        # First, generate the text response from the LLM
        llm_text = await self.generate_response(prompt)
        
        if llm_text:
            # Then, stream the audio of that text using the TTS service
            for chunk in self.tts_service.stream_audio(llm_text):
                yield chunk
        else:
            yield b"" # Yield an empty chunk if no LLM response