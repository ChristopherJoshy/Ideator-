from datetime import datetime
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

class VideoCache(BaseModel):
    id: str = Field(..., alias="_id")  # youtube video_id
    title: str
    channel: str
    views: int
    duration: str
    cached_at: datetime = Field(default_factory=datetime.utcnow)
    topic_tags: List[str] = Field(default_factory=list)

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "_id": "dQw4w9WgXcQ",
                "title": "Rick Astley - Never Gonna Give You Up",
                "channel": "Rick Astley",
                "views": 1200000000,
                "duration": "PT3M33S",
                "cached_at": "2026-07-11T12:00:00Z",
                "topic_tags": ["music", "pop", "classic"]
            }
        }
    }

class PaperCache(BaseModel):
    id: str = Field(..., alias="_id")  # custom or composite unique ID
    source: Literal["arxiv", "semanticscholar", "openalex", "core"]
    external_id: str  # ID in the source system (e.g. arXiv ID, Semantic Scholar paper ID)
    title: str
    tldr: Optional[str] = None
    citation_count: int = 0
    cached_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "_id": "arxiv_2303.11366",
                "source": "arxiv",
                "external_id": "2303.11366",
                "title": "Segment Anything",
                "tldr": "We introduce the Segment Anything project: a new task, dataset, and model for image segmentation.",
                "citation_count": 1500,
                "cached_at": "2026-07-11T12:00:00Z"
            }
        }
    }
