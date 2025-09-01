# AI Automation Agency: Voice Agent Project Context

### 1. Project Goal
The primary goal is to build and launch a scalable, real-time AI voice automation agent. This agent will handle two-way conversations and eventually integrate with various business systems (e.g., calendars, CRMs).

### 2. Technical Stack
* **Web Framework:** FastAPI (with Uvicorn)
* **Real-time Communication:** WebSockets
* **Speech-to-Text (STT):** Google Cloud Speech-to-Text API
* **Large Language Model (LLM):** Gemini API (`gemini-2.5-flash`)
* **Text-to-Speech (TTS):** ElevenLabs API

### 3. API Keys and Environment Variables
The following environment variables are required and have been set up for local development:
* `GOOGLE_APPLICATION_CREDENTIALS`: Path to the Google Cloud service account JSON key for STT.
* `VOICE_ASSISTANT_GEMINI_API_KEY`: Gemini API key for the LLM.
* `VOICE_ASSISTANT_ELEVENLABS_API_KEY`: ElevenLabs API key for TTS.

### 4. Codebase Status
The project has been successfully refactored into a modular and scalable directory structure. All core logic has been moved out of `main.py` into their respective service files.

* `main.py`: This is the lean entry point. It sets up FastAPI, initializes global service instances (LLM and TTS), and includes the API routes.
* `app/api/web_client_routes.py`: Contains the HTML/JavaScript for the browser-based client and the root (`/`) endpoint.
* `app/api/websocket_routes.py`: Contains the core WebSocket logic (`/ws`) that orchestrates the entire conversational pipeline.
* `app/services/speech_to_text.py`: Manages all interaction with the Google Cloud Speech-to-Text API. It runs in a background thread to handle streaming audio.
* `app/services/llm_service.py`: Encapsulates all interaction with the Gemini LLM. It generates text responses from final transcriptions.
* `app/services/text_to_speech.py`: Manages all interaction with the ElevenLabs TTS API. It streams audio back from text input.

### 5. Current Issue
The entire pipeline works, but the browser client does not play the audio. The server logs confirm that audio is being successfully streamed from ElevenLabs, but it appears there's a bug in the client-side JavaScript preventing playback.

### 6. Planned Next Steps
The next milestone is to debug and fix the client-side JavaScript to properly receive and play back the streamed audio from the WebSocket. Once playback is working, this milestone will be complete. After that, we'll begin integrating a telephone service like Twilio.

### 7. Files for Context
You should provide the following files to the new chat to continue:
* `main.py`
* `app/api/web_client_routes.py`
* `app/api/websocket_routes.py`
* `app/services/llm_service.py`
* `app/services/speech_to_text.py`
* `app/services/text_to_speech.py`
* All `plan.md` files from our previous milestones.

This complete context will allow a new conversation to start with all the same knowledge we've built together.