from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from pydantic import BaseModel, Field
from typing import Optional, Union, Dict, Any
from fastapi import Depends, HTTPException, status
from src.processors.queryProcessor import QueryProcessor
from src.tools.Whsiper import whisper_service

processor = QueryProcessor()

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000, description="The message to be processed.")
    user_id: Optional[str] = Field(None, description="Optional user ID for tracking.")
    
    class Config:
        json_schema_extra = {
            "example": {
                "message": "Hello, how are you?",
                "user_id": "12345"
            }
        }

class SpeechToTextRequest(BaseModel):
    transcribed_text: str
    user_id: Optional[str] = None
    auto_process: bool = Field(False, description="Whether to automatically process the transcribed text")

class SpeechToTextResponse(BaseModel):
    transcribed_text: str
    status: str = "success"
    chat_response: Optional[Dict[str, Any]] = None
    
class ChatResponse(BaseModel):
    response: Dict[str, Any]
    status: str = "success"
       
chat_router = APIRouter(
    prefix="/chat",
    tags=["Chat"],
    responses={404: {"description": "Not found"}},
)

@chat_router.get("/" , response_model=dict)
async def read_root():
    return {"message": "Welcome to the Chat API!"}


@chat_router.post("/", response_model=ChatResponse)
async def chat_endpoint(
    request: ChatRequest,
    processor: QueryProcessor = Depends(lambda: QueryProcessor()),
):
    """
    Process chat requests and return responses.
    
    Args:
        query (str): The query parameter from the URL
        request (ChatRequest): The request body containing the message
        processor (QueryProcessor): Query processor dependency
    
    Returns:
        ChatResponse: The processed response
        
    Raises:
        HTTPException: If the request is invalid or processing fails
    """
    
    # Simulate processing the request
    try: 
        if not request.message:
            raise HTTPException(
                status_code = status.HTTP_400_BAD_REQUEST,
                detail="Query and Message cannot be empty."
            )
            
        response = await processor.process_query(request.message)
        
        # Ensure response is a dictionary
        if isinstance(response, str):
            response = {"llm_response": response}
            
        return ChatResponse(
            response=response,
            status="success"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while processing the request: {str(e)}"
        )

@chat_router.post("/speech-to-text", response_model=SpeechToTextResponse)
async def speech_to_text_endpoint(
    audio_file: UploadFile = File(..., description="Audio file to transcribe"),
    language: Optional[str] = Form(None, description="Language code (e.g., 'en', 'hi')"),
    processor: QueryProcessor = Depends(lambda: QueryProcessor()),
):

    try:
        # Transcribe audio to text
        transcribed_text = await whisper_service.transcribe_audio(
            audio_file=audio_file,
            language=language
        )
        
        if not transcribed_text:
            raise HTTPException(
                status_code=400,
                detail="Could not transcribe audio. Please ensure the audio is clear and try again."
            )
        
        # Process the transcribed text to get chat response
        chat_response = await processor.process_query(transcribed_text)
        if isinstance(chat_response, str):
            chat_response = {"llm_response": chat_response}

        # Return SpeechToTextResponse instead of ChatResponse
        return SpeechToTextResponse(
            transcribed_text=transcribed_text,
            status="success",
            chat_response=chat_response
        )
        
    except HTTPException:
        # Re-raise HTTP exceptions (validation errors, etc.)
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred during speech-to-text conversion: {str(e)}"
        )