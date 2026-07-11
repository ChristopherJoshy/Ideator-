from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field
import uuid
from backend.models.idea import IdeaDNA

class Hackathon(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="_id")
    name: str
    platform: str  # "Devpost" | "Devfolio" | "MLH" | "Unstop"
    deadline: datetime
    theme: str
    url: str
    scraped_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "_id": "h1a2b3c4-9999-8888-7777-666655554444",
                "name": "HackMIT 2026",
                "platform": "Devpost",
                "deadline": "2026-09-15T23:59:59Z",
                "theme": "AI, Web3, Education",
                "url": "https://hackmit2026.devpost.com",
                "scraped_at": "2026-07-11T12:00:00Z"
            }
        }
    }

class PastWinner(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), alias="_id")
    hackathon_id: Optional[str] = None  # Reference to Hackathon (if applicable)
    project_title: str
    description_raw: str
    idea_dna: IdeaDNA
    source_url: str
    scraped_at: datetime = Field(default_factory=datetime.utcnow)

    model_config = {
        "populate_by_name": True,
        "json_schema_extra": {
            "example": {
                "_id": "w9z8y7x6-1111-2222-3333-444455556666",
                "hackathon_id": "h1a2b3c4-9999-8888-7777-666655554444",
                "project_title": "EduChain",
                "description_raw": "A decentralized platform for credential verification in education.",
                "idea_dna": {
                    "domain": "Education/Web3",
                    "mechanism": "Credential verification on-chain",
                    "stack": ["React", "Solidity", "IPFS"],
                    "target_user": "Universities"
                },
                "source_url": "https://devpost.com/software/educhain",
                "scraped_at": "2026-07-11T12:00:00Z"
            }
        }
    }
