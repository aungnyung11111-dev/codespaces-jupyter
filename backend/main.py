from __future__ import annotations

import asyncio
import os
import secrets
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from openai import (
    APIError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    RateLimitError,
)
from pydantic import BaseModel, Field


# ============================================================
# Configuration
# ============================================================

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not OPENAI_API_KEY:
    raise RuntimeError(
        "OPENAI_API_KEY is missing. Put it in backend/.env"
    )

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_TTS_MODEL = os.getenv(
    "OPENAI_TTS_MODEL",
    "gpt-4o-mini-tts",
)
OPENAI_TTS_VOICE = os.getenv(
    "OPENAI_TTS_VOICE",
    "nova",
)

MAX_TEXT_LENGTH = 2_000
MAX_AUDIO_BYTES = 15 * 1024 * 1024  # 15 MB

# Keep only a limited number of sessions in memory for MVP.
MAX_CONVERSATIONS = 5_000

# Keep the last N messages per conversation.
MAX_HISTORY_MESSAGES = 20

MEDIA_DIR = Path(__file__).resolve().parent / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)


# ============================================================
# Xiao He system persona
# ============================================================

SYSTEM_PROMPT = """
你是“小禾（Xiao He 🌾）”。

你的角色：
你是一位温暖、自然、有耐心的中文聊天伙伴，同时也是中文学习陪练。

你的核心目标：
让用户感觉是在和一个真实、友善、自然的人聊天，而不是在和客服机器人聊天。

语言：
1. 默认使用自然、日常的简体中文。
2. 回复不要太正式，不要每句话都像教材。
3. 根据用户说话内容自然地接话、追问、开玩笑或表达关心。
4. 如果用户使用中文学习语境，可以帮助纠正中文。

中文学习：
1. 用户出现明显中文错误时，温柔地纠正。
2. 不要每句话都纠正，只有有帮助的时候才纠正。
3. 遇到比较难的词，可以在词语后面补充拼音，例如：
   “这个词很实用：尴尬（gāngà）。”
4. 不要给用户大段语法课，除非用户主动询问。

聊天风格：
1. 温暖、轻松、像朋友。
2. 可以适当使用表情，但不要每句话都使用。
3. 回答长度根据对话调整。
4. 用户只说一句简单的话时，不要突然回答很长。
5. 不要反复说“作为AI，我……”。
6. 不要假装自己拥有现实世界中的真实经历。
7. 不要说自己是人类。

当用户明确要求翻译、解释、学习或作业帮助时，再切换到更清晰的教学模式。
"""


# ============================================================
# OpenAI client
# ============================================================

client = AsyncOpenAI(api_key=OPENAI_API_KEY)


# ============================================================
# FastAPI application
# ============================================================

app = FastAPI(
    title="小禾 AI Companion API",
    version="1.0.0",
    description="Backend API for 小禾 (Xiao He).",
)


# ============================================================
# CORS
# ============================================================

raw_origins = os.getenv("ALLOWED_ORIGINS", "*").strip()

if raw_origins == "*":
    allowed_origins = ["*"]
    allow_credentials = False
else:
    allowed_origins = [
        origin.strip()
        for origin in raw_origins.split(",")
        if origin.strip()
    ]
    allow_credentials = True

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Static audio files
# ============================================================

app.mount(
    "/media",
    StaticFiles(directory=str(MEDIA_DIR)),
    name="media",
)


# ============================================================
# In-memory conversation storage
# ============================================================
#
# This is intentionally simple for an MVP.
#
# Production:
# Replace this with Redis/PostgreSQL or another persistent store.
# ============================================================

conversation_store: OrderedDict[
    str,
    list[dict[str, str]]
] = OrderedDict()

conversation_locks: dict[str, asyncio.Lock] = {}


def create_conversation() -> str:
    conversation_id = secrets.token_urlsafe(32)

    conversation_store[conversation_id] = []
    conversation_store.move_to_end(conversation_id)

    # Simple LRU limit.
    while len(conversation_store) > MAX_CONVERSATIONS:
        old_id, _ = conversation_store.popitem(last=False)
        conversation_locks.pop(old_id, None)

    conversation_locks[conversation_id] = asyncio.Lock()

    return conversation_id


def get_existing_conversation(conversation_id: str) -> str:
    if conversation_id not in conversation_store:
        raise HTTPException(
            status_code=404,
            detail="Conversation not found or expired.",
        )

    conversation_store.move_to_end(conversation_id)

    if conversation_id not in conversation_locks:
        conversation_locks[conversation_id] = asyncio.Lock()

    return conversation_id


def get_or_create_conversation(
    conversation_id: Optional[str],
) -> str:
    if conversation_id:
        return get_existing_conversation(conversation_id)

    return create_conversation()


# ============================================================
# Request / response models
# ============================================================

class ChatTextRequest(BaseModel):
    text: str = Field(
        ...,
        min_length=1,
        max_length=MAX_TEXT_LENGTH,
        description="User's text message.",
    )

    conversation_id: Optional[str] = Field(
        default=None,
        description="Conversation ID returned by the previous request.",
    )


class ChatTextResponse(BaseModel):
    conversation_id: str
    text: str
    response_id: str


class ChatVoiceResponse(BaseModel):
    conversation_id: str
    transcript: str
    text: str
    audio_url: str
    response_id: str


# ============================================================
# Helpers
# ============================================================

def sanitize_user_text(text: str) -> str:
    text = text.strip()

    if not text:
        raise HTTPException(
            status_code=400,
            detail="Message cannot be empty.",
        )

    if len(text) > MAX_TEXT_LENGTH:
        raise HTTPException(
            status_code=413,
            detail=f"Message is too long. Max {MAX_TEXT_LENGTH} characters.",
        )

    return text


async def generate_xiaohe_reply(
    conversation_id: str,
    user_text: str,
) -> tuple[str, str]:
    """
    Generate Xiao He's response and update conversation history.

    Returns:
        answer_text, response_id
    """

    user_text = sanitize_user_text(user_text)

    lock = conversation_locks.setdefault(
        conversation_id,
        asyncio.Lock(),
    )

    async with lock:
        history = conversation_store[conversation_id]

        # Only send the most recent part of the conversation.
        recent_history = history[-MAX_HISTORY_MESSAGES:]

        input_messages = [
            {
                "role": message["role"],
                "content": message["content"],
            }
            for message in recent_history
        ]

        input_messages.append(
            {
                "role": "user",
                "content": user_text,
            }
        )

        try:
            response = await client.responses.create(
                model=OPENAI_MODEL,
                instructions=SYSTEM_PROMPT,
                input=input_messages,
                max_output_tokens=600,
            )

        except RateLimitError:
            raise HTTPException(
                status_code=429,
                detail="OpenAI rate limit reached. Please try again later.",
            )

        except AuthenticationError:
            raise HTTPException(
                status_code=401,
                detail="OpenAI API authentication failed.",
            )

        except BadRequestError as exc:
            raise HTTPException(
                status_code=400,
                detail=f"OpenAI rejected the request: {exc}",
            )

        except APITimeoutError:
            raise HTTPException(
                status_code=504,
                detail="OpenAI request timed out.",
            )

        except APIError:
            raise HTTPException(
                status_code=502,
                detail="OpenAI API error.",
            )

        answer_text = (response.output_text or "").strip()

        if not answer_text:
            raise HTTPException(
                status_code=502,
                detail="Xiao He returned an empty response.",
            )

        # Save the conversation.
        history.append(
            {
                "role": "user",
                "content": user_text,
            }
        )

        history.append(
            {
                "role": "assistant",
                "content": answer_text,
            }
        )

        # Trim old messages.
        if len(history) > MAX_HISTORY_MESSAGES:
            del history[
                :len(history) - MAX_HISTORY_MESSAGES
            ]

        conversation_store.move_to_end(conversation_id)

        return answer_text, response.id


async def create_tts_audio(
    text: str,
) -> str:
    """
    Generate MP3 audio and return the generated filename.
    """

    filename = f"{secrets.token_hex(16)}.mp3"
    output_path = MEDIA_DIR / filename

    try:
        async with (
            client.audio.speech.with_streaming_response.create(
                model=OPENAI_TTS_MODEL,
                voice=OPENAI_TTS_VOICE,
                input=text,
                response_format="mp3",
            )
            as response
        ):
            await response.stream_to_file(output_path)

    except RateLimitError:
        raise HTTPException(
            status_code=429,
            detail="OpenAI TTS rate limit reached.",
        )

    except AuthenticationError:
        raise HTTPException(
            status_code=401,
            detail="OpenAI API authentication failed.",
        )

    except BadRequestError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"OpenAI TTS rejected the request: {exc}",
        )

    except APITimeoutError:
        raise HTTPException(
            status_code=504,
            detail="OpenAI TTS request timed out.",
        )

    except APIError:
        raise HTTPException(
            status_code=502,
            detail="OpenAI TTS API error.",
        )

    return filename


# ============================================================
# Health check
# ============================================================

@app.get("/health")
async def health_check():
    return {
        "ok": True,
        "app": "小禾",
        "model": OPENAI_MODEL,
        "tts_model": OPENAI_TTS_MODEL,
        "tts_voice": OPENAI_TTS_VOICE,
    }


# ============================================================
# POST /chat/text
# ============================================================

@app.post(
    "/chat/text",
    response_model=ChatTextResponse,
)
async def chat_text(payload: ChatTextRequest):
    conversation_id = get_or_create_conversation(
        payload.conversation_id
    )

    answer, response_id = await generate_xiaohe_reply(
        conversation_id=conversation_id,
        user_text=payload.text,
    )

    return ChatTextResponse(
        conversation_id=conversation_id,
        text=answer,
        response_id=response_id,
    )


# ============================================================
# POST /chat/voice
# ============================================================

@app.post(
    "/chat/voice",
    response_model=ChatVoiceResponse,
)
async def chat_voice(
    request: Request,
    audio: UploadFile = File(...),
    conversation_id: Optional[str] = Form(default=None),
    language: str = Form(default="zh"),
):
    # Basic content-type check.
    if audio.content_type:
        allowed_prefixes = (
            "audio/",
            "video/mp4",
            "application/octet-stream",
        )

        if not audio.content_type.startswith(
            allowed_prefixes
        ):
            raise HTTPException(
                status_code=415,
                detail="Unsupported audio file type.",
            )

    # Read upload into memory so the temp upload can be closed safely.
    audio_bytes = await audio.read()

    if not audio_bytes:
        raise HTTPException(
            status_code=400,
            detail="Audio file is empty.",
        )

    if len(audio_bytes) > MAX_AUDIO_BYTES:
        raise HTTPException(
            status_code=413,
            detail="Audio file is too large.",
        )

    filename = audio.filename or "voice.m4a"

    # Avoid importing tempfile just for this:
    # BytesIO behaves like a file for OpenAI's SDK.
    from io import BytesIO

    audio_file = BytesIO(audio_bytes)

    # The OpenAI SDK uses the file name to infer the extension.
    audio_file.name = filename

    try:
        transcription = await client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language=language or "zh",
            response_format="json",
        )

    except RateLimitError:
        raise HTTPException(
            status_code=429,
            detail="OpenAI transcription rate limit reached.",
        )

    except AuthenticationError:
        raise HTTPException(
            status_code=401,
            detail="OpenAI API authentication failed.",
        )

    except BadRequestError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Audio transcription failed: {exc}",
        )

    except APITimeoutError:
        raise HTTPException(
            status_code=504,
            detail="Transcription request timed out.",
        )

    except APIError:
        raise HTTPException(
            status_code=502,
            detail="OpenAI transcription API error.",
        )

    transcript = (transcription.text or "").strip()

    if not transcript:
        raise HTTPException(
            status_code=422,
            detail="No speech was detected.",
        )

    conversation_id = get_or_create_conversation(
        conversation_id
    )

    # Send transcription to Xiao He.
    answer, response_id = await generate_xiaohe_reply(
        conversation_id=conversation_id,
        user_text=transcript,
    )

    # Convert the answer into speech.
    audio_filename = await create_tts_audio(answer)

    # Generate an externally reachable URL based on the current request.
    base_url = str(request.base_url).rstrip("/")

    audio_url = (
        f"{base_url}/media/{audio_filename}"
    )

    return ChatVoiceResponse(
        conversation_id=conversation_id,
        transcript=transcript,
        text=answer,
        audio_url=audio_url,
        response_id=response_id,
    )