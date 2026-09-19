#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Hebrew speech replies via ElevenLabs.

Telegram voice notes are OGG/Opus, so Opus output is requested first and the
audio is sent back as a true voice note. Some accounts or models only offer
MP3; that case falls back to sending an audio file instead of failing.

Verified against eleven_v3 with a Hebrew line: ~16 credits (~$0.0016) for a
short confirmation.

Configuration:
    ELEVENLABS_API_KEY    required — without it, replies stay text-only
    ELEVENLABS_VOICE_ID   required — a voice id from your ElevenLabs workspace
    ELEVENLABS_MODEL      default eleven_v3
    VOICE_REPLIES         auto (default) | always | never
                          auto speaks only when spoken to, so a typed message
                          gets a typed answer.
"""

import logging
import re
from typing import Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

API_ROOT = "https://api.elevenlabs.io/v1/text-to-speech"
DEFAULT_MODEL = "eleven_v3"

# Telegram renders an OGG/Opus file as a playable voice note; anything else
# arrives as an audio attachment.
OPUS_FORMAT = "opus_48000_64"
MP3_FORMAT = "mp3_44100_128"

# Speech should carry the sentence, not the markup or the emoji decoration.
TAG_RE = re.compile(r"<[^>]+>")
EMOJI_RE = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F000-\U0001F0FF️]+"
)


def speakable(text: str) -> str:
    """Reduce a reply to something worth reading aloud."""
    text = TAG_RE.sub("", text)
    text = EMOJI_RE.sub("", text)
    # Device ids and other <code> contents are unspeakable noise; collapse the
    # whitespace left behind by stripping tags.
    return " ".join(text.split()).strip()


class Speaker:
    def __init__(self, api_key: str, voice_id: str, model: str, mode: str):
        self.api_key = api_key
        self.voice_id = voice_id
        self.model = model
        self.mode = mode
        # Remembered after the first successful call so each reply does not
        # retry a format this account cannot produce.
        self._format: Optional[str] = None

    @classmethod
    def from_config(cls, get) -> Optional["Speaker"]:
        key = get("ELEVENLABS_API_KEY")
        voice = get("ELEVENLABS_VOICE_ID")
        mode = (get("VOICE_REPLIES") or "auto").strip().lower()

        if mode == "never":
            logger.info("Voice replies disabled (VOICE_REPLIES=never)")
            return None
        if not key or not voice:
            logger.info(
                "ElevenLabs not configured (no ELEVENLABS_API_KEY/VOICE_ID) — "
                "replies will be text only"
            )
            return None
        if mode not in ("auto", "always"):
            logger.warning("Unknown VOICE_REPLIES=%r — treating as auto", mode)
            mode = "auto"

        return cls(key, voice, get("ELEVENLABS_MODEL") or DEFAULT_MODEL, mode)

    def wants_voice(self, asked_by_voice: bool) -> bool:
        """always speaks; auto answers in the medium the request arrived in."""
        return self.mode == "always" or asked_by_voice

    async def synthesize(self, text: str) -> Tuple[bytes, bool]:
        """
        Render text to speech. Returns (audio, is_opus); is_opus False means
        the caller should send it as an audio file rather than a voice note.
        """
        text = speakable(text)
        if not text:
            raise ValueError("nothing speakable in this reply")

        for fmt in self._formats():
            audio = await self._request(text, fmt)
            if audio is not None:
                self._format = fmt
                return audio, fmt == OPUS_FORMAT
        raise RuntimeError("ElevenLabs rejected every output format")

    def _formats(self):
        if self._format:
            return (self._format,)
        return (OPUS_FORMAT, MP3_FORMAT)

    async def _request(self, text: str, fmt: str) -> Optional[bytes]:
        url = f"{API_ROOT}/{self.voice_id}"
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                params={"output_format": fmt},
                headers={"xi-api-key": self.api_key, "accept": "audio/*"},
                json={"text": text, "model_id": self.model},
            )

        if response.status_code == 200:
            return response.content

        body = response.text[:300]
        # An unsupported output format is worth retrying with another; a bad
        # key or voice id is not, so surface those immediately.
        if response.status_code in (400, 422) and "output_format" in body:
            logger.info("ElevenLabs rejected %s, trying the next format", fmt)
            return None
        raise RuntimeError(f"ElevenLabs returned {response.status_code}: {body}")
