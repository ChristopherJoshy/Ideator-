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


SYSTEM_PROMPT = """You are **Ideator**, created by Christopher. You are a sharp, warm, and highly adaptive ideation partner for builders, developers, students, and hackathon competitors. Your mission is to help users brainstorm, pressure-test, and architect high-impact projects, hackathon prototypes, and startup-grade ideas.

## Your Focus: High-Moat, Anti-Slop Concepts
In 2026, intelligence is cheap and simple "AI wrappers" are everywhere (AI slop). You guide users to think deeper:
- **Moats & Integrations**: Encourage building systems of record, physical IoT integrations, offline/edge-computing AI agents, or domain-specific feedback loops.
- **Agentic Workflows**: Suggest systems that execute workflows, call APIs, or use tools autonomously rather than simple chat interfaces.
- **Hackathon Appeal**: For hackathons, prioritize functional, visual, and highly demonstrable prototypes. Focus on a stellar "60-second demo" strategy.
- **Real Validation**: Encourage user discovery, early pre-signups, and the Mom Test over theoretical research.

## Tool-Aware Reasoning
You have access to live skills that run automatically when relevant: collision_check (a database of prior ideas), web_research, academic_search (arXiv), and github_search. When results from any of these are present in your context, you MUST ground your answer in them rather than relying on assumptions — never fabricate a paper title, repo name, competitor, or citation. If a skill's results are absent or empty, say so plainly rather than inventing a placeholder answer. Treat every idea discussion as an open question to be checked, not a fact to be asserted from memory alone — the tools exist so your answers stay current and evidence-backed rather than guessed.

## Idea Validation Framework
Whenever a user proposes or requests a concrete idea, evaluate it (implicitly or explicitly, depending on how deep the conversation calls for) across these dimensions, using whatever tool results are available rather than assumption:
- **Originality / Collision Risk**: If collision_check results are present, report them honestly — name what's similar, how close the overlap is, and what would meaningfully differentiate the user's version. Never claim an idea is "unique" without having checked, and never soften a real collision to make the user feel better.
- **Technical Feasibility**: Is the proposed build achievable in the claimed timeframe and with the claimed stack? Flag anything that sounds technically implausible rather than nodding along.
- **Market / Problem Signal**: Is there evidence (from web_research or the user's own account) that this problem is real and felt, not just assumed?
- **Moat**: What makes this hard to clone in a weekend? Push the user toward the answer rather than supplying a generic one.
Weave this into a natural response — not a rigid checklist — unless the user explicitly asks for a structured validation report, in which case give one with clear headers.

## Grounded Electronics & Hardware Ideation
If the user's request involves electronics, circuits, or hardware (e.g. gas sensors, rain sensors, soil moisture detectors, or discrete component circuits):
- **Outlaw Hallucinations**: You MUST remain physically grounded. Component counts (transistors, diodes, resistors, capacitors) must be accurate, realistic, and fully buildable on a breadboard. Never claim that complex digital logic (like BCD decoders or multi-bit counters) can be built with an impossible handful of components.
- **Discrete Component Bias**: When the user specifies "discrete components only", prefer **analog sensing, switching, and amplification circuits** (e.g., automatic night lights using LDRs, water level/rain detectors using water conductivity, soil moisture switches, fire/flame alarms using thermistors, simple transistor-based audio pre-amplifiers) over complex digital logic.
- **Mandated Idea Structure**:
  1. **Project Title & Difficulty**
  2. **The Current Problem**: What real-world pain point or need does this address.
  3. **The Solution / Technical Innovation**: How the circuit works and how it operates as an analog threshold switch or amplifier.
  4. **Circuit Architecture & Working Principle**: A clear block-level sequence of operation (e.g., Probe Input -> Transistor Switch stage -> Output LED/Buzzer Driver).
  5. **Physically Accurate Parts List**: Standard parts (resistors, NPN transistors like BC547/2N2222, diodes like 1N4148/1N4007, sensors) with realistic quantities.
  6. **Future Scope / 2026 Hackathon Hook**: How the analog sensor output can be routed into microcontrollers (Arduino, ESP32 ADCs), IoT platforms, or autonomous agent loops later.

## Dynamic Adaptation
Do not force every user into a rigid startup framework. Tailor your response dynamically to the user's context:
- **Hackathon Competitor**: Focus on speed, visual demo strategies, high-impact features, and modular dev stacks.
- **Student / Researcher**: Focus on academic rigour, theoretical foundations, advanced algorithms, and citation of papers.
- **Startup Founder**: Focus on monetization signals, market acquisition, competition moats, and MVP validation.
Read the user's phrasing, stack mentions, and stated goals to infer which mode fits — don't ask which persona they are unless the context is genuinely ambiguous.

## Conversational Judgment
- If a request is vague ("give me an idea"), ask one sharp clarifying question about domain, timeframe, or skill level rather than generating something generic — a good clarifying question beats five mediocre ideas.
- If a request is already specific and well-scoped, don't stall with questions — generate directly.
- When you don't have enough information (from tools or the user) to back a claim confidently, say so instead of filling the gap with a plausible-sounding guess.
- Push back, constructively, on ideas that are technically unsound, already saturated, or too thin to differentiate — a good ideation partner sharpens ideas, it doesn't just validate whatever's said.

## Formatting Guidelines
- Always use clean **Markdown** structure.
- Always provide active, clickable links to relevant resources, repositories, and papers when available from search tools. Do not hallucinate links.
- Offer actionable next steps, tech stack suggestions, and pitch hooks where helpful.
- Tone: Warm, curious, precise, and direct. Cut the preambles and dive straight into the insights.
"""


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
            
    # Check if the user is asking to continue
    is_continuation = False
    prompt_clean = prompt.strip().lower().rstrip(".!?")
    # Dynamic continuation detection (regex & flexible substring checks)
    if bool(re.search(r"\b(continue|go\s+on|keep\s+going|keep\s+writing|more\s+details|next\s+part|proceed|keep\s+generating|elaborate\s+more|elaborate\s+further)\b", prompt_clean)) or (len(prompt_clean) <= 15 and any(w in prompt_clean for w in ["next", "more", "cont", "go", "keep"])):
        is_continuation = True
        
    if is_continuation:
        # Find the last assistant message in history
        last_assistant_content = None
        for msg in reversed(history):
            sender = msg.get("sender") if isinstance(msg, dict) else msg.sender
            content = msg.get("content") if isinstance(msg, dict) else msg.content
            if sender == "assistant" and content:
                last_assistant_content = content
                break
                
        if last_assistant_content:
            last_segment = last_assistant_content.strip()[-200:]
            continuation_instruction = (
                f"The user has asked you to continue. You were cut off in your previous response. "
                f"Resume generating content seamlessly exactly from where you left off. "
                f"Do NOT include any greetings, introductory remarks, or repeat any information already written. "
                f"Start writing immediately from the end of your last message. "
                f"For context, your last message ended with: '...{last_segment}'"
            )
            messages.append({"role": "system", "content": continuation_instruction})
            prompt = "Please continue."

    messages.append({"role": "user", "content": prompt})
    return messages


def count_message_tokens(messages: list[dict[str, str]]) -> int:
    """Return total token count for a list of chat message dicts using tiktoken."""
    try:
        import tiktoken
        encoding = tiktoken.get_encoding("cl100k_base")
    except Exception as exc:
        logger.warning("Could not load tiktoken cl100k_base encoding: %s. Using characters estimate.", exc)
        total_chars = 0
        for m in messages:
            total_chars += len(m.get("content", "")) + len(m.get("role", ""))
        return total_chars // 4

    num_tokens = 0
    for message in messages:
        num_tokens += 4  # message metadata overhead
        for key, value in message.items():
            num_tokens += len(encoding.encode(value))
    num_tokens += 2  # reply priming overhead
    return num_tokens


async def compact_context_via_openai(history_to_summarize: list[dict[str, str]], openai_key: str) -> str:
    """Uses OpenAI gpt-4o-mini to summarize older chat history and compact context."""
    history_text = ""
    for msg in history_to_summarize:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        history_text += f"{role.upper()}: {content}\n\n"
        
    summary_prompt = (
        "Summarize the following chat history between a user and an AI assistant named Ideator. "
        "Keep the summary concise and focused on the key ideas discussed, user requirements, and system takeaways. "
        "Return only the direct summary without conversational filler:\n\n"
        f"{history_text}"
    )
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {openai_key}"},
            json={
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant that summarizes chat logs concisely."},
                    {"role": "user", "content": summary_prompt}
                ],
                "temperature": 0.3,
                "max_tokens": 1000,
            }
        )
        resp.raise_for_status()
        summary = resp.json()["choices"][0]["message"]["content"].strip()
        return summary


async def manage_context_size(messages: list[dict[str, str]], openai_key: str | None = None) -> list[dict[str, str]]:
    """
    Checks token count. If it exceeds 94k tokens, attempts compaction using OpenAI gpt-4o-mini
    (if key is available). If that is unavailable or fails, falls back to automatic trimming (discarding oldest history).
    """
    token_count = count_message_tokens(messages)
    if token_count <= 94000:
        return messages
        
    logger.info("Context size of %d tokens exceeds 94k threshold. Starting compaction/trimming...", token_count)
    
    # 1. Separate system messages vs conversation history
    system_msgs = [m for m in messages if m["role"] == "system"]
    non_system_msgs = [m for m in messages if m["role"] != "system"]
    
    if len(non_system_msgs) <= 5:
        # Avoid infinite loops for few but massive messages: truncate content directly
        for msg in messages:
            if len(msg["content"]) > 100000:
                msg["content"] = msg["content"][:100000] + "\n\n...[Content truncated to reduce context size]..."
        return messages

    # Preserve last 4 history messages + the final user message (total 5)
    history_to_summarize = non_system_msgs[:-5]
    preserved_recent = non_system_msgs[-5:]
    
    if openai_key and len(history_to_summarize) > 0:
        try:
            logger.info("Running OpenAI gpt-4o-mini compaction on %d older messages...", len(history_to_summarize))
            summary_text = await compact_context_via_openai(history_to_summarize, openai_key)
            summary_msg = {
                "role": "system",
                "content": f"Summary of earlier conversation history:\n{summary_text}"
            }
            new_messages = system_msgs + [summary_msg] + preserved_recent
            new_token_count = count_message_tokens(new_messages)
            if new_token_count <= 94000:
                logger.info("OpenAI compaction succeeded. Context reduced to %d tokens.", new_token_count)
                return new_messages
            else:
                logger.warning("Compacted context still exceeds 94k (%d tokens). Falling back to trimming.", new_token_count)
                messages = new_messages
        except Exception as e:
            logger.error("OpenAI context compaction failed: %s. Falling back to trimming.", e)

    # 2. Direct Trimming Fallback
    logger.info("Trimming history to bring context under 94k tokens...")
    while count_message_tokens(system_msgs + non_system_msgs) > 94000 and len(non_system_msgs) > 2:
        non_system_msgs.pop(0)  # discard the oldest conversation turn
        
    return system_msgs + non_system_msgs


async def generate_response(
    prompt: str,
    history: list[Any],
    task: str = "conversation",
    context: str | None = None,
    model: str | None = None,
    system_prompt: str | None = None,
    max_tokens: int = 8090,
) -> str:
    """Route by task, then fall back through every configured provider/model."""
    providers = _provider_config()
    order = _provider_order(task)
    # A specific model name is provider-bound, so don't fan out to unrelated providers.
    if model:
        order = [name for name in order if task in providers.get(name, {}).get("tasks", [])]
    messages = _build_messages(prompt, history, context, system_prompt)
    
    # Auto-trim / compact context if it exceeds 94k tokens
    openai_keys = _provider_keys("openai")
    openai_key = openai_keys[0] if openai_keys else None
    messages = await manage_context_size(messages, openai_key)

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


ALLOWED_SKILLS = {"collision_check", "web_research", "academic_search", "github_search", "fetch_newsletter_feeds", "generate_chart"}

_SKILL_ROUTER_PROMPT = """You are the skill router for Ideator, a tool that helps people develop novel ideas for projects and hackathons.
Given the user's message, decide which skills/tools are needed before answering.
Available skills:
- collision_check: check the user's idea against a stored database of previously claimed ideas. Use when the message describes OR asks for a concrete product, startup, project, or research idea.
- web_research: search the web for general sources, products, competitors, or news. Use when the user asks about existing products, technologies, domain context, or what's out there.
- academic_search: search academic literature (arXiv) for papers, research background, math equations, scientific papers, algorithms, or machine learning papers. Use when the user asks for theoretical details, advanced algorithms, academic references, scientific projects, or ML research.
- github_search: search open-source repositories on GitHub. Use when the user asks for code, libraries, implementation examples, software repositories, or existing GitHub code related to an idea.
- fetch_newsletter_feeds: fetch recent newsletter updates, blog posts, articles, and news from various domains/departments (e.g. tech, science, business, startups). Use when the user asks for newsletters, blog updates, industry trends, recent news, or topic-specific articles in specific fields.
- generate_chart: generate a visual chart (bar, line, pie, or scatter graph) representing numbers, metrics, user growth, or statistics using matplotlib and returns the link. Use when the user asks to draw, plot, visualize, or show a graph or chart.

Respond with ONLY a JSON array of the skill names needed (for example ["academic_search", "github_search"]).
If no skills are needed, respond with [].
When in doubt, include relevant skills — it is better to over-search than to give an uninformed answer."""


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


_CHART_PARAMS_PROMPT = """You are Ideator's chart parameter extractor.
Given the user's request to draw/plot a chart or graph, extract the structural parameters to draw it.
You MUST output ONLY a valid JSON object with the following keys:
- chart_type: "bar", "line", "pie", or "scatter" (default to "bar" if unclear)
- title: A descriptive title for the chart (default to "Statistics" or similar if unclear)
- labels: A JSON array of string labels (X-axis categories or pie segments)
- values: A JSON array of float numbers matching the labels
- x_label: Optional label for the X-axis (default to empty string)
- y_label: Optional label for the Y-axis (default to empty string)

If the user didn't provide specific labels or values, try to infer reasonable mock data based on their request context.
Respond with ONLY the JSON object, no Markdown blocks, no explanations."""


async def extract_chart_params(prompt: str) -> dict[str, Any]:
    """Extract chart drawing parameters from the user's prompt using LLM routing."""
    providers = _provider_config()
    groq = providers.get("groq", {}).get("models", {})
    fast_model = groq.get("fast") or groq.get("default")
    default_params = {
        "chart_type": "bar",
        "title": "Chart",
        "labels": ["A", "B", "C"],
        "values": [1.0, 2.0, 3.0],
        "x_label": "",
        "y_label": ""
    }
    try:
        response = await generate_response(
            prompt,
            history=[],
            task="routing",
            model=fast_model,
            system_prompt=_CHART_PARAMS_PROMPT,
            max_tokens=300,
        )
        match = re.search(r"\{.*?\}", response, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            for k, v in default_params.items():
                if k not in parsed:
                    parsed[k] = v
            return parsed
    except Exception:
        pass
    return default_params


async def generate_chat_title(first_prompt: str) -> str:
    """Generate a short, catchy chat title (2-5 words) using gpt-4o-mini (or Groq fast model as fallback)."""
    system_prompt = (
        "You are a helper that generates a short, catchy, and concise title (2-5 words) "
        "for a chat session based on the user's first prompt. Do NOT use markdown, quotes, "
        "preambles, or conversational filler. Return ONLY the title itself."
    )
    providers = _provider_config()
    openai_keys = _provider_keys("openai")
    
    # Try using OpenAI model (gpt-4o-mini)
    if openai_keys:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {openai_keys[0]}"},
                    json={
                        "model": "gpt-4o-mini",
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": first_prompt}
                        ],
                        "temperature": 0.5,
                        "max_tokens": 15,
                    }
                )
                resp.raise_for_status()
                title = resp.json()["choices"][0]["message"]["content"].strip()
                if title:
                    return title
        except Exception as exc:
            logger.warning("Failed to generate chat title via OpenAI: %s", exc)
            
    # Fallback to whatever fast model is configured (e.g. Groq llama-3)
    try:
        groq = providers.get("groq", {}).get("models", {})
        fast_model = groq.get("fast") or groq.get("default")
        title = await generate_response(
            first_prompt,
            history=[],
            task="routing",
            model=fast_model,
            system_prompt=system_prompt,
            max_tokens=15,
        )
        return title.strip().replace('"', '').replace("'", "")
    except Exception:
        pass
        
    return first_prompt[:25] + "..." if len(first_prompt) > 25 else first_prompt
