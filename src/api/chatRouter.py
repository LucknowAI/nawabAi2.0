import asyncio
import json
import pathlib
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
from ag_ui.core.events import (
    TextMessageContentEvent,
    TextMessageChunkEvent,
    TextMessageStartEvent,
    TextMessageEndEvent,
    ToolCallStartEvent,
    ToolCallArgsEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    RunStartedEvent,
    RunFinishedEvent,
    StepStartedEvent,
    StepFinishedEvent,
    StateSnapshotEvent,
    StateDeltaEvent,
    MessagesSnapshotEvent,
)
from agent.main_agent import nawab_agent
# from src.tools.Whsiper import whisper_service
from datetime import datetime, timezone
import uuid
from sqlalchemy import select
from sqlalchemy import func as sqlfunc
from src.utils.util_logger.logger import logger
from src.database.db import get_db, AsyncSessionFactory
from sqlalchemy_models.chat import ConversationModel, ChatMessageModel, AgUiEventModel

# Directory where raw event captures are written
_EVENT_LOG_DIR = pathlib.Path("query_logs")
_EVENT_LOG_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _snake_to_camel(s: str) -> str:
    """'thread_id' → 'threadId'  (single-level key conversion)."""
    parts = s.split("_")
    return parts[0] + "".join(p.capitalize() for p in parts[1:])


def _camelise(obj):
    """
    Recursively convert all dict keys from snake_case to camelCase.
    Drops keys whose value is None so Zod doesn't choke on unexpected nulls.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if v is None:
                continue          # drop null fields entirely
            out[_snake_to_camel(k)] = _camelise(v)
        return out
    if isinstance(obj, list):
        return [_camelise(i) for i in obj]
    return obj


def _patch_run_started(event: dict, input_messages: list) -> dict:
    """
    CopilotKit Zod schema requires RUN_STARTED to carry a full `input` object:
      { threadId, runId, messages, tools, context }
    We reconstruct it from the captured input_messages list.
    """
    thread_id = event.get("threadId", "")
    run_id    = event.get("runId", "")
    return {
        **event,
        "input": {
            "threadId": thread_id,
            "runId":    run_id,
            "messages": input_messages,
            "tools":    [],
            "context":  [],
        },
    }


def _messages_to_events(messages: list) -> list[dict]:
    """
    Converts raw input_messages (conversation history) into a synthetic AG-UI
    event list so the frontend can reconstruct every text message and tool call
    that happened before the current captured run.

    Emits:
      TEXT_MESSAGE_START / CONTENT / END  for assistant text turns
      TOOL_CALL_START / ARGS / END        for each tool call
      TOOL_CALL_RESULT                    for the matching tool-role message
                                          (required by CopilotKit to fire
                                           useCopilotAction render callback)
    """
    ts = 0
    events: list[dict] = []

    # Build a lookup: tool_call_id → tool result message
    tool_results: dict[str, dict] = {}
    for msg in messages:
        if msg.get("role") == "tool":
            tc_id = msg.get("toolCallId") or msg.get("tool_call_id") or ""
            if tc_id:
                tool_results[tc_id] = msg

    for msg in messages:
        role   = msg.get("role")
        msg_id = msg.get("id") or str(uuid.uuid4())

        if role != "assistant":
            continue

        content    = msg.get("content") or ""
        tool_calls = msg.get("toolCalls") or msg.get("tool_calls") or []

        # ── text content ──────────────────────────────────────────────────────
        if content:
            events.append({"type": "TEXT_MESSAGE_START",   "timestamp": ts, "messageId": msg_id, "role": "assistant"})
            ts += 1
            events.append({"type": "TEXT_MESSAGE_CONTENT", "timestamp": ts, "messageId": msg_id, "delta": content})
            ts += 1
            events.append({"type": "TEXT_MESSAGE_END",     "timestamp": ts, "messageId": msg_id})
            ts += 1

        # ── tool calls ────────────────────────────────────────────────────────
        for tc in tool_calls:
            tc_id   = tc.get("id", str(uuid.uuid4()))
            fn      = tc.get("function", {})
            fn_name = fn.get("name", "unknown")
            args    = fn.get("arguments", "{}")

            events.append({
                "type":            "TOOL_CALL_START",
                "timestamp":       ts,
                "toolCallId":      tc_id,
                "toolCallName":    fn_name,
                "parentMessageId": msg_id,
            })
            ts += 1
            events.append({
                "type":       "TOOL_CALL_ARGS",
                "timestamp":  ts,
                "toolCallId": tc_id,
                "delta":      args,
            })
            ts += 1
            events.append({
                "type":       "TOOL_CALL_END",
                "timestamp":  ts,
                "toolCallId": tc_id,
            })
            ts += 1

            # TOOL_CALL_RESULT fires useCopilotAction's render callback
            result_msg = tool_results.get(tc_id)
            result_content = (result_msg.get("content") or "") if result_msg else ""
            result_msg_id  = result_msg.get("id", str(uuid.uuid4())) if result_msg else str(uuid.uuid4())
            events.append({
                "type":       "TOOL_CALL_RESULT",
                "timestamp":  ts,
                "messageId":  result_msg_id,
                "toolCallId": tc_id,
                "content":    result_content,
                "role":       "tool",
            })
            ts += 1

    return events


def _serialise_event(event) -> dict:
    """Convert any AG-UI / pydantic-ai event to a plain dict for JSON storage."""
    try:
        # pydantic v2 BaseModel
        return event.model_dump(mode="json")
    except AttributeError:
        pass
    try:
        # pydantic v1 BaseModel
        return event.dict()
    except AttributeError:
        pass
    # plain dataclass / namedtuple / dict fallback
    return vars(event) if hasattr(event, "__dict__") else str(event)

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


# ── Mock / Replay endpoints ───────────────────────────────────────────────────

@chat_router.get("/mock/conversations")
async def list_mock_conversations(
    user_id: int = Depends(get_current_user_id),
):
    """
    Returns a list of captured event-log files available for replay testing.
    Use the returned `id` values with POST /chat/mock/replay/{id}.
    """
    files = sorted(_EVENT_LOG_DIR.glob("events_*.json"), reverse=True)
    result = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            # pick the last user message as a title preview
            preview = ""
            for msg in reversed(data.get("input_messages", [])):
                if msg.get("role") == "user":
                    preview = (msg.get("content") or "")[:120]
                    break
            result.append({
                "id": f.stem,                              # e.g. events_20260302T003743_f5319da1
                "captured_at": data.get("captured_at"),
                "preview": preview,
                "event_count": len(data.get("events", [])),
            })
        except Exception as parse_err:
            logger.warning(f"Skipping {f.name}: {parse_err}")
    return result


@chat_router.post("/mock/replay/{capture_id}")
async def replay_mock_conversation(
    capture_id: str,
    user_id: int = Depends(get_current_user_id),
    delay_ms: int = 0,
):
    """
    Streams a previously captured AG-UI event log back as real SSE.
    The frontend receives the exact same event stream as a live agent run.

    Workflow:
      1. GET /chat/mock/conversations          → pick a capture `id`
      2. POST /chat/mock/replay/<id>           → streams that conversation
      3. Optional ?delay_ms=30                 → adds delay between events
         for a realistic streaming effect.
    """
    capture_file = _EVENT_LOG_DIR / f"{capture_id}.json"
    if not capture_file.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Capture {capture_id!r} not found in query_logs/",
        )

    try:
        data = json.loads(capture_file.read_text(encoding="utf-8"))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Could not parse capture: {e}")

    # Extract the raw event_data dicts – these are already AG-UI compatible JSON
    event_payloads: list[dict] = [
        entry["event_data"] for entry in data.get("events", [])
    ]

    # Pre-camelise the input messages once
    camel_input_messages = [_camelise(m) for m in data.get("input_messages", [])]

    async def sse_stream():
        # 1. RUN_STARTED must always be the very first event
        for payload in event_payloads:
            camel = _camelise(payload)
            if camel.get("type") == "RUN_STARTED":
                yield f"data: {json.dumps(_patch_run_started(camel, camel_input_messages), default=str)}\n\n"
                break

        # 2. MESSAGES_SNAPSHOT — restores the full conversation thread
        #    (all prior messages including tool calls) in one event.
        #    CopilotKit renders these correctly without synthetic event sequences.
        if camel_input_messages:
            snapshot = {
                "type":      "MESSAGES_SNAPSHOT",
                "timestamp": 0,
                "messages":  camel_input_messages,
            }
            yield f"data: {json.dumps(snapshot, default=str)}\n\n"
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)

        # 3. remaining captured run events (skip the RUN_STARTED already sent)
        for payload in event_payloads:
            camel = _camelise(payload)
            if camel.get("type") == "RUN_STARTED":
                continue
            yield f"data: {json.dumps(camel, default=str)}\n\n"
            if delay_ms > 0:
                await asyncio.sleep(delay_ms / 1000)

    return StreamingResponse(
        sse_stream(),
        media_type=SSE_CONTENT_TYPE,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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

    Conversation persistence strategy
    ----------------------------------
    * Every AG-UI event is stored in ``ag_ui_events`` as it is emitted so the
      frontend can replay the full conversation after a page refresh.
    * The ``thread_id`` from the AG-UI payload becomes the ``session_id`` of a
      ``ConversationModel`` row, so all turns of one chat map to the same
      conversation in the database.
    * On the first turn the conversation row is created; subsequent turns from
      the same thread reuse it and append events with monotonically increasing
      sequence numbers.
    * The final assistant text is also written to ``chat_messages`` so
      human-readable history is available independently of event replay.
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

    # thread_id is sent by CopilotKit on every request for the same chat thread
    thread_id: str = (getattr(run_input, "thread_id", None) or str(uuid.uuid4()))

    adapter = AGUIAdapter(agent=nawab_agent, run_input=run_input, accept=accept)
    event_stream = adapter.run_stream(deps=StateDeps(state={}))

    async def capture_and_stream():
        """
        Streams every AG-UI event to the client while accumulating them in
        memory.  A single bulk write is performed after RunFinishedEvent:

          1. INSERT INTO ag_ui_events  – all events in one executemany query
          2. INSERT INTO chat_messages – user + assistant rows in one query
          3. UPDATE conversations      – bump message_count

        No DB I/O happens during streaming, keeping latency minimal.
        """
        from collections import Counter
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        assistant_text_parts: list[str] = []
        message_id: str | None = None
        captured_events: list[dict] = []   # {event_type, event_data}
        event_dicts:     list[dict] = []   # raw dicts for bulk insert
        conv_id: int | None = None
        next_sequence: int = 0

        # ── 1. Find or create the ConversationModel row ───────────────────────
        # Short-lived session committed before streaming starts so no connection
        # is held open while the agent is inferring.
        try:
            async with AsyncSessionFactory() as setup_db:
                result = await setup_db.execute(
                    select(ConversationModel)
                    .where(ConversationModel.session_id == thread_id)
                    .where(ConversationModel.user_id == user_id)
                )
                conv = result.scalar_one_or_none()

                if conv is None:
                    conv = ConversationModel(
                        user_id=user_id,
                        session_id=thread_id,
                        status="active",
                        message_count=0,
                    )
                    setup_db.add(conv)
                    await setup_db.flush()

                conv_id = conv.id

                # Find the next sequence offset (supports appending to existing runs)
                seq_result = await setup_db.execute(
                    select(sqlfunc.coalesce(sqlfunc.max(AgUiEventModel.sequence), -1))
                    .where(AgUiEventModel.conversation_id == conv_id)
                )
                next_sequence = (seq_result.scalar() or -1) + 1

                await setup_db.commit()
                logger.info(
                    f"[AG-UI] thread={thread_id!r} conv_id={conv_id} "
                    f"next_seq={next_sequence}"
                )
        except Exception as setup_err:
            traceback.print_exc()
            logger.error(f"[AG-UI] Failed to set up conversation row: {setup_err}")
            # conv_id stays None – events still stream but won't be persisted

        # ── 2. Stream – accumulate in memory, zero DB I/O ─────────────────────
        async for event in event_stream:
            event_class = type(event).__name__
            event_dict  = _serialise_event(event)

            captured_events.append({"event_type": event_class, "event_data": event_dict})
            event_dicts.append(event_dict)

            # accumulate assistant text
            if isinstance(event, (TextMessageContentEvent, TextMessageChunkEvent)):
                if message_id is None and event.message_id:
                    message_id = event.message_id
                if event.delta:
                    assistant_text_parts.append(event.delta)

            # ── 3. Stream finished – single bulk write ────────────────────────
            elif isinstance(event, RunFinishedEvent):
                full_response = "".join(assistant_text_parts)

                # debug JSON dump
                try:
                    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                    dump_path = _EVENT_LOG_DIR / f"events_{ts}_{uuid.uuid4().hex[:8]}.json"
                    type_summary = dict(Counter(e["event_type"] for e in captured_events))
                    logger.info(f"[AG-UI SUMMARY] {type_summary}")
                    dump_path.write_text(
                        json.dumps(
                            {
                                "captured_at": ts,
                                "user_id": user_id,
                                "thread_id": thread_id,
                                "conversation_id": conv_id,
                                "event_type_summary": type_summary,
                                "input_messages": [
                                    _serialise_event(m) for m in run_input.messages
                                ],
                                "events": captured_events,
                            },
                            indent=2,
                            default=str,
                        ),
                        encoding="utf-8",
                    )
                    logger.info(f"AG-UI event dump → {dump_path}")
                except Exception as dump_err:
                    logger.warning(f"Could not write event dump: {dump_err}")

                if conv_id is not None:
                    try:
                        user_text = ""
                        for msg in reversed(run_input.messages):
                            if msg.role == "user":
                                user_text = (
                                    msg.content
                                    if isinstance(msg.content, str)
                                    else ""
                                )
                                break

                        async with AsyncSessionFactory() as bulk_db:
                            # ── ag_ui_events: one INSERT … VALUES (…),(…),… ──
                            if event_dicts:
                                await bulk_db.execute(
                                    pg_insert(AgUiEventModel).values(
                                        [
                                            {
                                                "conversation_id": conv_id,
                                                "sequence": next_sequence + i,
                                                "event": ed,
                                            }
                                            for i, ed in enumerate(event_dicts)
                                        ]
                                    ).on_conflict_do_nothing()  # idempotent on retry
                                )

                            # ── chat_messages: one INSERT with two rows ───────
                            await bulk_db.execute(
                                ChatMessageModel.__table__.insert(),
                                [
                                    {
                                        "message_id":      str(uuid.uuid4()),
                                        "conversation_id": conv_id,
                                        "role":            "user",
                                        "content":         user_text,
                                    },
                                    {
                                        "message_id":      message_id or str(uuid.uuid4()),
                                        "conversation_id": conv_id,
                                        "role":            "assistant",
                                        "content":         full_response,
                                    },
                                ],
                            )

                            # ── conversations: bump message_count ─────────────
                            conv_row = await bulk_db.get(ConversationModel, conv_id)
                            if conv_row:
                                conv_row.message_count = (
                                    (conv_row.message_count or 0) + 2
                                )

                            await bulk_db.commit()

                        logger.info(
                            f"Bulk-saved {len(event_dicts)} events + 2 messages "
                            f"for conv_id={conv_id} session_id={thread_id!r}"
                        )
                    except Exception as db_error:
                        traceback.print_exc()
                        logger.error(f"Failed bulk DB write: {db_error}")

            yield event  # always forward every event to the client

    sse_event_stream = adapter.encode_stream(capture_and_stream())
    return StreamingResponse(sse_event_stream, media_type=accept)


# ── Conversation history / event-replay endpoints ─────────────────────────────

@chat_router.get("/conversations", summary="List user conversations")
async def list_conversations(
    user_id: int = Depends(get_current_user_id),
    limit: int = 50,
    offset: int = 0,
):
    """
    Returns all conversations belonging to the authenticated user, newest first.

    Each entry includes the ``thread_id`` (== ``session_id``), title, status,
    message count, and timestamps.  Pass ``thread_id`` to
    ``GET /chat/conversations/{thread_id}/events`` to replay a conversation.
    """
    async with AsyncSessionFactory() as db:
        result = await db.execute(
            select(ConversationModel)
            .where(ConversationModel.user_id == user_id)
            .order_by(ConversationModel.id.desc())
            .limit(limit)
            .offset(offset)
        )
        convs = result.scalars().all()

    return [
        {
            "thread_id":     c.session_id,
            "title":         c.title,
            "status":        c.status,
            "message_count": c.message_count,
            "created_at":    c.created_at.isoformat() if c.created_at else None,
            "updated_at":    c.updated_at.isoformat() if c.updated_at else None,
        }
        for c in convs
    ]


@chat_router.get(
    "/conversations/{thread_id}/events",
    summary="Get stored AG-UI events for a conversation (for replay)",
)
async def get_conversation_events(
    thread_id: str,
    user_id: int = Depends(get_current_user_id),
):
    """
    Returns the full sequence of AG-UI events stored for ``thread_id``.

    The frontend can feed these events to CopilotKit's ``runtime.replayEvents()``
    to reconstruct the chat UI exactly as it appeared when the conversation ran::

        const res = await fetch(`/api/chat/conversations/${threadId}/events`);
        const events = await res.json();
        runtime.replayEvents(events);

    Events are returned in ``sequence`` order.  Each element is the raw AG-UI
    event dict (e.g. ``{"type": "TEXT_MESSAGE_CONTENT", "delta": "Hello"}``).

    Raises **404** if the conversation does not exist or belongs to a different
    user.
    """
    async with AsyncSessionFactory() as db:
        # verify the conversation belongs to this user
        conv_result = await db.execute(
            select(ConversationModel)
            .where(ConversationModel.session_id == thread_id)
            .where(ConversationModel.user_id == user_id)
        )
        conv = conv_result.scalar_one_or_none()
        if conv is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Conversation {thread_id!r} not found.",
            )

        events_result = await db.execute(
            select(AgUiEventModel)
            .where(AgUiEventModel.conversation_id == conv.id)
            .order_by(AgUiEventModel.sequence)
        )
        events = events_result.scalars().all()

    return [ev.event for ev in events]


@chat_router.get(
    "/conversations/{thread_id}/messages",
    summary="Get human-readable messages for a conversation",
)
async def get_conversation_messages(
    thread_id: str,
    user_id: int = Depends(get_current_user_id),
):
    """
    Returns the ``chat_messages`` rows for a conversation in chronological
    order.  This is a lighter alternative to event replay when you only need
    the text content (e.g. for a summary view or mobile client).
    """
    async with AsyncSessionFactory() as db:
        conv_result = await db.execute(
            select(ConversationModel)
            .where(ConversationModel.session_id == thread_id)
            .where(ConversationModel.user_id == user_id)
        )
        conv = conv_result.scalar_one_or_none()
        if conv is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Conversation {thread_id!r} not found.",
            )

        msgs_result = await db.execute(
            select(ChatMessageModel)
            .where(ChatMessageModel.conversation_id == conv.id)
            .order_by(ChatMessageModel.timestamp)
        )
        msgs = msgs_result.scalars().all()

    return [
        {
            "message_id": m.message_id,
            "role":       m.role,
            "content":    m.content,
            "timestamp":  m.timestamp.isoformat() if m.timestamp else None,
        }
        for m in msgs
    ]


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