"""Provider-backed conversation for the chat endpoints.

Routes each request by task, then falls back through every configured provider so
that all models are used — not only OpenAI. Raises :class:`ModelUnavailableError`
with a user-friendly message when no provider can fulfil the request.
"""

import json
import logging
import re
from pathlib import Path
from typing import Any

import httpx
import yaml

from backend.config import settings

logger = logging.getLogger(__name__)


class ModelUnavailableError(RuntimeError):
    """Raised when no configured provider can produce a response."""


SYSTEM_PROMPT = """You are **Ideator** — a sharp, warm idea partner for founders, builders, and students. Your job is to help people find raw ideas worth pursuing and then improve them into something genuinely worth building.

## Your personality
You are direct without being harsh, enthusiastic without being a yes-machine. You care about the person's success more than you care about validating their idea. You give honest, specific feedback — you challenge weak assumptions, surface hidden risks, and propose the smallest possible next step to test a hypothesis. You treat everyone as a capable adult.

## How to structure your responses
Always use **Markdown** — the interface renders it beautifully. Use it naturally, not excessively:
- Use `##` or `###` headings to organise long answers into scannable sections.
- Use **bold** to highlight the most important insight in each paragraph.
- Use bullet lists for parallel items (features, risks, steps), but write prose when the ideas flow naturally.
- Use `inline code` for technical terms, tools, frameworks, and model names.
- Use code blocks with language tags for any actual code snippets.
- Use > blockquotes sparingly, only for a key quote or a sharp one-liner insight.

## How to evaluate ideas
When someone shares a concept, run it through this lens:
1. **The real problem** — Who feels this pain acutely, and how often?
2. **Why now** — What makes this moment better than two years ago?
3. **Competition** — Who else is doing this, and what's the genuine differentiator?
4. **Monetisation signal** — Would someone pay, switch, or change behaviour?
5. **Smallest test** — What is the cheapest, fastest experiment to learn whether the core assumption is true?

## Conversation behaviour
- **Anchor on specifics.** Reference the user's exact words, constraints, and goals. Never give generic advice that would apply to any idea.
- **Ask at most one focused question per turn.** Build understanding progressively rather than overwhelming the user.
- **Short replies are follow-ups.** When the user sends a short message, treat it as continuing the current thread — use conversation history and session memory to stay coherent.
- **Session memory.** If prior session facts are provided in context, use them naturally; do not announce that you are using memory.
- **Tool results.** If a collision-check or web-research result is provided in context, ground your answer in it and acknowledge it briefly (e.g. "A similar product exists — here's how you could differentiate…"). Never claim to have run a tool unless a real result is present.
- **No hallucinated facts.** If you don't know something, say so clearly and tell the user how to find it.

## Tone
Warm, curious, and precise. Use plain language. Be concise but complete — always explain the reasoning behind a conclusion, never just state it. If you'd normally write a paragraph of preamble before the answer, cut it."""


def _provider_config() -> dict[str, dict[str, Any]]:
    config_path = Path(__file__).resolve().parent.parent / "config" / "llm_providers.yaml"
    with config_path.open(encoding="utf-8") as file:
        return yaml.safe_load(file).get("providers", {})


def _provider_keys(name: str) -> list[str]:
    """Return every API key configured for a provider (supports comma-separated lists)."""
    raw = {
        "groq": settings.GROQ_API_KEYS,
        "cerebras": settings.CEREBRAS_API_KEYS,
        "mistral": settings.MISTRAL_API_KEYS,
        "openai": settings.OPENAI_API_KEY,
    }.get(name, "")
    if not raw:
        return []
    return [key.strip() for key in raw.replace(";", ",").split(",") if key.strip()]


def _provider_order(task: str) -> list[str]:
    """Providers whose config lists the task come first, then the rest as fallback."""
    providers = _provider_config()
    task_first = [name for name, config in providers.items() if task in config.get("tasks", [])]
    return task_first + [name for name in providers if name not in task_first]


def _build_messages(
    prompt: str,
    history: list[Any],
    context: str | None = None,
    system_prompt: str | None = None,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt or SYSTEM_PROMPT}]
    if context:
        messages.append({"role": "system", "content": context})
    for message in history[-30:]:
        sender = message.get("sender") if isinstance(message, dict) else message.sender
        content = message.get("content") if isinstance(message, dict) else message.content
        if sender in {"user", "assistant"} and content:
            messages.append({"role": "assistant" if sender == "assistant" else "user", "content": content})
    messages.append({"role": "user", "content": prompt})
    return messages


async def generate_response(
    prompt: str,
    history: list[Any],
    task: str = "conversation",
    context: str | None = None,
    model: str | None = None,
    system_prompt: str | None = None,
    max_tokens: int = 1200,
) -> str:
    """Route by task, then fall back through every configured provider/model."""
    providers = _provider_config()
    order = _provider_order(task)
    # A specific model name is provider-bound, so don't fan out to unrelated providers.
    if model:
        order = [name for name in order if task in providers.get(name, {}).get("tasks", [])]
    messages = _build_messages(prompt, history, context, system_prompt)

    available = False
    async with httpx.AsyncClient(timeout=30.0) as client:
        for name in order:
            keys = _provider_keys(name)
            if not keys:
                continue
            available = True
            config = providers[name]
            chosen_model = model or config["models"].get("default")
            if not chosen_model:
                continue
            for key in keys:
                try:
                    response = await client.post(
                        f"{config['base_url'].rstrip('/')}/chat/completions",
                        headers={"Authorization": f"Bearer {key}"},
                        json={
                            "model": chosen_model,
                            "messages": messages,
                            "temperature": 0.7,
                            "max_tokens": max_tokens,
                        },
                    )
                    response.raise_for_status()
                    content = response.json()["choices"][0]["message"]["content"].strip()
                    if content:
                        logger.info("Generated %s response with %s (%s)", task, name, model)
                        return content
                except (httpx.HTTPError, KeyError, IndexError, TypeError) as exc:
                    logger.warning("%s (%s) unavailable for %s: %s", name, model, task, exc)

    if not available:
        raise ModelUnavailableError(
            "I couldn't find any AI provider configured. Add a Groq, Cerebras, Mistral, or "
            "OpenAI API key to the backend to start chatting."
        )
    raise ModelUnavailableError(
        "All AI providers are temporarily unreachable. Please check your connection or API "
        "keys and try again in a moment."
    )


async def generate_chat_response(prompt: str, history: list[Any]) -> str:
    return await generate_response(prompt, history, task="conversation")


ALLOWED_SKILLS = {"collision_check", "web_research"}

_SKILL_ROUTER_PROMPT = """You are the skill router for Ideator, a tool that helps people develop novel ideas.
Given the user's message, decide which skills are needed before answering.
Available skills:
- collision_check: check the user's idea against a stored vector database of previously claimed ideas to assess novelty. Use when the message describes OR asks for a concrete product, startup, project, or research idea — including vague requests like "suggest me ideas", "what should I build", or "give me project ideas".
- web_research: search the web for recent sources, products, papers, and competitors. Use when the user asks about existing research, technologies, wants idea suggestions, asks about a domain, or wants to know what's already out there.

Respond with ONLY a JSON array of the skill names needed (for example ["collision_check", "web_research"]).
If the message is purely a greeting, purely small talk with zero ideation content, or completely unintelligible, respond with [].
When in doubt, include both skills — it is better to over-search than to give an uninformed answer."""


def _parse_string_list(text: str) -> list[str]:
    text = (text or "").strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Tolerate models that wrap the array in prose: grab the first [...] block.
        match = re.search(r"\[.*?\]", text, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                data = None
        else:
            data = None
    if isinstance(data, list):
        return [str(item).strip() for item in data if str(item).strip()]
    return []


def _parse_skills(text: str) -> list[str]:
    return [skill for skill in _parse_string_list(text) if skill in ALLOWED_SKILLS]


async def plan_skills(prompt: str) -> list[str]:
    """Ask a fast routing model which skills are relevant; default to none on failure.

    This is what makes tool/skill usage dynamic: skills run only when the router
    decides they are needed for this specific message, never unconditionally.
    """
    providers = _provider_config()
    groq = providers.get("groq", {}).get("models", {})
    fast_model = groq.get("fast") or groq.get("default")
    try:
        decision = await generate_response(
            f"User message: {prompt}",
            history=[],
            task="routing",
            model=fast_model,
            system_prompt=_SKILL_ROUTER_PROMPT,
            max_tokens=64,
        )
    except ModelUnavailableError:
        return []
    return _parse_skills(decision)


_SESSION_FACTS_PROMPT = """You are Ideator's memory extractor. From the latest exchange between the user and Ideator, extract ONLY durable, reusable facts worth remembering for the rest of this session.
Capture: the core idea or problem, key decisions, constraints, user preferences, goals, target audience, and anything that should shape future replies.
Do NOT capture pleasantries, throwaway comments, or things already obvious from the immediate prompt.
Respond with ONLY a JSON array of short strings (1-5 items). If nothing durable was said, respond with []."""


async def extract_session_facts(prompt: str, response: str) -> list[str]:
    """Distill the latest exchange into durable, session-level takeaways."""
    providers = _provider_config()
    groq = providers.get("groq", {}).get("models", {})
    fast_model = groq.get("fast") or groq.get("default")
    try:
        decision = await generate_response(
            f"User: {prompt}\n\nIdeator: {response}",
            history=[],
            task="routing",
            model=fast_model,
            system_prompt=_SESSION_FACTS_PROMPT,
            max_tokens=200,
        )
    except ModelUnavailableError:
        return []
    return _parse_string_list(decision)
