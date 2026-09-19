#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Turn free-text Hebrew (or mixed Hebrew/English) into a device command.

Plain string matching cannot cross languages: a device the Smart Life app calls
"Living room light" will never substring-match "האור בסלון". Claude gets the
live device list and does the bridging, returning a fixed JSON shape via
structured outputs rather than prose we would have to parse.

Configuration:
    ANTHROPIC_API_KEY   required
    INTENT_MODEL        default claude-opus-5
"""

import json
import logging
from typing import Any, Dict, List, Optional

from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "claude-opus-5"

ACTIONS = ("on", "off", "status", "list", "brightness", "unclear")

# additionalProperties:false and a fully-required property set are what make
# the response shape guaranteed — every field is always present, nullable
# where it may not apply.
SCHEMA = {
    "type": "object",
    "properties": {
        "action": {
            "type": "string",
            "enum": list(ACTIONS),
            "description": "What the speaker wants. 'unclear' when you cannot tell, "
                           "or when several devices fit equally well.",
        },
        "device_id": {
            "type": ["string", "null"],
            "description": "The exact id of the single matching device, or null "
                           "for the 'list' and 'unclear' actions.",
        },
        "value": {
            "type": ["integer", "null"],
            "description": "Brightness percentage 1-100 for the 'brightness' action, else null.",
        },
        "reply_he": {
            "type": "string",
            "description": "One short sentence in Hebrew. For 'unclear', the question "
                           "to ask back. Otherwise a natural confirmation of what is "
                           "about to happen.",
        },
    },
    "required": ["action", "device_id", "value", "reply_he"],
    "additionalProperties": False,
}

SYSTEM = """You translate spoken home-automation requests into a single device command.

The user speaks Hebrew, often mixing in English device names. Device names in \
the Tuya account may be in either language, so match by meaning, not by \
spelling: "האור בסלון" refers to a device that might be named "Living room \
light", and "המנורה על השולחן" to one named "Desk lamp".

Rules:
- Pick a device only when one device clearly fits. If two or more fit equally \
well, or you are guessing, use action "unclear" and ask which one in reply_he.
- device_id must be copied exactly from the device list. Never invent one.
- An offline device can still be chosen; the caller reports the failure.
- "תדליק"/"תפעיל"/"תעלה" mean on; "תכבה"/"תסגור"/"תוריד" mean off.
- Asking what state something is in ("מה המצב", "האור דולק?") is "status".
- Asking what devices exist ("מה יש לי", "תראה לי את המכשירים") is "list".
- A percentage or "תעמעם"/"יותר בהיר" with a light is "brightness" with value 1-100.
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
    def __init__(self, api_key: str, model: str = DEFAULT_MODEL):
        self.client = AsyncAnthropic(api_key=api_key)
        self.model = model

    @classmethod
    def from_config(cls, get) -> Optional["IntentParser"]:
        """Build from a config getter, or None when no key is configured."""
        key = get("ANTHROPIC_API_KEY")
        if not key:
            logger.info(
                "ANTHROPIC_API_KEY not set — natural language and voice control disabled"
            )
            return None
        return cls(key, get("INTENT_MODEL") or DEFAULT_MODEL)

    async def parse(self, text: str, devices: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Map an utterance onto one device command.

        Returns the validated dict. Raises on API failure — the caller decides
        what to tell the user.
        """
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=1024,
            system=SYSTEM,
            messages=[{
                "role": "user",
                "content": (
                    f"Devices in the account:\n{_device_lines(devices)}\n\n"
                    f"The user said: {text}"
                ),
            }],
            # effort low: this is a short classification, and latency is felt
            # directly — someone is standing in a room waiting for a light.
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": SCHEMA},
            },
        )

        if response.stop_reason == "refusal":
            raise RuntimeError("intent request was declined by the safety classifier")

        text_block = next((b.text for b in response.content if b.type == "text"), "")
        result = json.loads(text_block)

        # Structured outputs guarantee the shape, but not that a device_id is
        # real — the model could echo a plausible-looking id. Verify against
        # the list before anything gets switched.
        known = {d.get("id") for d in devices}
        if result["device_id"] is not None and result["device_id"] not in known:
            logger.warning("Model returned unknown device_id %r", result["device_id"])
            result["action"] = "unclear"
            result["device_id"] = None
            result["reply_he"] = "לא הצלחתי לזהות את המכשיר. איזה מכשיר התכוונת?"

        if result["action"] in ("on", "off", "status", "brightness") and not result["device_id"]:
            result["action"] = "unclear"
            if not result["reply_he"]:
                result["reply_he"] = "על איזה מכשיר מדובר?"

        return result
