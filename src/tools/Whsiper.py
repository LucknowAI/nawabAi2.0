import io
import logging
from typing import Optional, Union
from openai import OpenAI
from fastapi import UploadFile, HTTPException
from src.config.settings import Settings
from src.utils.validators import AudioValidator

logger = logging.getLogger(__name__)

class WhisperService:
    
    def __init__(self):
        if not Settings.OPENAI_API_KEY:
            raise ValueError("OpenAI API key not found in environment variables")
        
        self.client = OpenAI(api_key=Settings.OPENAI_API_KEY)
        self.supported_formats = {
            'audio/mpeg', 'audio/mp3', 'audio/mp4', 'audio/wav', 
            'audio/webm', 'audio/m4a', 'audio/ogg', 'audio/flac'
        }
        self.max_file_size = 25 * 1024 * 1024  # 25MB limit (OpenAI's limit)
    
    async def transcribe_audio(self, audio_file: UploadFile, language: Optional[str] = None, prompt: Optional[str] = None) -> str:
        try:
            # Validate audio file
            is_valid, error_message = AudioValidator.validate_audio_file(audio_file)
            if not is_valid:
                raise HTTPException(status_code=400, detail=error_message)
            
            # Sanitize language code
            language = AudioValidator.sanitize_language_code(language)
            
            # Read file content
            audio_content = await audio_file.read()
            
            if not audio_content:
                raise HTTPException(
                    status_code=400,
                    detail="Empty audio file received"
                )
        
            audio_buffer = io.BytesIO(audio_content)
            audio_buffer.name = audio_file.filename or "audio.wav"
            
            transcription_params = {
                "file": audio_buffer,
                "model": "whisper-1",
                "response_format": "text"
            }
    
            if language:
                transcription_params["language"] = language
            if prompt:
                transcription_params["prompt"] = prompt
            
            # Perform transcription
            transcript = self.client.audio.transcriptions.create(**transcription_params)
            
            logger.info(f"Successfully transcribed audio file: {audio_file.filename}")
            return transcript.strip()
            
        except Exception as e:
            error_str = str(e)
            logger.error(f"Error transcribing audio: {error_str}")
            
            # Handle specific OpenAI API errors
            if "insufficient_quota" in error_str or "quota" in error_str.lower():
                raise HTTPException(
                    status_code=402,  # Payment Required
                    detail="OpenAI quota exceeded. Please add credits to your OpenAI account at https://platform.openai.com/account/billing"
                )
            elif "401" in error_str or "invalid_api_key" in error_str:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid OpenAI API key. Please check your API key configuration."
                )
            elif "429" in error_str or "rate_limit" in error_str.lower():
                raise HTTPException(
                    status_code=429,
                    detail="OpenAI rate limit exceeded. Please wait a moment and try again."
                )
            else:
                raise HTTPException(
                    status_code=500,
                    detail=f"Failed to transcribe audio: {error_str}"
                )


whisper_service = WhisperService()
