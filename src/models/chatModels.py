from typing import List, Optional, Dict, Literal
from datetime import datetime
from pydantic import BaseModel
from beanie import Document

class ChatMessage(BaseModel):
    message_id  : str
    role        : Literal["user", "assistant", "system"]
    content     : str
    timestamp   : datetime
    metadata    : Optional[Dict] = {}

class ChatSession(Document):  # Beanie document
    session_id    : str
    user_id       : str
    title         : Optional[str] = None
    created_at    : datetime
    updated_at    : datetime
    completed_at  : Optional[datetime] = None
    status        : Literal["active", "completed", "archived"]
    message_count : int = 0
    messages      : List[ChatMessage] = []
    metadata      : Optional[Dict] = {}

