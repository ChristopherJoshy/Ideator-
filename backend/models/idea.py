from datetime import datetime
from typing import List, Optional, Literal
from pydantic import BaseModel, Field
import uuid

class IdeaDNA(BaseModel):
    domain: str
    mechanism: str
    stack: List[str]
    target_user: str

class Idea(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="_id")
    title: str
    description: str
    idea_dna: IdeaDNA
    embedding_ref: str  # ID in Qdrant vector store
    status: Literal["suggested", "shortlisted", "claimed", "abandoned", "shipped"] = "suggested"
    claimed_by: Optional[str] = None  # user_id
    claimed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "_id": "d1c2b3a4-1234-5678-abcd-ef0123456789",
                "title": "Decentralized Web Hosting",
                "description": "A peer-to-peer web hosting platform using IPFS.",
                "idea_dna": {
                    "domain": "Web3",
                    "mechanism": "Peer-to-peer sharing",
                    "stack": ["React", "Go", "IPFS"],
                    "target_user": "Developers"
                },
                "embedding_ref": "d1c2b3a4-1234-5678-abcd-ef0123456789",
                "status": "suggested",
                "claimed_by": None,
                "claimed_at": None,
                "expires_at": None,
                "created_at": "2026-07-11T12:00:00Z"
            }
        }
    }
