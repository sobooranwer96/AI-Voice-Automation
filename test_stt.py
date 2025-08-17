import os
from google.cloud import speech_v1 as speech
import io

# --- Configuration for Google Cloud Speech-to-Text ---
# This should match the audio file you'll use for testing.
# Google recommends 16000 Hz, 16-bit, mono channel, LINEAR16 encoding (WAV format).
SAMPLE_RATE_HERTZ = 16000
AUDIO_ENCODING = speech.RecognitionConfig.AudioEncoding.LINEAR16
LANGUAGE_CODE = "en-US"

# --- Path to your test audio file ---
# IMPORTANT: Replace 'path/to/your/test_audio.wav' with the actual path to your WAV file.
# Make sure this WAV file is 16kHz sample rate, mono channel, 16-bit PCM.
# You can record one using Audacity or find a sample online.
AUDIO_FILE_PATH = r"C:\repos\AI-Voice-Automation\untitled.wav" 

def transcribe_file(audio_file_path: str) -> str:
    """Transcribes a local audio file using Google Cloud Speech-to-Text."""
    try:
        # Instantiates a client
        client = speech.SpeechClient()

        # Loads the audio file into memory
        with io.open(audio_file_path, "rb") as audio_file:
            content = audio_file.read()
        audio = speech.RecognitionAudio(content=content)

        config = speech.RecognitionConfig(
            encoding=AUDIO_ENCODING,
            sample_rate_hertz=SAMPLE_RATE_HERTZ,
            language_code=LANGUAGE_CODE,
        )

        print(f"Sending audio file '{audio_file_path}' for transcription...")
        # Performs synchronous speech recognition
        response = client.recognize(config=config, audio=audio)

        transcript = ""
        for result in response.results:
            # The first alternative is the most likely transcription
            transcript += result.alternatives[0].transcript + " "

        if transcript:
            print(f"Transcription successful: {transcript.strip()}")
            return transcript.strip()
        else:
            print("No transcription results found.")
            return "No transcription found."

    except Exception as e:
        print(f"An error occurred during transcription: {e}")
        # Print full traceback for detailed error analysis
        import traceback
        traceback.print_exc()
        return f"Error: {e}"

if __name__ == "__main__":
    # Ensure GOOGLE_APPLICATION_CREDENTIALS is set before running this script.
    # You can verify it by running: echo %GOOGLE_APPLICATION_CREDENTIALS% in your terminal.
    if "GOOGLE_APPLICATION_CREDENTIALS" not in os.environ:
        print("Error: GOOGLE_APPLICATION_CREDENTIALS environment variable is not set.")
        print("Please set it to the path of your service account JSON key file.")
        print("Example (Windows): set GOOGLE_APPLICATION_CREDENTIALS=\"C:\\path\\to\\your\\google-cloud-key.json\"")
        print("Example (Linux/macOS): export GOOGLE_APPLICATION_CREDENTIALS=\"/path/to/your/google-cloud-key.json\"")
    else:
        print(f"GOOGLE_APPLICATION_CREDENTIALS is set to: {os.environ['GOOGLE_APPLICATION_CREDENTIALS']}")
        transcription_result = transcribe_file(AUDIO_FILE_PATH)
        print(f"\nFinal Result: {transcription_result}")

