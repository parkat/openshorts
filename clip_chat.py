"""Gemini chat helper scoped to a single clip's transcript.

Lets the user converse with Gemini about ONE short's script to generate titles,
descriptions, hashtags, hooks, etc. Mirrors the google-genai usage in thumbnail.py
(single-prompt string with embedded conversation history) so it stays compatible
with the pinned google-genai version.
"""
import json
from google import genai
from google.genai import types

# Same fast text model used elsewhere for title refinement.
CHAT_MODEL = "gemini-flash-latest"

SYSTEM_PREAMBLE = """You are a viral short-form video strategist helping a creator repurpose ONE short clip for TikTok, Instagram Reels, and YouTube Shorts.

You are given the clip's transcript — the exact words spoken in this specific short. Treat it as the single source of truth about the clip's content.

Help with whatever the creator asks: punchy titles, platform-specific captions/descriptions, hashtag sets, opening hooks, on-screen text, or a content angle.

Guidelines:
- Ground everything in the actual transcript; don't invent facts it doesn't support.
- Be platform-savvy and concise. For titles/hashtags, return a clean scannable list.
- Match the language of the transcript.
- Output the deliverable directly with minimal preamble. Use markdown lists where helpful."""


def chat_about_clip(api_key, script, user_message, conversation_history=None):
    """Return Gemini's reply (markdown text) for a message about this clip.

    conversation_history: list of {"role": "user"|"assistant", "content": str},
    excluding the current user_message.
    """
    client = genai.Client(api_key=api_key)

    history_text = ""
    if conversation_history:
        for msg in conversation_history:
            role = msg.get("role", "user")
            label = "ASSISTANT" if role in ("assistant", "model") else "USER"
            content = str(msg.get("content", "")).strip()
            if content:
                history_text += f"\n{label}: {content}"

    prompt = f"""{SYSTEM_PREAMBLE}

CLIP TRANSCRIPT:
\"\"\"
{script}
\"\"\"

CONVERSATION SO FAR:{history_text if history_text else " (none yet)"}

USER'S NEW MESSAGE:
{user_message}

Respond directly to the user's new message."""

    response = client.models.generate_content(
        model=CHAT_MODEL,
        contents=[prompt],
        config=types.GenerateContentConfig(
            temperature=0.9,
        ),
    )
    return (response.text or "").strip()
