from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from typing import Optional, Union, Dict, Any
from fastapi import Depends, HTTPException, status
from src.processors.queryProcessor import QueryProcessor

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
