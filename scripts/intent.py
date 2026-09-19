#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Turn free-text Hebrew (or mixed Hebrew/English) into a device command.

Plain string matching cannot cross languages: a device the Smart Life app calls
"Living room light" will never substring-match "האור בסלון". An LLM gets the
live device list and does the bridging, returning a fixed JSON shape.

Any OpenAI-compatible /chat/completions endpoint works, so the provider is a
config change rather than a code change. Defaults to NVIDIA's hosted models.

Configuration:
    LLM_URL     endpoint base, default https://integrate.api.nvidia.com/v1
    LLM_KEY     bearer token; falls back to NVIDIA_API_KEY, then GROQ_API_KEY,
                then STT_KEY (Groq serves both speech and chat on one key)
    LLM_MODEL   default meta/llama-3.3-70b-instruct
    LLM_TIMEOUT default 30 seconds
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "meta/llama-3.3-70b-instruct"
COMPLETIONS_PATH = "/chat/completions"

ACTIONS = ("on", "off", "status", "list", "brightness", "unclear")

# Models that are not held to a schema sometimes wrap JSON in prose or a code
# fence. Pulling out the outermost object is more robust than trusting them.
JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

SYSTEM = """You translate spoken home-automation requests into a single device command.

The user speaks Hebrew, often mixing in English device names. Device names in \
the account may be in either language, so match by meaning, not by spelling: \
"האור בסלון" refers to a device that might be named "Living room light", and \
"המנורה על השולחן" to one named "Desk lamp".

Reply with ONLY a JSON object, no prose, no code fence, with exactly these keys:
{"action": one of on|off|status|list|brightness|unclear,
 "device_id": the exact id from the device list, or null,
 "value": brightness percentage 1-100 for the brightness action, else null,
 "reply_he": one short sentence in Hebrew}

Rules:
- Pick a device only when one device clearly fits. If two or more fit equally \
well, or you are guessing, use "unclear" and ask which one in reply_he.
- device_id must be copied exactly from the device list. Never invent one.
- "תדליק"/"תפעיל"/"תעלה" mean on; "תכבה"/"תסגור"/"תוריד" mean off.
- Asking what state something is in ("מה המצב", "האור דולק?") is "status".
- Asking what devices exist ("מה יש לי", "תראה לי את המכשירים") is "list", \
with device_id null.
- A percentage, or "תעמעם"/"יותר בהיר" with a light, is "brightness".
- Anything unrelated to controlling these devices is "unclear", with reply_he \
saying briefly that you only control the listed devices.
- reply_he is always Hebrew, one short sentence, no emoji, no device ids."""


def _device_lines(devices: List[Dict[str, Any]]) -> str:
    return "\n".join(
        f"- id={d.get('id')} | name={d.get('name', '')!r} "
        f"| category={d.get('category', '?')} "
        f"| {'online' if d.get('online', True) else 'offline'}"
        for d in devices
    )


class IntentParser:
    def __init__(self, url: str, key: str, model: str, timeout: float = 30.0):
        self.url = url.rstrip("/")
        if not self.url.endswith(COMPLETIONS_PATH):
            self.url += COMPLETIONS_PATH
        self.key = key
        self.model = model
        self.timeout = timeout

    @classmethod
    def from_config(cls, get) -> Optional["IntentParser"]:
        """Build from a config getter, or None when no key is configured."""
        key = (
            get("LLM_KEY")
            or get("NVIDIA_API_KEY")
            or get("GROQ_API_KEY")
            # Groq serves chat and speech off the same key, so if STT is
            # configured against Groq the chat side is already paid for.
            or get("STT_KEY")
        )
        if not key:
            logger.info(
                "No LLM key (LLM_KEY / NVIDIA_API_KEY) — natural language and "
                "voice control disabled"
            )
            return None
        parser = cls(
            url=get("LLM_URL") or DEFAULT_URL,
            key=key,
            model=get("LLM_MODEL") or DEFAULT_MODEL,
            timeout=float(get("LLM_TIMEOUT") or 30.0),
        )
        logger.info("Intent model: %s at %s", parser.model, parser.url)
        return parser

    async def parse(self, text: str, devices: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Map an utterance onto one device command.

        Returns the validated dict. Raises on API or parse failure — the caller
        decides what to tell the user.
        """
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": (
                    f"Devices in the account:\n{_device_lines(devices)}\n\n"
                    f"The user said: {text}"
                )},
            ],
            # Low temperature: this is classification, not writing.
            "temperature": 0,
            "max_tokens": 400,
            # Honoured by most OpenAI-compatible servers; harmlessly ignored by
            # the rest, which is why the response is still parsed defensively.
            "response_format": {"type": "json_object"},
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.url,
                headers={"Authorization": f"Bearer {self.key}"},
                json=body,
            )

        if response.status_code != 200:
            raise RuntimeError(
                f"{self.model} returned {response.status_code}: {response.text[:300]}"
            )

        content = response.json()["choices"][0]["message"]["content"]
        return self.validate(content, devices)

    @staticmethod
    def validate(content: str, devices: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Coerce a model's reply into a usable command, or into a question.

        Without a schema guarantee the reply may be malformed, may omit keys, or
        may name a device that does not exist. Every one of those becomes a
        clarifying question rather than an action: guessing would switch the
        wrong thing in someone's home.
        """
        match = JSON_RE.search(content or "")
        if not match:
            raise ValueError(f"no JSON in model reply: {content[:200]!r}")
        result = json.loads(match.group(0))

        if not isinstance(result, dict):
            raise ValueError(f"model reply was not an object: {content[:200]!r}")

        action = str(result.get("action") or "").strip().lower()
        if action not in ACTIONS:
            logger.warning("Model returned unknown action %r", result.get("action"))
            action = "unclear"

        device_id = result.get("device_id") or None
        if device_id is not None:
            device_id = str(device_id)

        value = result.get("value")
        if not isinstance(value, int):
            try:
                value = int(str(value).strip())
            except (TypeError, ValueError):
                value = None

        reply = str(result.get("reply_he") or "").strip()

        known = {d.get("id") for d in devices}
        if device_id is not None and device_id not in known:
            logger.warning("Model returned unknown device_id %r", device_id)
            action, device_id = "unclear", None
            reply = "לא הצלחתי לזהות את המכשיר. איזה מכשיר התכוונת?"

        if action in ("on", "off", "status", "brightness") and not device_id:
            action = "unclear"
            reply = reply or "על איזה מכשיר מדובר?"

        if not reply:
            reply = "לא הבנתי את הבקשה."

        return {
            "action": action,
            "device_id": device_id,
            "value": value,
            "reply_he": reply,
        }
