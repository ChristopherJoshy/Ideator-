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
from backend.models.chat import Chat, ChatMessage, IdeaCanvas
from backend.services.telegram_logger import log_chat_message, log_error
from backend.services.memory import remember_in_background
from backend.services.llm import (
    generate_response, generate_response_messages, plan_skills, extract_session_facts, extract_chart_params,
    generate_chat_title, generate_followups, generate_canvas_update,
    generate_deep_research_queries, generate_optimized_tool_queries, ModelUnavailableError, _build_messages
)
from backend.services.tools import (
    collision_check, web_research, academic_search, github_search,
    fetch_newsletter_feeds, generate_chart,
    hacker_news_search, wikipedia_summary, reddit_search,
    npm_search, crossref_search, world_bank_indicator, coinpaprika,
)
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


@router.get("/{chat_id}/canvas", response_model=IdeaCanvas)
async def get_chat_canvas(chat_id: str, current_user: User = Depends(get_current_user)):
    db = get_mongodb_db()
    chat_doc = await db.chats.find_one({"_id": chat_id, "user_id": current_user.id})
    if not chat_doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
    canvas = chat_doc.get("canvas")
    if not canvas:
        # Return default/empty canvas
        return IdeaCanvas()
    return IdeaCanvas(**canvas)


@router.put("/{chat_id}/canvas", response_model=IdeaCanvas)
async def update_chat_canvas(chat_id: str, updated: IdeaCanvas, current_user: User = Depends(get_current_user)):
    db = get_mongodb_db()
    chat_doc = await db.chats.find_one({"_id": chat_id, "user_id": current_user.id})
    if not chat_doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    old_canvas = chat_doc.get("canvas")
    history_push = []
    if old_canvas:
        history_push.append(old_canvas)

    now = datetime.utcnow()
    updated.updated_at = now

    update_payload = {
        "$set": {
            "canvas": updated.model_dump(),
            "updated_at": now
        }
    }
    if history_push:
        update_payload["$push"] = {"canvas_history": old_canvas}

    await db.chats.update_one({"_id": chat_id}, update_payload)
    logger.info(f"Updated idea canvas for chat session {chat_id}")
    return updated


@router.get("/{chat_id}/canvas/history", response_model=List[IdeaCanvas])
async def get_chat_canvas_history(chat_id: str, current_user: User = Depends(get_current_user)):
    db = get_mongodb_db()
    chat_doc = await db.chats.find_one({"_id": chat_id, "user_id": current_user.id})
    if not chat_doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")
    history = chat_doc.get("canvas_history", [])
    return [IdeaCanvas(**h) for h in history]
def parse_tool_call(text: str) -> dict | None:
    import re
    # Look for a JSON block inside triple backticks
    match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
    if not match:
        match = re.search(r"(\{.*?\})", text, re.DOTALL)
    if match:
        try:
            import json
            parsed = json.loads(match.group(1))
            if "tool" in parsed and "query" in parsed:
                return parsed
        except Exception:
            pass
    return None


async def execute_tool(name: str, query: str, base_url: str = "http://localhost:8000") -> str:
    name_lower = name.lower()
    try:
        if "collision" in name_lower:
            return await collision_check(query)
        elif "web" in name_lower:
            return await web_research(query)
        elif "academic" in name_lower:
            return await academic_search(query)
        elif "github" in name_lower:
            return await github_search(query)
        elif "news" in name_lower or "feed" in name_lower:
            return await fetch_newsletter_feeds(query)
        elif "hacker" in name_lower:
            return await hacker_news_search(query)
        elif "wiki" in name_lower:
            return await wikipedia_summary(query)
        elif "reddit" in name_lower:
            return await reddit_search(query)
        elif "npm" in name_lower:
            return await npm_search(query)
        elif "crossref" in name_lower:
            return await crossref_search(query)
        elif "world" in name_lower or "bank" in name_lower:
            return await world_bank_indicator(query)
        elif "coin" in name_lower or "paprika" in name_lower:
            return await coinpaprika(query)
        elif "chart" in name_lower:
            params = await extract_chart_params(query)
            return await generate_chart(
                chart_type=params.get("chart_type", "bar"),
                title=params.get("title", "Chart"),
                labels=params.get("labels", []),
                values=params.get("values", []),
                x_label=params.get("x_label", ""),
                y_label=params.get("y_label", ""),
                base_url=base_url
            )
    except Exception as e:
        return f"Error executing tool: {e}"
    return "Error: Unknown tool name"


# Maps the skill-router's lowercase skill names to the execute_tool() tool identifiers,
# and to the optimized per-tool query key produced by generate_optimized_tool_queries().
# This is what makes the tools "dynamic": each runs with a custom, query-specific string
# derived from the user's actual message rather than a generic one.
SKILL_TO_TOOL = {
    "collision_check": "CollisionCheck",
    "web_research": "WebResearch",
    "academic_search": "AcademicSearch",
    "github_search": "GithubSearch",
    "hacker_news_search": "HackerNewsSearch",
    "wikipedia_summary": "WikipediaSummary",
    "reddit_search": "RedditSearch",
    "npm_search": "NpmSearch",
    "crossref_search": "CrossrefSearch",
    "world_bank_indicator": "WorldBankIndicator",
    "coinpaprika": "Coinpaprika",
    "fetch_newsletter_feeds": "FetchNewsletterFeeds",
}

QUERY_KEY_FOR_SKILL = {
    "web_research": "general",
    "academic_search": "academic",
    "github_search": "code",
    "hacker_news_search": "community",
    "reddit_search": "community",
    "wikipedia_summary": "general",
    "npm_search": "code",
    "crossref_search": "academic",
    "world_bank_indicator": "economy",
    "coinpaprika": "crypto",
    "fetch_newsletter_feeds": "general",
    "collision_check": "general",
}


async def run_chat_pipeline(prompt: str, history: list, chat_id: str, user_id: str, user_name: str, base_url: str = "http://localhost:8000", deep_research: bool = False):
    """Shared, mock-free chat pipeline yielding SSE/WebSocket events.

    Runs real tool steps (collision check + optional web research), then generates a
    response across all configured providers with full fallback, streaming the text
    token-by-token. Persists the assistant message at the end.
    """
    db = get_mongodb_db()
    tool_steps: list[dict] = []
    assistant_content = ""

    # Ensures the novelty/collision check runs at most once per turn (collision_check
    # also stores a vector, so running it twice on the same text would self-collide).
    collision_checked = {"v": False}

    async def run_final_collision(text: str):
        if collision_checked["v"]:
            return None
        collision_checked["v"] = True
        try:
            return await collision_check(text)
        except Exception as exc:
            logger.warning("Final collision check failed: %s", exc)
            return None

    # Automatically generate chat title on first message using AI (gpt-4o-mini)
    if not history:
        try:
            chat_title = await generate_chat_title(prompt)
            await db.chats.update_one({"_id": chat_id}, {"$set": {"title": chat_title}})
            logger.info("Automatically generated title '%s' for chat %s", chat_title, chat_id)
        except Exception as exc:
            logger.warning("Failed to auto-generate chat title for %s: %s", chat_id, exc)

    context_parts: list[str] = []

    # Compile optimized search queries for all tools
    tool_queries = await generate_optimized_tool_queries(prompt)

    if deep_research:
        # Step 1: Formulate search queries
        yield {"event": "agent_step", "step": "Formulating research queries...", "status": "running"}
        academic_query = tool_queries.get("academic", prompt)
        community_query = tool_queries.get("community", prompt)

        # Step 2: Academic literature search
        yield {"event": "agent_step", "step": "Searching research databases (arXiv, CrossRef)...", "status": "running"}
        yield {"event": "tool_start", "name": "AcademicSearch", "args": json.dumps({"query": academic_query[:60]})}
        academic_res = await academic_search(academic_query)
        yield {"event": "tool_end", "name": "AcademicSearch", "result": academic_res}
        tool_steps.append({"tool": "AcademicSearch", "args": json.dumps({"query": academic_query[:60]}), "result": academic_res})

        yield {"event": "tool_start", "name": "CrossrefSearch", "args": json.dumps({"query": academic_query[:60]})}
        crossref_res = await crossref_search(academic_query)
        yield {"event": "tool_end", "name": "CrossrefSearch", "result": crossref_res}
        tool_steps.append({"tool": "CrossrefSearch", "args": json.dumps({"query": academic_query[:60]}), "result": crossref_res})

        # Step 3: Developer & Community sentiment checking
        yield {"event": "agent_step", "step": "Checking community discussions (Hacker News, Reddit)...", "status": "running"}
        yield {"event": "tool_start", "name": "HackerNewsSearch", "args": json.dumps({"query": community_query[:60]})}
        hn_res = await hacker_news_search(community_query)
        yield {"event": "tool_end", "name": "HackerNewsSearch", "result": hn_res}
        tool_steps.append({"tool": "HackerNewsSearch", "args": json.dumps({"query": community_query[:60]}), "result": hn_res})

        yield {"event": "tool_start", "name": "RedditSearch", "args": json.dumps({"query": community_query[:60]})}
        reddit_res = await reddit_search(community_query)
        yield {"event": "tool_end", "name": "RedditSearch", "result": reddit_res}
        tool_steps.append({"tool": "RedditSearch", "args": json.dumps({"query": community_query[:60]}), "result": reddit_res})

        # Compile tool outputs for model context
        for r_name, r_val in [("Academic", academic_res), ("CrossRef", crossref_res), ("Hacker News", hn_res), ("Reddit", reddit_res)]:
            try:
                parsed = json.loads(r_val)
                if isinstance(parsed, dict) and "sources" in parsed:
                    source_lines = [f"- {s.get('title', 'Untitled')} ({s.get('url', '')})" for s in parsed["sources"]]
                    readable = f"{r_name} results:\n" + "\n".join(source_lines)
                else:
                    readable = r_val
            except Exception:
                readable = r_val
            context_parts.append(readable)

        # Collision Check too
        yield {"event": "agent_step", "step": "Running novelty collision check...", "status": "running"}
        yield {"event": "tool_start", "name": "CollisionCheck", "args": json.dumps({"query": tool_queries["general"][:60]})}
        collision_res = await run_final_collision(tool_queries["general"])
        yield {"event": "tool_end", "name": "CollisionCheck", "result": collision_res}
        tool_steps.append({"tool": "CollisionCheck", "args": json.dumps({"query": tool_queries["general"][:60]}), "result": collision_res})
        context_parts.append(f"Novelty check result: {collision_res}")

        yield {"event": "agent_step", "step": "Deep research complete. Writing insights...", "status": "done"}
        tool_context = "\n\n".join(context_parts) or None
        try:
            response_text = await generate_response(prompt, history, task="conversation", context=tool_context)
            assistant_content = response_text
        except ModelUnavailableError as exc:
            logger.warning("Chat generation failed for %s: %s", chat_id, exc)
            yield {"event": "error", "text": str(exc)}
            asyncio.create_task(log_error(error_msg=str(exc), user_name=user_name, path=f"/chats/{chat_id}"))
            yield {"event": "done"}
            return
    else:
        # Standard Loop: Dynamic ReAct tool execution loop
        react_messages = _build_messages(prompt, history)
        
        session_facts = await get_session_facts(chat_id)
        if session_facts:
            react_messages.insert(1, {
                "role": "system",
                "content": "Session memory — established earlier in this conversation (use it; do not ask the user to repeat it):\n" + "\n".join(f"- {fact}" for fact in session_facts)
            })

        # ── Dynamic, query-specific tool pre-run ────────────────────────────
        # The skill router decides which tools are relevant for THIS message, then each
        # one is executed with a custom optimized query derived from the user's prompt.
        # This is what makes the tools "dynamic": the AI researches the web/DBs with the
        # user's actual intent before answering, and can still call more tools via ReAct.
        tool_queries = await generate_optimized_tool_queries(prompt)
        try:
            planned_skills = await plan_skills(prompt)
        except Exception:
            planned_skills = []

        dynamic_context: list[str] = []
        for skill in planned_skills:
            if skill == "collision_check":
                # Collision is handled by the final novelty gate (avoids duplicate storage).
                continue
            tool_name = SKILL_TO_TOOL.get(skill)
            if not tool_name:
                continue
            qkey = QUERY_KEY_FOR_SKILL.get(skill, "general")
            custom_query = (tool_queries.get(qkey) or "").strip() or prompt
            yield {"event": "tool_start", "name": tool_name, "args": json.dumps({"query": custom_query[:60]})}
            result = await execute_tool(tool_name, custom_query, base_url=base_url)
            yield {"event": "tool_end", "name": tool_name, "result": result}
            tool_steps.append({"tool": tool_name, "args": json.dumps({"query": custom_query[:60]}), "result": result})
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict) and "sources" in parsed:
                    src_lines = [f"- {s.get('title', 'Untitled')} ({s.get('url', '')})" for s in parsed["sources"]]
                    dynamic_context.append(f"{tool_name} results:\n" + "\n".join(src_lines))
                else:
                    dynamic_context.append(f"{tool_name} result: {result}")
            except Exception:
                dynamic_context.append(f"{tool_name} result: {result}")

        if dynamic_context:
            react_messages.append({
                "role": "system",
                "content": "Pre-search results (ground your answer in these; cite real sources, never fabricate):\n"
                + "\n\n".join(dynamic_context),
            })

        max_turns = 4
        assistant_content = ""
        
        for turn in range(max_turns):
            try:
                response_text = await generate_response_messages(react_messages, task="conversation")
            except ModelUnavailableError as exc:
                logger.warning("Chat generation failed for %s: %s", chat_id, exc)
                yield {"event": "error", "text": str(exc)}
                asyncio.create_task(log_error(error_msg=str(exc), user_name=user_name, path=f"/chats/{chat_id}"))
                yield {"event": "done"}
                return

            tool_call = parse_tool_call(response_text)
            if tool_call:
                tool_name = tool_call.get("tool")
                tool_query = tool_call.get("query")
                if tool_name and "collision" in tool_name.lower():
                    # Mark as checked so the final novelty gate won't re-run (and self-collide).
                    collision_checked["v"] = True

                yield {"event": "tool_start", "name": tool_name, "args": json.dumps({"query": tool_query[:60]})}
                result = await execute_tool(tool_name, tool_query, base_url=base_url)
                yield {"event": "tool_end", "name": tool_name, "result": result}
                tool_steps.append({"tool": tool_name, "args": json.dumps({"query": tool_query[:60]}), "result": result})

                react_messages.append({"role": "assistant", "content": response_text})
                react_messages.append({"role": "system", "content": f"Tool '{tool_name}' result:\n{result}"})
                continue
            else:
                assistant_content = response_text
                break

    # ── Final novelty gate ────────────────────────────────────────────────
    # Before the answer reaches the user, verify the underlying idea for collision.
    # This is the "check the final answer for collision, then give it to the user" step.
    if not collision_checked["v"] and assistant_content.strip():
        yield {"event": "agent_step", "step": "Verifying novelty of the final answer…", "status": "running"}
        collision_res = await run_final_collision(prompt)
        if collision_res and "overlaps with a previously stored idea" in collision_res:
            assistant_content = assistant_content.rstrip() + "\n\n---\n\n**Novelty check:** " + collision_res
        yield {"event": "agent_step", "step": "Novelty verified.", "status": "done"}

    # Persist durable takeaways from this exchange so future turns remember them.
    extracted_facts = await extract_session_facts(prompt, assistant_content)
    if extracted_facts:
        await remember_session_facts(chat_id, user_id, extracted_facts)

    for token in assistant_content.split(" "):
        yield {"event": "delta", "text": token + " "}

    # Generate follow-up suggestion chips and emit before 'done'
    followups = await generate_followups(response_text, prompt)
    if followups:
        yield {"event": "followups", "suggestions": followups}

    # Emit done and persist message

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

    host = request.headers.get("host") or request.url.netloc
    scheme = "https" if request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https" else "http"
    base_url = f"{scheme}://{host}"

    async def event_generator():
        async for event in run_chat_pipeline(
            prompt, chat_doc.get("messages", []), chat_id, current_user.id, current_user.display_name, base_url=base_url
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
        deep_research = bool(payload.get("deep_research", False))

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

        host = websocket.headers.get("host") or websocket.url.netloc
        scheme = "https" if websocket.url.scheme == "wss" or websocket.headers.get("x-forwarded-proto") == "https" else "http"
        base_url = f"{scheme}://{host}"

        async for event in run_chat_pipeline(
            prompt, chat_doc.get("messages", []), chat_id, user.id, user.display_name, base_url=base_url, deep_research=deep_research
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
