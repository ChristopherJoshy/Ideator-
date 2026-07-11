from datetime import datetime
from typing import List, Dict, Any
from pydantic import BaseModel, Field
import uuid

class User(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="_id")
    display_name: str
    skills: List[str] = Field(default_factory=list)
    past_projects: List[str] = Field(default_factory=list)
    preferences: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "_id": "e0b8d5a1-7788-47fb-8ad9-df328325a51a",
                "display_name": "Alice",
                "skills": ["Python", "Machine Learning"],
                "past_projects": ["Predictive Maintenance System"],
                "preferences": {"risk_appetite": "moderate", "timeline": "3 months"},
                "created_at": "2026-07-11T12:00:00Z"
            }
        }
    }
