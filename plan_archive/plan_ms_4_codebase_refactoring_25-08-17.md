# Overall Project Plan

## Overall Goal
The goal of this project is to build a scalable, real-time audio streaming and processing application using a FastAPI WebSocket server. This application will serve as a core component for a professional product, allowing for continuous, low-latency audio communication and intelligent conversational responses.

---

## Milestone 4: Codebase Refactoring for Future Scalability

### Goal
The goal of this milestone is to reorganize the current monolithic `main.py` file into a modular, readable, and maintainable structure. This refactoring will not only separate existing functionalities but also **establish a clear architectural foundation for future features and external integrations**, such as phone call handling (e.g., Twilio, Vonage) and various business system integrations (e.g., Google Calendar, CRM, ticketing systems). This proactive organization will significantly ease future development, debugging, and expansion of our AI automation agency's offerings.

### New Technologies
* No new core technologies are introduced in this milestone. We are focusing on **architectural best practices** and **code organization** to support future technology integrations.

---

### Subtasks
1.  **Create Comprehensive Project Directory Structure**: Establish a logical and extensible folder structure. This will include:
    * `app/`: The main application package.
        * `app/core/`: For core application logic, configurations, and shared utilities (e.g., logging setup, common constants).
        * `app/services/`: For distinct AI service integrations (e.g., `speech_to_text.py`, `llm_service.py`, `text_to_speech.py`).
        * `app/api/`: For FastAPI routes and WebSocket endpoints (e.g., `websocket_routes.py`, `web_client_routes.py`).
        * `app/integrations/`: A dedicated package for external software integrations.
            * `app/integrations/calendar/`: For calendar services (e.g., `google_calendar.py`, `outlook_calendar.py`).
            * `app/integrations/crm/`: For CRM systems (e.g., `salesforce.py`, `hubspot.py`).
            * `app/integrations/telephony/`: For phone call platforms (e.g., `twilio_handler.py`, `vonage_handler.py`).
            * `app/integrations/utils.py`: Common utilities for integrations.
        * `app/utils/`: General utility functions that don't fit into `core` or specific services/integrations.
    * `tests/`: For unit and integration tests.
    * `config/`: For environment-specific configuration files (e.g., `.env.example`).
    * `scripts/`: For setup, deployment, or maintenance scripts.
2.  **Extract HTML Client**: Move the `HTML_CLIENT` string and the `@app.get("/")` route into a new module (e.g., `app/api/web_client_routes.py`). This module will handle serving the web interface.
3.  **Extract STT Worker Logic**: Move the `build_streaming_config`, `audio_requests_only_generator`, `full_requests_generator`, and `stt_worker` functions into a new module (e.g., `app/services/speech_to_text.py`). This module will encapsulate all Google STT logic.
4.  **Extract LLM Interaction Logic**: Move the Gemini initialization and `generate_content` call logic into a new module (e.g., `app/services/llm_service.py`). This module will be responsible for all LLM interactions.
5.  **Centralize WebSocket Endpoint**: Keep the core `@app.websocket("/ws")` endpoint in `app/api/websocket_routes.py`. Refactor its internal logic to import and utilize functions from the new `app/services/` modules, and prepare it to handle different message types for future TTS and integration responses.
6.  **Update Imports and Main App Entry Point**: Adjust all necessary `import` statements across `main.py` and the new modules to reflect the new file locations. The `main.py` will become a leaner entry point, primarily responsible for initializing FastAPI and including the various routers/modules.
7.  **Verify Functionality**: Run the refactored application and confirm that all existing functionality (real-time STT, Gemini LLM responses in logs) works exactly as it did before the refactoring. This step is crucial to ensure no functionality is broken during the reorganization.