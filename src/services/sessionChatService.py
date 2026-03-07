"""
Session Chat Service
=====================

WHY THIS SERVICE IS NEEDED:
---------------------------
This service is the central orchestrator for all chat-related operations.
It handles the complex logic of:

1. **Dual Storage Strategy**:
   - Redis: Fast cache for active sessions and recent messages
   - PostgreSQL: Persistent storage for all data
   
2. **Context Management**:
   - Keeps track of conversation history
   - Generates summaries when conversations get too long
   - Provides context to the LLM for coherent responses
   
3. **Session Lifecycle**:
   - Create new sessions
   - Add messages
   - Complete/archive sessions
   - List user's sessions

WHAT IT SOLVES:
---------------
- Decouples chat logic from API endpoints
- Ensures data consistency between cache and database
- Manages the complexity of context windows
- Provides a clean interface for the chat router

ARCHITECTURE:
-------------
┌─────────────┐     ┌──────────────────┐     ┌─────────┐
│ Chat Router │────>│ SessionChatService│────>│  Redis  │ (fast cache)
└─────────────┘     └──────────────────┘     └─────────┘
                            │                      
                            v                      
                    ┌──────────────┐               
                    │  PostgreSQL  │ (persistent)  
                    └──────────────┘               
"""

from typing import List, Optional, Dict, Any, Tuple
from datetime import datetime, timezone
from sqlalchemy import select, update, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
import uuid
import logging

from src.database.postgres import get_db_context
from src.database.redis import redis_manager
from src.models.sqlalchemy_models import (
    ChatSession, ChatMessage, ContextSummary,
    SessionStatus, MessageRole
)
from src.config.settings import settings
from src.languageModel.llms.lite_llm import LiteLLMClient

logger = logging.getLogger(__name__)


class SessionChatService:
    """
    Chat Session Management Service
    --------------------------------
    
    This service manages the complete lifecycle of chat sessions.
    
    KEY RESPONSIBILITIES:
    1. Create and manage chat sessions
    2. Store and retrieve messages
    3. Generate and manage context summaries
    4. Provide conversation context for LLM calls
    
    USAGE:
    ```python
    service = SessionChatService()
    
    # Create a new session
    session = await service.create_session(db, user_id)
    
    # Add messages
    await service.add_message(db, session.id, "user", "Hello!")
    await service.add_message(db, session.id, "assistant", "Hi there!")
    
    # Get context for LLM
    context = await service.get_conversation_context(db, session.id)
    ```
    """
    
    def __init__(self):
        # LLM client for generating summaries
        self.llm_client = LiteLLMClient(
            api_key=settings.GEMINI_API_KEY,
            model_name=settings.SUMMARY_LLM_MODEL
        )
    
    # =========================================
    # SESSION MANAGEMENT
    # =========================================
    
    async def create_session(
        self, 
        db: AsyncSession, 
        user_id: str,
        title: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> ChatSession:
        """
        Create a new chat session for a user.
        
        WHY TWO STORAGE LOCATIONS:
        - PostgreSQL: Permanent record, survives restarts
        - Redis: Fast access for active conversations
        
        Args:
            db: Database session
            user_id: ID of the user creating the session
            title: Optional title (auto-generated if not provided)
            metadata: Optional additional data
            
        Returns:
            ChatSession: The created session
        """
        try:
            # Create session in PostgreSQL
            session = ChatSession(
                id=uuid.uuid4(),
                user_id=uuid.UUID(user_id) if isinstance(user_id, str) else user_id,
                title=title,
                status=SessionStatus.ACTIVE,
                metadata=metadata or {},
                message_count=0,
                messages_since_summary=0
            )
            
            db.add(session)
            await db.flush()  # Get the ID without committing
            
            # Cache in Redis for fast access
            await redis_manager.cache_session(
                session_id=str(session.id),
                user_id=str(user_id),
                data={
                    "title": title,
                    "metadata": metadata or {}
                }
            )
            
            logger.info(f"Created session {session.id} for user {user_id}")
            return session
            
        except Exception as e:
            logger.error(f"Error creating session: {str(e)}")
            raise
    
    async def get_session(
        self, 
        db: AsyncSession, 
        session_id: str,
        include_messages: bool = False
    ) -> Optional[ChatSession]:
        """
        Retrieve a session by ID.
        
        First checks Redis cache, falls back to PostgreSQL.
        
        Args:
            db: Database session
            session_id: UUID of the session
            include_messages: Whether to eager load messages
            
        Returns:
            ChatSession or None
        """
        try:
            session_uuid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
            
            query = select(ChatSession).where(
                and_(
                    ChatSession.id == session_uuid,
                    ChatSession.is_deleted == False
                )
            )
            
            if include_messages:
                query = query.options(selectinload(ChatSession.messages))
            
            result = await db.execute(query)
            return result.scalar_one_or_none()
            
        except Exception as e:
            logger.error(f"Error retrieving session {session_id}: {str(e)}")
            return None
    
    async def get_user_sessions(
        self, 
        db: AsyncSession, 
        user_id: str,
        status: Optional[SessionStatus] = None,
        limit: int = 20,
        offset: int = 0
    ) -> List[ChatSession]:
        """
        Get all sessions for a user.
        
        Ordered by last activity (most recent first).
        
        Args:
            db: Database session
            user_id: User's ID
            status: Optional filter by status
            limit: Maximum sessions to return
            offset: For pagination
            
        Returns:
            List of ChatSession objects
        """
        try:
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
            
            query = select(ChatSession).where(
                and_(
                    ChatSession.user_id == user_uuid,
                    ChatSession.is_deleted == False
                )
            )
            
            if status:
                query = query.where(ChatSession.status == status)
            
            query = query.order_by(ChatSession.last_activity.desc())
            query = query.limit(limit).offset(offset)
            
            result = await db.execute(query)
            return list(result.scalars().all())
            
        except Exception as e:
            logger.error(f"Error retrieving sessions for user {user_id}: {str(e)}")
            return []
    
    async def update_session(
        self, 
        db: AsyncSession, 
        session_id: str,
        updates: Dict[str, Any]
    ) -> bool:
        """
        Update session properties.
        
        Updates both PostgreSQL and Redis cache.
        """
        try:
            session_uuid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
            
            # Update in PostgreSQL
            await db.execute(
                update(ChatSession)
                .where(ChatSession.id == session_uuid)
                .values(**updates, updated_at=datetime.now(timezone.utc))
            )
            
            # Update Redis cache
            await redis_manager.update_session(session_id, updates)
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating session {session_id}: {str(e)}")
            return False
    
    async def complete_session(
        self, 
        db: AsyncSession, 
        session_id: str
    ) -> bool:
        """
        Mark a session as completed.
        
        This is called when:
        - User explicitly ends the chat
        - Session times out
        - User starts a new conversation
        """
        try:
            session_uuid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
            now = datetime.now(timezone.utc)
            
            # Update PostgreSQL
            await db.execute(
                update(ChatSession)
                .where(ChatSession.id == session_uuid)
                .values(
                    status=SessionStatus.COMPLETED,
                    completed_at=now,
                    updated_at=now
                )
            )
            
            # Get session data from Redis before invalidating (for archival)
            session_data = await redis_manager.get_session(session_id)
            
            # Remove from Redis cache
            if session_data:
                await redis_manager.invalidate_session(
                    session_id, 
                    session_data.get("user_id")
                )
            
            logger.info(f"Completed session {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error completing session {session_id}: {str(e)}")
            return False
    
    async def delete_session(
        self, 
        db: AsyncSession, 
        session_id: str,
        user_id: str
    ) -> bool:
        """
        Soft delete a session.
        
        WHY SOFT DELETE:
        - Preserves audit trail
        - Allows recovery if needed
        - Required for some compliance standards
        """
        try:
            session_uuid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
            
            await db.execute(
                update(ChatSession)
                .where(ChatSession.id == session_uuid)
                .values(
                    is_deleted=True,
                    updated_at=datetime.now(timezone.utc)
                )
            )
            
            # Remove from Redis
            await redis_manager.invalidate_session(session_id, user_id)
            
            logger.info(f"Deleted session {session_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting session {session_id}: {str(e)}")
            return False
    
    # =========================================
    # MESSAGE MANAGEMENT
    # =========================================
    
    async def add_message(
        self, 
        db: AsyncSession, 
        session_id: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        token_count: Optional[int] = None
    ) -> ChatMessage:
        """
        Add a message to a session.
        
        This is the core method called for every user message and AI response.
        
        FLOW:
        1. Create message in PostgreSQL (permanent storage)
        2. Add to Redis cache (fast context retrieval)
        3. Update session counters
        4. Check if summarization is needed
        
        Args:
            db: Database session
            session_id: Session to add message to
            role: "user", "assistant", or "system"
            content: The message text
            metadata: Optional additional data (sources, language, etc.)
            token_count: Estimated token count for this message
            
        Returns:
            The created ChatMessage
        """
        try:
            session_uuid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
            
            # Determine role enum
            role_enum = MessageRole(role) if isinstance(role, str) else role
            
            # Create message in PostgreSQL
            message = ChatMessage(
                id=uuid.uuid4(),
                session_id=session_uuid,
                role=role_enum,
                content=content,
                metadata=metadata or {},
                token_count=token_count
            )
            
            db.add(message)
            await db.flush()
            
            # Update session counters
            await db.execute(
                update(ChatSession)
                .where(ChatSession.id == session_uuid)
                .values(
                    message_count=ChatSession.message_count + 1,
                    messages_since_summary=ChatSession.messages_since_summary + 1,
                    last_activity=datetime.now(timezone.utc),
                    updated_at=datetime.now(timezone.utc)
                )
            )
            
            # Add to Redis cache
            await redis_manager.add_message_to_cache(
                session_id=session_id,
                role=role,
                content=content,
                metadata=metadata
            )
            
            # Check if we need to generate a summary
            session = await self.get_session(db, session_id)
            if session and session.messages_since_summary >= settings.MESSAGES_BEFORE_SUMMARY:
                # Trigger summary generation (async, don't block)
                await self._maybe_generate_summary(db, session_id)
            
            logger.debug(f"Added {role} message to session {session_id}")
            return message
            
        except Exception as e:
            logger.error(f"Error adding message to session {session_id}: {str(e)}")
            raise
    
    async def get_messages(
        self, 
        db: AsyncSession, 
        session_id: str,
        limit: int = 50,
        before_id: Optional[str] = None
    ) -> List[ChatMessage]:
        """
        Get messages for a session with pagination.
        
        Messages are returned in chronological order (oldest first).
        
        Args:
            db: Database session
            session_id: Session ID
            limit: Maximum messages to return
            before_id: For pagination, get messages before this ID
            
        Returns:
            List of ChatMessage objects
        """
        try:
            session_uuid = uuid.UUID(session_id) if isinstance(session_id, str) else session_id
            
            query = select(ChatMessage).where(
                ChatMessage.session_id == session_uuid
            )
            
            if before_id:
                before_uuid = uuid.UUID(before_id)
                # Get the timestamp of the before_id message
                before_msg = await db.execute(
                    select(ChatMessage.created_at).where(ChatMessage.id == before_uuid)
                )
                before_time = before_msg.scalar_one_or_none()
                if before_time:
                    query = query.where(ChatMessage.created_at < before_time)
            
            query = query.order_by(ChatMessage.created_at.asc())
            query = query.limit(limit)
            
            result = await db.execute(query)
            return list(result.scalars().all())
            
        except Exception as e:
            logger.error(f"Error retrieving messages for session {session_id}: {str(e)}")
            return []
    
    # =========================================
    # CONTEXT MANAGEMENT
    # =========================================
    
    async def get_conversation_context(
        self, 
        db: AsyncSession, 
        session_id: str,
        max_messages: int = None
    ) -> List[Dict[str, str]]:
        """
        Get conversation context for LLM call.
        
        This is the KEY METHOD that provides context to the AI.
        
        STRATEGY:
        1. If there's a summary, include it as a system message
        2. Add recent messages from cache (Redis)
        3. If cache miss, fetch from PostgreSQL
        
        FORMAT RETURNED:
        [
            {"role": "system", "content": "[Previous context summary]..."},
            {"role": "user", "content": "User's message"},
            {"role": "assistant", "content": "AI's response"},
            ...
        ]
        
        WHY THIS MATTERS:
        - LLMs have limited context windows
        - We need to provide relevant history
        - Summary + recent messages = best of both worlds
        """
        max_msgs = max_messages or settings.MAX_CONTEXT_MESSAGES
        context = []
        
        try:
            # First, try to get from Redis (fast)
            cached_messages = await redis_manager.get_session_messages(
                session_id, 
                limit=max_msgs
            )
            
            if cached_messages:
                # Get session for summary
                cached_session = await redis_manager.get_session(session_id)
                summary = cached_session.get("context_summary") if cached_session else None
                
                # Add summary as system message if available
                if summary:
                    context.append({
                        "role": "system",
                        "content": f"[Previous conversation summary]: {summary}"
                    })
                
                # Add cached messages
                for msg in cached_messages:
                    context.append({
                        "role": msg.get("role", "user"),
                        "content": msg.get("content", "")
                    })
                
                return context
            
            # Fallback: Fetch from PostgreSQL
            session = await self.get_session(db, session_id)
            if not session:
                return []
            
            # Add summary if available
            if session.context_summary:
                context.append({
                    "role": "system",
                    "content": f"[Previous conversation summary]: {session.context_summary}"
                })
            
            # Get recent messages
            messages = await self.get_messages(db, session_id, limit=max_msgs)
            for msg in messages:
                context.append(msg.to_llm_format())
            
            return context
            
        except Exception as e:
            logger.error(f"Error getting context for session {session_id}: {str(e)}")
            return []
    
    async def _maybe_generate_summary(
        self, 
        db: AsyncSession, 
        session_id: str
    ) -> Optional[str]:
        """
        Generate a summary if the conversation is long enough.
        
        This is called automatically when messages_since_summary exceeds threshold.
        
        WHY SUMMARIZATION:
        - LLM context windows are limited (4K, 8K, 128K tokens)
        - Long conversations need compression
        - Summaries preserve key information while saving tokens
        """
        try:
            session = await self.get_session(db, session_id, include_messages=True)
            if not session:
                return None
            
            # Get messages to summarize (all except the most recent ones)
            messages_to_summarize = []
            messages_to_keep = []
            all_messages = list(session.messages)
            
            keep_count = settings.MAX_CONTEXT_MESSAGES // 2  # Keep half in full
            
            if len(all_messages) > keep_count:
                messages_to_summarize = all_messages[:-keep_count]
                messages_to_keep = all_messages[-keep_count:]
            else:
                return None  # Not enough messages to summarize
            
            # Create conversation text for summarization
            conversation_text = "\n".join([
                f"{msg.role.value}: {msg.content}" 
                for msg in messages_to_summarize
            ])
            
            # Generate summary using LLM
            summary_prompt = f"""Summarize the following conversation between a user and Nawab (a Lucknow AI assistant).
Keep the key topics discussed, any important information shared, and the overall context.
Be concise but preserve important details.

Conversation:
{conversation_text}

Summary:"""
            
            summary = await self.llm_client.generate_response(summary_prompt)
            
            if not summary or "error" in summary.lower():
                logger.warning(f"Failed to generate summary for session {session_id}")
                return None
            
            # Save summary to database
            summary_record = ContextSummary(
                id=uuid.uuid4(),
                session_id=session.id,
                summary_text=summary,
                message_range={
                    "start_id": str(messages_to_summarize[0].id),
                    "end_id": str(messages_to_summarize[-1].id),
                    "count": len(messages_to_summarize)
                },
                model_used=settings.SUMMARY_LLM_MODEL
            )
            db.add(summary_record)
            
            # Update session with new summary
            await db.execute(
                update(ChatSession)
                .where(ChatSession.id == session.id)
                .values(
                    context_summary=summary,
                    last_summary_at=datetime.now(timezone.utc),
                    messages_since_summary=0
                )
            )
            
            # Update Redis cache
            await redis_manager.update_context_summary(session_id, summary)
            
            logger.info(f"Generated summary for session {session_id}: {len(messages_to_summarize)} messages summarized")
            return summary
            
        except Exception as e:
            logger.error(f"Error generating summary for session {session_id}: {str(e)}")
            return None
    
    # =========================================
    # HELPER METHODS
    # =========================================
    
    async def get_or_create_active_session(
        self, 
        db: AsyncSession, 
        user_id: str
    ) -> Tuple[ChatSession, bool]:
        """
        Get the user's active session or create a new one.
        
        BEHAVIOR:
        - If user has an active session with recent activity, return it
        - If session is stale (>24 hours), complete it and create new
        - If no active session, create new
        
        Returns:
            Tuple of (session, is_new)
        """
        try:
            # Get user's most recent active session
            sessions = await self.get_user_sessions(
                db, user_id, 
                status=SessionStatus.ACTIVE, 
                limit=1
            )
            
            if sessions:
                session = sessions[0]
                
                # Check if session is stale
                if session.last_activity:
                    time_since_activity = datetime.now(timezone.utc) - session.last_activity.replace(tzinfo=timezone.utc)
                    if time_since_activity.total_seconds() > settings.SESSION_TIMEOUT:
                        # Complete the stale session
                        await self.complete_session(db, str(session.id))
                    else:
                        return session, False
            
            # Create new session
            new_session = await self.create_session(db, user_id)
            return new_session, True
            
        except Exception as e:
            logger.error(f"Error in get_or_create_active_session: {str(e)}")
            # Create new session as fallback
            new_session = await self.create_session(db, user_id)
            return new_session, True
    
    async def get_session_stats(
        self, 
        db: AsyncSession, 
        user_id: str
    ) -> Dict[str, Any]:
        """
        Get statistics about a user's sessions.
        
        Useful for user dashboards and analytics.
        """
        try:
            user_uuid = uuid.UUID(user_id) if isinstance(user_id, str) else user_id
            
            # Count total sessions
            total_count = await db.execute(
                select(func.count(ChatSession.id))
                .where(
                    and_(
                        ChatSession.user_id == user_uuid,
                        ChatSession.is_deleted == False
                    )
                )
            )
            
            # Count by status
            active_count = await db.execute(
                select(func.count(ChatSession.id))
                .where(
                    and_(
                        ChatSession.user_id == user_uuid,
                        ChatSession.status == SessionStatus.ACTIVE,
                        ChatSession.is_deleted == False
                    )
                )
            )
            
            # Count total messages
            message_count = await db.execute(
                select(func.sum(ChatSession.message_count))
                .where(
                    and_(
                        ChatSession.user_id == user_uuid,
                        ChatSession.is_deleted == False
                    )
                )
            )
            
            return {
                "total_sessions": total_count.scalar() or 0,
                "active_sessions": active_count.scalar() or 0,
                "total_messages": message_count.scalar() or 0,
            }
            
        except Exception as e:
            logger.error(f"Error getting session stats: {str(e)}")
            return {
                "total_sessions": 0,
                "active_sessions": 0,
                "total_messages": 0,
            }


# =========================================
# GLOBAL INSTANCE
# =========================================

# Create a singleton instance
session_chat_service = SessionChatService()


async def get_session_chat_service() -> SessionChatService:
    """
    FastAPI Dependency for SessionChatService.
    
    Usage:
    ```python
    @router.post("/chat")
    async def chat(
        service: SessionChatService = Depends(get_session_chat_service)
    ):
        ...
    ```
    """
    return session_chat_service

