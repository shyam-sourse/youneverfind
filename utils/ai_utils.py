# ╔══════════════════════════════════════════════════════════════════╗
# ║                                                                  ║
# ║   ░█▀▀░█▀█░█▀▄░█▀▀░█░█   ░█▀▄░█▀▀░█░█░█▀▀                     ║
# ║   ░█░░░█░█░█░█░█▀▀░▄▀▄   ░█░█░█▀▀░▀▄▀░▀▀█                     ║
# ║   ░▀▀▀░▀▀▀░▀▀░░▀▀▀░▀░▀   ░▀▀░░▀▀▀░░▀░░▀▀▀                     ║
# ║                                                                  ║
# ║            © 2026 CodeX Devs — All Rights Reserved              ║
# ║                                                                  ║
# ║   AI backend: GROQ  (https://console.groq.com)                   ║
# ║                                                                  ║
# ╚══════════════════════════════════════════════════════════════════╝

import aiohttp
import base64
import io
import time
import os
import random
import json
import asyncio
from types import SimpleNamespace
from langdetect import detect
from gtts import gTTS
from urllib.parse import quote
from utils.config_loader import load_current_language, config
try:
    from duckduckgo_search import AsyncDDGS
except ImportError:
    from ddgs import AsyncDDGS
from dotenv import load_dotenv

load_dotenv()

current_language = load_current_language()
internet_access = config.get('INTERNET_ACCESS', True)


from utils.groq_keys import (
    key_manager,
    GroqError,
    GroqAPIError,
    error_message,
)

# kept so older imports (`from utils.ai_utils import GeminiError`) don't break
GeminiError = GroqError

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODELS_URL = "https://api.groq.com/openai/v1/models"

# ── model availability cache ──────────────────────────────────────────────
# Every key can have a different set of allowed models. Asking a key for a
# model it cannot use returns 404 and wastes a request, which is what filled
# the console with "The model ... does not exist or you do not have access".
# We ask each key ONCE which models it can use, cache the answer, and also
# remember any model a key gets 404 on so it is never tried on that key again.
_MODEL_CACHE_TTL = 3600
_model_cache = {}          # key -> (expires_at, set(model_ids))
_model_blocklist = {}      # key -> set(model_ids that 404'd)


def _key_id(key):
    return key[-8:] if key else ""


async def _fetch_models(key):
    """Return the set of model ids this key may use (empty set = unknown)."""
    cached = _model_cache.get(_key_id(key))
    now = time.time()
    if cached and cached[0] > now:
        return cached[1]
    models = set()
    try:
        async with aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=20)
        ) as session:
            async with session.get(
                GROQ_MODELS_URL, headers={"Authorization": f"Bearer {key}"}
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    for item in data.get("data") or []:
                        mid = item.get("id")
                        if mid:
                            models.add(mid)
    except Exception:
        models = set()
    if models:
        _model_cache[_key_id(key)] = (now + _MODEL_CACHE_TTL, models)
    return models


def _mark_unsupported(key, model):
    _model_blocklist.setdefault(_key_id(key), set()).add(model)


async def _is_supported(key, model):
    """False only when we positively know this key cannot use this model."""
    if model in _model_blocklist.get(_key_id(key), ()):
        return False
    available = await _fetch_models(key)
    if not available:
        return True  # unknown - let the request decide
    return model in available

# Groq model rotation list - tried in this order. If one is unavailable,
# decommissioned, or your key has no access, the bot moves to the next model.
GROQ_MODELS = [
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "openai/gpt-oss-20b",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.1-8b-instant",
]

# Vision-capable Groq models (used for image analysis)
GROQ_VISION_MODELS = [
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
]

# Groq is OpenAI-compatible, so a Gemini model id in config.yml would 404.
_LEGACY_MODEL_PREFIXES = ("gemini", "models/gemini", "gpt-3.5", "gpt-4")


def _normalize_model(model):
    """Ignore leftover Gemini/OpenAI model ids from the old config."""
    if not model or str(model).lower().startswith(_LEGACY_MODEL_PREFIXES):
        return None
    return str(model)


def default_model():
    return _normalize_model(config.get("MODEL_ID")) or GROQ_MODELS[0]


class _Completion:
    """OpenAI-style response object so every existing caller
    (response.choices[0].message.content) keeps working unchanged."""

    def __init__(self, content, tool_calls=None, raw=None):
        message = SimpleNamespace(
            role="assistant",
            content=content,
            tool_calls=tool_calls or None,
        )
        self.choices = [SimpleNamespace(message=message, finish_reason=None)]
        self.raw = raw

    @property
    def text(self):
        """Convenience alias - the old Gemini responses exposed `.text`."""
        return self.choices[0].message.content


def _wrap_tool_calls(raw_calls):
    calls = []
    for call in raw_calls or []:
        fn = call.get("function", {}) or {}
        calls.append(
            SimpleNamespace(
                id=call.get("id"),
                type=call.get("type", "function"),
                function=SimpleNamespace(
                    name=fn.get("name"),
                    arguments=fn.get("arguments") or "{}",
                ),
            )
        )
    return calls or None


def _clean_messages(messages):
    """Normalise the bot's message history into the Groq/OpenAI schema."""
    cleaned = []
    for msg in messages:
        if not isinstance(msg, dict):
            msg = {"role": "user", "content": str(msg)}
        role = msg.get("role", "user")
        if role in ("model", "bot"):
            role = "assistant"
        item = {"role": role, "content": msg.get("content", "") or ""}
        # tool plumbing must be preserved verbatim
        if msg.get("tool_calls"):
            item["tool_calls"] = msg["tool_calls"]
        if msg.get("tool_call_id"):
            item["tool_call_id"] = msg["tool_call_id"]
        if msg.get("name") and role in ("tool", "function"):
            item["name"] = msg["name"]
        if not item["content"] and not item.get("tool_calls"):
            continue
        cleaned.append(item)
    return cleaned


async def _groq_request(key, payload, timeout=180):
    """One HTTP call to Groq. Raises GroqAPIError with the real status code
    so the key manager can decide: rotate key, rotate model, or give up."""
    model = payload.get("model")
    # Skip the call entirely when this key is known not to have the model.
    if model and not await _is_supported(key, model):
        raise GroqAPIError(404, f"model {model} not available for this key (skipped)")
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    async with aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=timeout)
    ) as session:
        async with session.post(GROQ_API_URL, headers=headers, json=payload) as resp:
            body = await resp.text()
            if resp.status != 200:
                detail = body
                try:
                    parsed = json.loads(body)
                    detail = (
                        parsed.get("error", {}).get("message")
                        or parsed.get("error", {}).get("code")
                        or body
                    )
                except Exception:
                    pass
                if resp.status in (400, 404) and model:
                    _mark_unsupported(key, model)
                raise GroqAPIError(resp.status, str(detail)[:500])
            return json.loads(body)


def _message_text(message):
    """Groq reasoning models (gpt-oss-*) can put everything in `reasoning`
    and leave `content` empty - that produced "Empty response from model"."""
    for field in ("content", "reasoning", "reasoning_content"):
        value = message.get(field)
        if isinstance(value, list):
            value = "".join(
                part.get("text", "") for part in value if isinstance(part, dict)
            )
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""



async def chat_completion(model=None, messages=None, tools=None, **kwargs):
    """Send a chat completion to Groq with KEY + MODEL ROTATION.

    - Every GROQ_API_KEY line in .env is loaded (one key per line, or comma
      separated) and rotated round-robin.
    - A key that is rate limited / out of quota is parked on a cooldown and the
      next key is used automatically; an invalid key is dropped for the run.
    - Each key also walks the model rotation list when a model is unavailable
      or decommissioned.
    - If everything fails the user gets a clear message, e.g.
      "AI limit reached ..." instead of a crash.
    """
    payload_messages = _clean_messages(messages or [])
    wanted = _normalize_model(model)
    candidates = ([wanted] if wanted else []) + [
        m for m in GROQ_MODELS if m != wanted
    ]

    base_payload = {"messages": payload_messages}
    if tools:
        base_payload["tools"] = tools
        base_payload["tool_choice"] = kwargs.pop("tool_choice", "auto")
    if kwargs.get("temperature") is not None:
        base_payload["temperature"] = kwargs["temperature"]
    if kwargs.get("max_tokens") is not None:
        base_payload["max_tokens"] = kwargs["max_tokens"]
    if kwargs.get("top_p") is not None:
        base_payload["top_p"] = kwargs["top_p"]

    async def _call(key, candidate):
        data = await _groq_request(key, {**base_payload, "model": candidate})
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message", {}) or {}
        text = _message_text(message)
        calls = _wrap_tool_calls(message.get("tool_calls"))
        if not text and not calls:
            raise RuntimeError("Empty response from model")
        return _Completion(text, calls, raw=data)

    try:
        return await key_manager.run(_call, models=candidates)
    except GroqError as e:
        # Never crash the bot - hand the user a readable reason.
        return _Completion(e.user_message)


async def ask_ai(prompt, system=None, model=None, **kwargs):
    """Small helper: one-shot prompt -> text (with full key rotation)."""
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    completion = await chat_completion(
        model=model or default_model(),
        messages=messages,
        **kwargs,
    )
    return completion.choices[0].message.content


#: old name kept alive so nothing that imported it breaks
ask_gemini = ask_ai


async def vision_completion(image_bytes, prompt=None, mime_type="image/jpeg", model=None):
    """Describe / analyse an image with Groq's vision models.

    Returns a `_Completion` (so `.text` and `.choices[0].message.content` both
    work). Raises `GroqError` when every key + vision model failed.
    """
    prompt = prompt or "What is shown in this image? Provide a detailed description."
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{b64}"},
                },
            ],
        }
    ]
    wanted = _normalize_model(model)
    candidates = ([wanted] if wanted else []) + [
        m for m in GROQ_VISION_MODELS if m != wanted
    ]

    async def _call(key, candidate):
        data = await _groq_request(
            key, {"model": candidate, "messages": messages, "max_tokens": 1024}
        )
        text = _message_text(
            ((data.get("choices") or [{}])[0].get("message") or {})
        )
        if not text:
            raise RuntimeError("Empty response from model")
        return _Completion(text, raw=data)

    return await key_manager.run(_call, models=candidates)


async def generate_response(instructions, history):
    if not key_manager.has_keys:
        return error_message("no_keys")

    messages = [
        {"role": "system", "name": "instructions", "content": instructions},
        *history,
    ]

    tools = [
        {
            "type": "function",
            "function": {
                "name": "searchtool",
                "description": "Searches the internet.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The query for search engine",
                        }
                    },
                    "required": ["query"],
                },
            },
        }
    ]
    response = await chat_completion(
        model=default_model(),
        messages=messages,
        tools=tools if config.get('INTERNET_ACCESS', True) else None,
    )
    response_message = response.choices[0].message
    tool_calls = response_message.tool_calls

    if tool_calls:
        available_functions = {
            "searchtool": duckduckgotool,
        }
        # append the assistant turn as a plain dict (JSON serialisable)
        messages.append(
            {
                "role": "assistant",
                "content": response_message.content or "",
                "tool_calls": [
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {
                            "name": c.function.name,
                            "arguments": c.function.arguments,
                        },
                    }
                    for c in tool_calls
                ],
            }
        )

        for tool_call in tool_calls:
            function_name = tool_call.function.name
            function_to_call = available_functions.get(function_name)
            if function_to_call is None:
                continue
            try:
                function_args = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                function_args = {}
            function_response = await function_to_call(
                query=function_args.get("query", "")
            )
            messages.append(
                {
                    "tool_call_id": tool_call.id,
                    "role": "tool",
                    "name": function_name,
                    "content": function_response,
                }
            )
        second_response = await chat_completion(
            model=default_model(),
            messages=messages,
        )
        return second_response.choices[0].message.content
    return response_message.content


async def duckduckgotool(query) -> str:
    if not config.get('INTERNET_ACCESS', True):
        return "internet access has been disabled by user"
    blob = ''
    results = await AsyncDDGS(proxy=None).text(query, max_results=6)
    try:
        for index, result in enumerate(results[:6]):  # Limiting to 6 results
            blob += f'[{index}] Title : {result["title"]}\nSnippet : {result["body"]}\n\n\n Provide a cohesive response base on provided Search results'
    except Exception as e:
        blob += f"Search error: {e}\n"
    return blob


async def poly_image_gen(session, prompt):
    seed = random.randint(1, 100000)
    image_url = f"https://image.pollinations.ai/prompt/{prompt}?seed={seed}"
    async with session.get(image_url) as response:
        image_data = await response.read()
        return io.BytesIO(image_data)

async def generate_image_prodia(prompt, model, sampler, seed, neg):
    print("\033[1;32m(Prodia) Creating image for :\033[0m", prompt)
    start_time = time.time()
    async def create_job(prompt, model, sampler, seed, neg):
        url = 'https://api.prodia.com/generate'
        params = {
            'new': 'true',
            'prompt': f'{quote(prompt)}',
            'model': model,
            'steps': '100',
            'cfg': '9.5',
            'seed': f'{seed}',
            'sampler': sampler,
            'upscale': 'True',
            'aspect_ratio': 'square'
        }
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params) as response:
                data = await response.json()
                return data['job']

    job_id = await create_job(prompt, model, sampler, seed, neg)
    url = f'https://api.prodia.com/job/{job_id}'
    headers = {
        'authority': 'api.prodia.com',
        'accept': '*/*',
    }

    async with aiohttp.ClientSession() as session:
        while True:
            async with session.get(url, headers=headers) as response:
                json = await response.json()
                if json['status'] == 'succeeded':
                    async with session.get(f'https://images.prodia.xyz/{job_id}.png?download=1', headers=headers) as response:
                        content = await response.content.read()
                        img_file_obj = io.BytesIO(content)
                        duration = time.time() - start_time
                        print(f"\033[1;34m(Prodia) Finished image creation\n\033[0mJob id : {job_id}  Prompt : ", prompt, "in", duration, "seconds.")
                        return img_file_obj

async def text_to_speech(text):
    bytes_obj = io.BytesIO()
    detected_language = detect(text)
    tts = gTTS(text=text, lang=detected_language)
    tts.write_to_fp(bytes_obj)
    bytes_obj.seek(0)
    return bytes_obj
