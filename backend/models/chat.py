from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import uuid

class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sender: str  # "user" | "assistant" | "system"
    content: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    
    # Internal envelope details
    skill_used: Optional[str] = None
    sources: Optional[List[Dict[str, Any]]] = None
    tool_steps: Optional[List[Dict[str, Any]]] = None  # Trace display items

class IdeaCanvas(BaseModel):
    value_prop: str = ""
    target_user: str = ""
    tech_stack: str = ""
    checklist: List[str] = Field(default_factory=list)
    scores: Dict[str, float] = Field(default_factory=lambda: {
        "novelty": 0.0,
        "feasibility": 0.0,
        "moat": 0.0,
        "market_signal": 0.0,
        "demo_ability": 0.0
    })
    updated_at: datetime = Field(default_factory=datetime.utcnow)

class Chat(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="_id")
    user_id: str
    messages: List[ChatMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    title: Optional[str] = None
    canvas: Optional[IdeaCanvas] = None
    canvas_history: List[IdeaCanvas] = Field(default_factory=list)

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "_id": "f8a7d6c5-4321-8765-fedc-ba9876543210",
                "user_id": "e0b8d5a1-7788-47fb-8ad9-df328325a51a",
                "messages": [
                    {
                        "id": "11111111-2222-3333-4444-555555555555",
                        "sender": "user",
                        "content": "Hi, I need a final year project idea.",
                        "timestamp": "2026-07-11T12:00:00Z"
                    },
                    {
                        "id": "22222222-3333-4444-5555-666666666666",
                        "sender": "assistant",
                        "content": "Sure, let's find you something unique. What are your skills?",
                        "timestamp": "2026-07-11T12:00:05Z"
                    }
                ],
                "created_at": "2026-07-11T12:00:00Z",
                "updated_at": "2026-07-11T12:00:05Z"
            }
        }
    }
