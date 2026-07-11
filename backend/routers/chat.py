import asyncio
import json
import logging
from datetime import datetime
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status, Request, WebSocket, WebSocketDisconnect
from sse_starlette.sse import EventSourceResponse

from backend.config import settings
from backend.db.mongodb import get_mongodb_db
from backend.routers.auth import get_current_user
from backend.models.user import User
from backend.models.chat import Chat, ChatMessage
from backend.services.telegram_logger import log_chat_message, log_error
from backend.services.memory import remember_in_background
from backend.services.llm import generate_response, plan_skills, extract_session_facts, extract_chart_params, generate_chat_title, ModelUnavailableError
from backend.services.tools import collision_check, web_research, academic_search, github_search, fetch_newsletter_feeds, generate_chart
from backend.services.memory import remember_in_background, forget_chat, remember_session_facts, get_session_facts

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chats", tags=["Chat"])


@router.post("", response_model=Chat, response_model_by_alias=False)
async def create_chat(current_user: User = Depends(get_current_user)):
    db = get_mongodb_db()
    chat = Chat(user_id=current_user.id)
    await db.chats.insert_one(chat.model_dump(by_alias=True))
    logger.info(f"Created chat session {chat.id} for user {current_user.display_name}")
    return chat


@router.get("", response_model=List[Chat], response_model_by_alias=False)
async def list_chats(current_user: User = Depends(get_current_user)):
    db = get_mongodb_db()
    cursor = db.chats.find({"user_id": current_user.id}).sort("updated_at", -1)
    chats = []
    async for doc in cursor:
        chats.append(Chat(**doc))
    return chats


@router.get("/{chat_id}/messages", response_model=List[ChatMessage])
async def get_messages(chat_id: str, current_user: User = Depends(get_current_user)):
    db = get_mongodb_db()
    chat_doc = await db.chats.find_one({"_id": chat_id, "user_id": current_user.id})
    if not chat_doc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found"
        )
    return chat_doc.get("messages", [])


@router.delete("/{chat_id}")
async def delete_chat(chat_id: str, current_user: User = Depends(get_current_user)):
    db = get_mongodb_db()
    result = await db.chats.delete_one({"_id": chat_id, "user_id": current_user.id})
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Chat session not found"
        )
    asyncio.create_task(forget_chat(chat_id))
    logger.info(f"Deleted chat session {chat_id} for user {current_user.display_name}")
    return {"deleted": True}


async def run_chat_pipeline(prompt: str, history: list, chat_id: str, user_id: str, user_name: str):
    """Shared, mock-free chat pipeline yielding SSE/WebSocket events.

    Runs real tool steps (collision check + optional web research), then generates a
    response across all configured providers with full fallback, streaming the text
    token-by-token. Persists the assistant message at the end.
    """
    db = get_mongodb_db()
    tool_steps: list[dict] = []
    assistant_content = ""

    # Automatically generate chat title on first message using AI (gpt-4o-mini)
    if not history:
        try:
            chat_title = await generate_chat_title(prompt)
            await db.chats.update_one({"_id": chat_id}, {"$set": {"title": chat_title}})
            logger.info("Automatically generated title '%s' for chat %s", chat_title, chat_id)
        except Exception as exc:
            logger.warning("Failed to auto-generate chat title for %s: %s", chat_id, exc)

    # Dynamic skill selection: a fast routing model decides which tools (if any)
    # are relevant to THIS message. Tools run only when the router asks for them.
    skills = await plan_skills(prompt)
    context_parts: list[str] = []

    # Recover durable takeaways stored earlier in this session and surface them as
    # context so the model remembers the user's idea, decisions, and preferences
    # without the user repeating themselves. This never alters the current prompt.
    session_facts = await get_session_facts(chat_id)
    if session_facts:
        context_parts.append(
            "Session memory — established earlier in this conversation (use it; do not ask "
            "the user to repeat it):\n" + "\n".join(f"- {fact}" for fact in session_facts)
        )

    if "collision_check" in skills:
        yield {"event": "tool_start", "name": "CollisionCheck",
               "args": json.dumps({"similarity_threshold": settings.COLLISION_SIMILARITY_THRESHOLD})}
        collision_result = await collision_check(prompt)
        yield {"event": "tool_end", "name": "CollisionCheck", "result": collision_result}
        tool_steps.append({"tool": "CollisionCheck",
                           "args": json.dumps({"similarity_threshold": settings.COLLISION_SIMILARITY_THRESHOLD}),
                           "result": collision_result})
        context_parts.append(f"Collision check result: {collision_result}")

    if "web_research" in skills:
        paper_result = await web_research(f"recent research and existing products: {prompt}")
        if paper_result is not None:
            yield {"event": "tool_start", "name": "WebResearch", "args": json.dumps({"query": prompt[:60]})}
            yield {"event": "tool_end", "name": "WebResearch", "result": paper_result}
            tool_steps.append({"tool": "WebResearch", "args": json.dumps({"query": prompt[:60]}), "result": paper_result})

            # Build a readable summary for the LLM context (not raw JSON)
            try:
                parsed = json.loads(paper_result)
                if isinstance(parsed, dict) and "sources" in parsed:
                    source_lines = [
                        f"- {s.get('title', 'Untitled')} ({s.get('url', '')})"
                        for s in parsed["sources"]
                        if s.get("title") or s.get("url")
                    ]
                    readable = "Web research found these sources:\n" + "\n".join(source_lines)
                else:
                    readable = paper_result
            except (json.JSONDecodeError, TypeError):
                readable = paper_result
            context_parts.append(f"Web research result: {readable}")

    if "academic_search" in skills:
        yield {"event": "tool_start", "name": "AcademicSearch", "args": json.dumps({"query": prompt[:60]})}
        academic_result = await academic_search(prompt)
        yield {"event": "tool_end", "name": "AcademicSearch", "result": academic_result}
        tool_steps.append({"tool": "AcademicSearch", "args": json.dumps({"query": prompt[:60]}), "result": academic_result})

        # Build readable summary
        try:
            parsed = json.loads(academic_result)
            if isinstance(parsed, dict) and "sources" in parsed:
                source_lines = [
                    f"- {s.get('title', 'Untitled')} ({s.get('url', '')})"
                    for s in parsed["sources"]
                ]
                readable = "Academic search found these papers:\n" + "\n".join(source_lines)
            else:
                readable = academic_result
        except Exception:
            readable = academic_result
        context_parts.append(f"Academic research: {readable}")

    if "github_search" in skills:
        yield {"event": "tool_start", "name": "GithubSearch", "args": json.dumps({"query": prompt[:60]})}
        github_result = await github_search(prompt)
        yield {"event": "tool_end", "name": "GithubSearch", "result": github_result}
        tool_steps.append({"tool": "GithubSearch", "args": json.dumps({"query": prompt[:60]}), "result": github_result})

        # Build readable summary
        try:
            parsed = json.loads(github_result)
            if isinstance(parsed, dict) and "sources" in parsed:
                source_lines = [
                    f"- {s.get('title', 'Untitled')} ({s.get('url', '')})"
                    for s in parsed["sources"]
                ]
                readable = "GitHub search found these repositories:\n" + "\n".join(source_lines)
            else:
                readable = github_result
        except Exception:
            readable = github_result
        context_parts.append(f"GitHub search: {readable}")

    if "fetch_newsletter_feeds" in skills:
        yield {"event": "tool_start", "name": "FetchNewsletterFeeds", "args": json.dumps({"topic": prompt[:60]})}
        newsletter_result = await fetch_newsletter_feeds(prompt)
        yield {"event": "tool_end", "name": "FetchNewsletterFeeds", "result": newsletter_result}
        tool_steps.append({"tool": "FetchNewsletterFeeds", "args": json.dumps({"topic": prompt[:60]}), "result": newsletter_result})

        # Build readable summary
        try:
            parsed = json.loads(newsletter_result)
            if isinstance(parsed, dict) and "sources" in parsed:
                source_lines = [
                    f"- {s.get('title', 'Untitled')} ({s.get('url', '')})"
                    for s in parsed["sources"]
                ]
                readable = "Newsletter/Feed articles found:\n" + "\n".join(source_lines)
            else:
                readable = newsletter_result
        except Exception:
            readable = newsletter_result
        context_parts.append(f"Newsletter updates: {readable}")

    if "generate_chart" in skills:
        yield {"event": "tool_start", "name": "GenerateChart", "args": json.dumps({"prompt": prompt[:60]})}
        params = await extract_chart_params(prompt)
        chart_result = await generate_chart(
            chart_type=params.get("chart_type", "bar"),
            title=params.get("title", "Chart"),
            labels=params.get("labels", []),
            values=params.get("values", []),
            x_label=params.get("x_label", ""),
            y_label=params.get("y_label", "")
        )
        yield {"event": "tool_end", "name": "GenerateChart", "result": chart_result}
        tool_steps.append({"tool": "GenerateChart", "args": json.dumps(params), "result": chart_result})
        
        try:
            parsed = json.loads(chart_result)
            if isinstance(parsed, dict) and "sources" in parsed:
                img_url = parsed["sources"][0]["url"]
                readable = f"Successfully generated a {params.get('chart_type')} chart titled '{params.get('title')}' at URL: {img_url}. You MUST embed this chart directly in your final response using the Markdown syntax: `![{params.get('title')}]({img_url})`."
            else:
                readable = chart_result
        except Exception:
            readable = chart_result
        context_parts.append(f"Chart generation result: {readable}")

    tool_context = "\n\n".join(context_parts) or None

    # Generation across all providers with fallback, grounded in tool output + session memory.
    try:
        response_text = await generate_response(prompt, history, task="conversation", context=tool_context)
    except ModelUnavailableError as exc:
        logger.warning("Chat generation failed for %s: %s", chat_id, exc)
        yield {"event": "error", "text": str(exc)}
        asyncio.create_task(log_error(error_msg=str(exc), user_name=user_name, path=f"/chats/{chat_id}"))
        yield {"event": "done"}
        return

    # Persist durable takeaways from this exchange so future turns remember them.
    extracted_facts = await extract_session_facts(prompt, response_text)
    if extracted_facts:
        await remember_session_facts(chat_id, user_id, extracted_facts)

    for token in response_text.split(" "):
        assistant_content += token + " "
        yield {"event": "delta", "text": token + " "}

    assistant_msg = ChatMessage(
        sender="assistant",
        content=assistant_content.strip(),
        skill_used="conversation",
        tool_steps=tool_steps,
    )
    await db.chats.update_one(
        {"_id": chat_id},
        {
            "$push": {"messages": assistant_msg.model_dump()},
            "$set": {"updated_at": datetime.utcnow()}
        }
    )
    remember_in_background(
        message_id=assistant_msg.id, chat_id=chat_id, user_id=user_id,
        sender=assistant_msg.sender, content=assistant_msg.content,
    )
    asyncio.create_task(
        log_chat_message(sender_name="Ideator", message=assistant_content.strip(), is_user=False, chat_id=chat_id)
    )
    yield {"event": "done"}


@router.get("/{chat_id}/stream")
async def stream_chat(
    chat_id: str,
    prompt: str,
    request: Request,
    current_user: User = Depends(get_current_user)
):
    db = get_mongodb_db()
    chat_doc = await db.chats.find_one({"_id": chat_id, "user_id": current_user.id})
    if not chat_doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    user_msg = ChatMessage(sender="user", content=prompt)
    await db.chats.update_one(
        {"_id": chat_id},
        {"$push": {"messages": user_msg.model_dump()}, "$set": {"updated_at": datetime.utcnow()}}
    )
    remember_in_background(
        message_id=user_msg.id, chat_id=chat_id, user_id=current_user.id,
        sender=user_msg.sender, content=user_msg.content,
    )
    asyncio.create_task(log_chat_message(sender_name=current_user.display_name, message=prompt, is_user=True, chat_id=chat_id))

    async def event_generator():
        async for event in run_chat_pipeline(
            prompt, chat_doc.get("messages", []), chat_id, current_user.id, current_user.display_name
        ):
            if await request.is_disconnected():
                return
            yield {
                "event": event["event"],
                "data": json.dumps({key: value for key, value in event.items() if key != "event"}),
            }

    return EventSourceResponse(event_generator())


@router.websocket("/{chat_id}/ws")
async def websocket_chat(websocket: WebSocket, chat_id: str):
    await websocket.accept()

    session_id = websocket.query_params.get("session_id") or websocket.cookies.get("session_id")
    if not session_id:
        await websocket.send_json({"event": "error", "text": "Unauthorized: No session token found"})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    db = get_mongodb_db()
    user_doc = await db.users.find_one({"_id": session_id})
    if not user_doc:
        await websocket.send_json({"event": "error", "text": "Unauthorized: Session invalid"})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    user = User(**user_doc)
    chat_doc = await db.chats.find_one({"_id": chat_id, "user_id": user.id})
    if not chat_doc:
        await websocket.send_json({"event": "error", "text": "Chat session not found"})
        await websocket.close(code=status.WS_1011_INTERNAL_ERROR)
        return

    try:
        data = await websocket.receive_text()
        payload = json.loads(data)
        prompt = payload.get("prompt", "").strip()

        if not prompt:
            await websocket.send_json({"event": "error", "text": "Prompt cannot be empty"})
            return

        user_msg = ChatMessage(sender="user", content=prompt)
        await db.chats.update_one(
            {"_id": chat_id},
            {"$push": {"messages": user_msg.model_dump()}, "$set": {"updated_at": datetime.utcnow()}}
        )
        remember_in_background(
            message_id=user_msg.id, chat_id=chat_id, user_id=user.id,
            sender=user_msg.sender, content=user_msg.content,
        )
        asyncio.create_task(log_chat_message(sender_name=user.display_name, message=prompt, is_user=True, chat_id=chat_id))

        async for event in run_chat_pipeline(
            prompt, chat_doc.get("messages", []), chat_id, user.id, user.display_name
        ):
            await websocket.send_json(event)

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for chat {chat_id}")
    except Exception as exc:
        logger.error(f"WebSocket error in chat {chat_id}: {exc}")
        asyncio.create_task(log_error(error_msg=str(exc), user_name=user.display_name, path=f"WS /chats/{chat_id}/ws"))
        try:
            await websocket.send_json({"event": "error", "text": "An internal error occurred."})
        except Exception:
            pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
