import re
from typing import Optional, Set, Tuple
from fastapi import UploadFile

class AuthValidator:

    @staticmethod
    def validate_email(email: str) -> bool:
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        return bool(re.match(pattern, email))

    @staticmethod
    def validate_password_length(password: str) -> tuple[bool, Optional[str]]:
        if len(password) < 8:
            return False, "Password must be at least 8 characters long"
        if not re.search(r'[A-Z]', password):
            return False, "Password must contain at least one uppercase letter"
        if not re.search(r'[a-z]', password):
            return False, "Password must contain at least one lowercase letter"
        if not re.search(r'\d', password):
            return False, "Password must contain at least one digit"
        if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
            return False, "Password must contain at least one special character"
        return True, None

    @staticmethod
    def sanitize_string(value: str) -> str:
        return value.strip()[:100]

class AudioValidator:
    """Validator for audio file uploads."""
    
    SUPPORTED_FORMATS: Set[str] = {
        'audio/mpeg', 'audio/mp3', 'audio/mp4', 'audio/wav', 
        'audio/webm', 'audio/m4a', 'audio/ogg', 'audio/flac'
    }
    
    SUPPORTED_EXTENSIONS: Set[str] = {
        '.mp3', '.wav', '.mp4', '.m4a', '.webm', '.ogg', '.flac'
    }
    
    MAX_FILE_SIZE: int = 25 * 1024 * 1024  # 25MB
    
    @classmethod
    def validate_audio_file(cls, audio_file: UploadFile) -> Tuple[bool, Optional[str]]:

        # Check file size
        if audio_file.size and audio_file.size > cls.MAX_FILE_SIZE:
            return False, f"File too large. Maximum size is {cls.MAX_FILE_SIZE / (1024*1024):.1f}MB"
        
        # Check content type
        if audio_file.content_type not in cls.SUPPORTED_FORMATS:
            return False, f"Unsupported audio format. Supported formats: {', '.join(cls.SUPPORTED_FORMATS)}"
        
        # Check filename extension
        if audio_file.filename:
            file_extension = f".{audio_file.filename.lower().split('.')[-1]}"
            if file_extension not in cls.SUPPORTED_EXTENSIONS:
                return False, f"Unsupported file extension. Supported extensions: {', '.join(cls.SUPPORTED_EXTENSIONS)}"
        
        return True, None
        
    @staticmethod
    def sanitize_language_code(language: Optional[str]) -> Optional[str]:
        """Sanitize and validate language code."""
        if not language:
            return None
        
        # Remove any non-alphabetic characters and convert to lowercase
        sanitized = re.sub(r'[^a-zA-Z]', '', language.strip().lower())
        
        # Return first 2 characters (ISO 639-1 format)
        return sanitized[:2] if sanitized else None