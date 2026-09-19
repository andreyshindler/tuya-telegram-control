#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Speech-to-text for Telegram voice messages.

Talks to an OpenAI-compatible /audio/transcriptions endpoint — the same shape
the hebrew-voice project on this host already uses, so its HV_STT_* settings
can be reused verbatim rather than provisioning another provider.

Configuration (config.env, or the environment; HV_* names are accepted as
fallbacks so the values can be copied across as-is):
    STT_URL / HV_STT_URL          required — endpoint base or full URL
    STT_KEY / HV_STT_KEY          required — bearer token
    STT_MODEL / HV_STT_MODEL      default whisper-large-v3
    STT_LANGUAGE / HV_STT_LANGUAGE  default he
    STT_TIMEOUT / HV_STT_TIMEOUT  default 60 seconds
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

TRANSCRIPTIONS_PATH = "/audio/transcriptions"


class SpeechConfigError(RuntimeError):
    """Raised when transcription is requested but not configured."""


class Transcriber:
    def __init__(self, url: str, key: str, model: str, language: str, timeout: float):
        self.url = self._endpoint(url)
        self.key = key
        self.model = model
        self.language = language
        self.timeout = timeout

    @staticmethod
    def _endpoint(url: str) -> str:
        """
        Accept either a full transcription URL or the API base.

        hebrew-voice stores whichever form its provider wants, so normalise
        rather than assuming: only append the path when it isn't already there.
        """
        url = url.rstrip("/")
        if url.endswith(TRANSCRIPTIONS_PATH):
            return url
        return url + TRANSCRIPTIONS_PATH

    @classmethod
    def from_config(cls, get) -> Optional["Transcriber"]:
        """
        Build from a config getter, or return None if STT isn't configured.

        Voice is an optional feature — a missing key disables voice rather
        than stopping the bot, so the text commands keep working.
        """
        url = get("STT_URL") or get("HV_STT_URL")
        key = get("STT_KEY") or get("HV_STT_KEY")
        if not url or not key:
            logger.info("STT not configured (no STT_URL/STT_KEY) — voice messages disabled")
            return None
        return cls(
            url=url,
            key=key,
            model=get("STT_MODEL") or get("HV_STT_MODEL") or "whisper-large-v3",
            language=get("STT_LANGUAGE") or get("HV_STT_LANGUAGE") or "he",
            timeout=float(get("STT_TIMEOUT") or get("HV_STT_TIMEOUT") or 60.0),
        )

    async def transcribe(self, audio: bytes, filename: str = "voice.ogg") -> str:
        """
        Transcribe audio bytes. Telegram delivers voice as OGG/Opus, which
        Whisper-compatible endpoints accept directly — no ffmpeg step.
        """
        files = {"file": (filename, audio, "audio/ogg")}
        data = {"model": self.model, "language": self.language}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.url,
                headers={"Authorization": f"Bearer {self.key}"},
                files=files,
                data=data,
            )

        if response.status_code != 200:
            # The body usually explains it (bad key, model name, quota), and it
            # is far more useful in the log than a bare status code.
            raise RuntimeError(
                f"STT returned {response.status_code}: {response.text[:300]}"
            )

        payload = response.json()
        text = (payload.get("text") or "").strip()
        if not text:
            raise RuntimeError("STT returned an empty transcript")
        return text
