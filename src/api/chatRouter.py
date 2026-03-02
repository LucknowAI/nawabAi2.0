import json
from http import HTTPStatus
import traceback

from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from fastapi.requests import Request
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from typing import Optional, Union, Dict, Any
from fastapi import Depends, HTTPException, status
from src.processors.queryProcessor import QueryProcessor
from src.auth.jwt_utils import get_current_user_id

from pydantic_ai.ui import SSE_CONTENT_TYPE, StateDeps
from pydantic_ai.ui.ag_ui import AGUIAdapter
from ag_ui.core.events import TextMessageContentEvent, TextMessageChunkEvent, RunFinishedEvent
from agent.main_agent import nawab_agent
# from src.tools.Whsiper import whisper_service
from datetime import datetime
import uuid
from src.utils.util_logger.logger import logger
from src.database.db import get_db
from sqlalchemy_models.chat import ConversationModel, ChatMessageModel

processor = QueryProcessor()

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000, description="The message to be processed.")
    
    class Config:
        json_schema_extra = {
            "example": {
                "message": "Hello, how are you?"
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
    user_id: int = Depends(get_current_user_id),
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
        
        # Save chat history via SQLAlchemy
        try:
            async with get_db() as db:
                conversation = ConversationModel(
                    user_id=user_id,
                    session_id=str(uuid.uuid4()),
                    status="active",
                    message_count=2,
                )
                db.add(conversation)
                await db.flush()  # populate conversation.id

                db.add(ChatMessageModel(
                    message_id=str(uuid.uuid4()),
                    conversation_id=conversation.id,
                    role="user",
                    content=request.message,
                ))
                db.add(ChatMessageModel(
                    message_id=str(uuid.uuid4()),
                    conversation_id=conversation.id,
                    role="assistant",
                    content=response.get("llm_response", str(response)),
                ))
                # commit happens automatically on __aexit__

        except Exception as db_error:
            # Log the error but don't fail the request
            logger.error(f"Failed to save chat to database: {db_error}")
            
        return ChatResponse(
            response=response,
            status="success"
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"An error occurred while processing the request: {str(e)}"
        )

@chat_router.post("/nawab")
async def nawab_agent_endpoint(
    request: Request,
    user_id: int = Depends(get_current_user_id),
) -> Response:
    """
    AG-UI compatible streaming endpoint backed by the Nawab pydantic-ai agent.
    Accepts an AG-UI RunAgentInput JSON body and streams back Server-Sent Events.
    """
    accept = request.headers.get("accept", SSE_CONTENT_TYPE)
    try:
        run_input = AGUIAdapter.build_run_input(await request.body())
    except ValidationError as e:
        return Response(
            content=json.dumps(e.errors()),
            media_type="application/json",
            status_code=HTTPStatus.UNPROCESSABLE_ENTITY,
        )

    adapter = AGUIAdapter(agent=nawab_agent, run_input=run_input, accept=accept)
    event_stream = adapter.run_stream(deps=StateDeps(state={}))

    async def capture_and_stream():
        """
        Passes every AG-UI event through to the client unchanged.
        Accumulates TextMessageChunkEvent deltas so the full assistant reply
        can be persisted to the database once RunFinishedEvent arrives.
        """
        assistant_text_parts: list[str] = []
        message_id: str | None = None

        async for event in event_stream:
            # collect text chunks — TextMessageContentEvent carries the actual delta
            if isinstance(event, (TextMessageContentEvent, TextMessageChunkEvent)):
                if message_id is None and event.message_id:
                    message_id = event.message_id
                if event.delta:
                    assistant_text_parts.append(event.delta)

            # stream is done — save to DB
            elif isinstance(event, RunFinishedEvent):
                full_response = "".join(assistant_text_parts)
                try:
                    # extract last user message from AG-UI input
                    user_text = ""
                    for msg in reversed(run_input.messages):
                        if msg.role == "user":
                            user_text = msg.content if isinstance(msg.content, str) else ""
                            break

                    # user_id comes from the verified JWT cookie
                    user_id_int = user_id

                    async with get_db() as db:
                        conversation = ConversationModel(
                            user_id=user_id_int,
                            session_id=str(uuid.uuid4()),
                            status="active",
                            message_count=2,
                        )
                        db.add(conversation)
                        await db.flush()  # populate conversation.id

                        db.add(ChatMessageModel(
                            message_id=str(uuid.uuid4()),
                            conversation_id=conversation.id,
                            role="user",
                            content=user_text,
                        ))
                        db.add(ChatMessageModel(
                            message_id=message_id or str(uuid.uuid4()),
                            conversation_id=conversation.id,
                            role="assistant",
                            content=full_response,
                        ))
                        # commit happens automatically on get_db().__aexit__

                    logger.info(f"Saved conversation {conversation.session_id!r} to DB")
                    # logger.info(f"Simulated saving chat session to DB: user_id={user_id_int}, session_id={session_id}, user_text={user_text!r}, assistant_response={full_response!r}")
                except Exception as db_error:
                    traceback.print_exc()
                    logger.error(f"Failed to save to DB: {db_error}")

            yield event  # always forward every event to the client

    sse_event_stream = adapter.encode_stream(capture_and_stream())
    return StreamingResponse(sse_event_stream, media_type=accept)



# @chat_router.post("/speech-to-text", response_model=SpeechToTextResponse)
# async def speech_to_text_endpoint(
#     audio_file: UploadFile = File(..., description="Audio file to transcribe"),
#     language: Optional[str] = Form(None, description="Language code (e.g., 'en', 'hi')"),
#     processor: QueryProcessor = Depends(lambda: QueryProcessor()),
# ):

#     try:
#         # Transcribe audio to text
#         transcribed_text = await whisper_service.transcribe_audio(
#             audio_file=audio_file,
#             language=language
#         )
        
#         if not transcribed_text:
#             raise HTTPException(
#                 status_code=400,
#                 detail="Could not transcribe audio. Please ensure the audio is clear and try again."
#             )
        
#         # Process the transcribed text to get chat response
#         chat_response = await processor.process_query(transcribed_text)
#         if isinstance(chat_response, str):
#             chat_response = {"llm_response": chat_response}

#         # Return SpeechToTextResponse instead of ChatResponse
#         return SpeechToTextResponse(
#             transcribed_text=transcribed_text,
#             status="success",
#             chat_response=chat_response
#         )
        
#     except HTTPException:
#         # Re-raise HTTP exceptions (validation errors, etc.)
#         raise
#     except Exception as e:
#         raise HTTPException(
#             status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#             detail=f"An error occurred during speech-to-text conversion: {str(e)}"
#         )