# Milestone 5: Text-to-Speech (TTS) with ElevenLabs

### Goal
The goal of this milestone is to integrate ElevenLabs Text-to-Speech (TTS) into our FastAPI application. We will take the text response from Gemini, send it to the ElevenLabs API to synthesize audio, and then stream that audio back to the web browser client for playback. This completes the full conversational loop: Speech-to-Text -> LLM -> Text-to-Speech. 

### New Technologies
* **ElevenLabs API:** A leading platform for natural-sounding speech synthesis software that uses deep learning. It's known for its ability to produce lifelike speech by synthesizing vocal emotion and intonation in a variety of languages, including English, Spanish, German, and Japanese.
* **`elevenlabs` Python Client Library:** The official Python SDK for the ElevenLabs API, which provides a simple way to make API calls, including for streaming audio.

---

### Subtasks
1.  **ElevenLabs API Key Setup**: Obtain an ElevenLabs API key from your profile settings on their website and set it as a permanent environment variable (`VOICE_ASSISTANT_ELEVENLABS_API_KEY`). The API key is required for authentication in all API requests.
2.  **Install the ElevenLabs Python Client Library**: Install the official `elevenlabs` Python package.
3.  **Create a Text-to-Speech Service Module**: Create a new module (e.g., `app/services/text_to_speech.py`) to encapsulate all ElevenLabs TTS logic, including client initialization and a method to stream audio from text.
4.  **Modify the LLM Service to Call TTS**: Update the LLM service module to send Gemini's text response to the new TTS service. This is where we'll initiate the audio generation.
5.  **Update WebSocket Handler for ElevenLabs Audio**: Refactor the WebSocket endpoint to receive audio chunks from the TTS service and send them to the client for playback.
6.  **Update Client-Side HTML/JavaScript for Audio Playback**: Modify the JavaScript in our web client to receive and play back the streamed audio data from the WebSocket.
7.  **Test Full Conversational Loop**: Verify that the entire pipeline works by speaking into the microphone, seeing the transcription, and then hearing the AI's verbal response.