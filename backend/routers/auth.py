import logging
from fastapi import APIRouter, Response, Request, HTTPException, Depends, status
from pydantic import BaseModel
from backend.db.mongodb import get_mongodb_db
from backend.models.user import User
from backend.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Authentication"])

class LoginRequest(BaseModel):
    display_name: str


class LoginResponse(BaseModel):
    message: str
    user: User


def _session_id_from_request(request: Request) -> str | None:
    """Read either supported session transport in one place."""
    session_id = request.cookies.get("session_id")
    if not session_id:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Session "):
            session_id = auth_header.removeprefix("Session ").strip()
    return session_id or None

async def get_current_user(request: Request) -> User:
    # The header fallback keeps sessions working when a frontend and API are on
    # different origins and the browser declines a third-party cookie.
    session_id = _session_id_from_request(request)

    if not session_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    
    db = get_mongodb_db()
    user_doc = await db.users.find_one({"_id": session_id})
    if not user_doc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalid or user not found"
        )
    
    return User(**user_doc)

@router.post("/login", response_model=LoginResponse, response_model_by_alias=False)
async def login(payload: LoginRequest, response: Response, request: Request):
    display_name = payload.display_name.strip()
    if not display_name:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Display name cannot be empty"
        )
    
    db = get_mongodb_db()
    
    # Keep an existing browser identity.  This is intentionally lightweight MVP
    # auth, but it must not create a new user (and empty chat history) on refresh.
    user_doc = None
    session_id = _session_id_from_request(request)
    if session_id:
        user_doc = await db.users.find_one({"_id": session_id})

    # Name login is the only credential in this MVP, so re-use that identity if
    # the browser has lost its cookie/local session.
    if not user_doc:
        user_doc = await db.users.find_one({"display_name": display_name})

    if user_doc:
        user = User(**user_doc)
    else:
        user = User(display_name=display_name)
        await db.users.insert_one(user.model_dump(by_alias=True))
    
    # Configure cookie based on env
    # Cross-site cookie requirements: samesite="none", secure=True
    # For localhost dev, samesite="lax", secure=False is fine
    # Let's support samesite="none" and secure=True for Vercel -> Ngrok setups
    is_prod_or_cross_site = settings.APP_ENV == "production" or "vercel.app" in settings.ALLOWED_ORIGINS or any("ngrok" in o for o in settings.ALLOWED_ORIGINS)
    
    response.set_cookie(
        key="session_id",
        value=user.id,
        httponly=True,
        samesite="none" if is_prod_or_cross_site else "lax",
        secure=True if is_prod_or_cross_site else False,
        max_age=3600 * 24 * 7,  # 7 days
        path="/"
    )
    
    logger.info(f"User '{display_name}' logged in. Session created: {user.id}")
    return {"message": "Logged in successfully", "user": user}

@router.get("/me", response_model=User, response_model_by_alias=False)
async def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@router.post("/logout")
async def logout(response: Response):
    is_prod_or_cross_site = settings.APP_ENV == "production" or "vercel.app" in settings.ALLOWED_ORIGINS or any("ngrok" in o for o in settings.ALLOWED_ORIGINS)
    
    response.delete_cookie(
        key="session_id",
        path="/",
        samesite="none" if is_prod_or_cross_site else "lax",
        secure=True if is_prod_or_cross_site else False
    )
    return {"message": "Logged out successfully"}
