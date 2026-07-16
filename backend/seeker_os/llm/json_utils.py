"""Shared JSON extraction utilities for LLM responses.

Handles markdown code fences, reasoning/thinking prefixes (e.g. Qwen,
DeepSeek, GLM models that prepend "Thinking:" before JSON), prose
preamble, and trailing text.
"""

from __future__ import annotations

import json


def extract_json_text(text: str) -> str:
    """Extract the JSON object substring from an LLM response.

    Handles:
    - Markdown code fences (```json ... ``` or ``` ... ```)
    - Reasoning/thinking prefixes (Qwen, DeepSeek, GLM, etc.)
    - Prose preamble before the JSON object
    - Trailing text after the JSON object

    Returns the extracted JSON text (not yet parsed). The caller's
    json.loads() will raise JSONDecodeError if the text is still invalid.
    """
    text = text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        lines = lines[1:]  # drop opening fence
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]  # drop closing fence
        text = "\n".join(lines).strip()

    # Fast path: clean JSON with no trailing text
    if text and text[0] in "{[":
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            pass  # may have trailing text — try raw_decode below

    decoder = json.JSONDecoder()

    # Try raw_decode from the first { — handles prose preamble
    # and trailing text in one shot. Only scan for { (not [) because
    # all SeekerOS LLM responses are JSON objects, and scanning for [
    # can match an array nested inside the object.
    idx = text.find("{")
    if idx >= 0:
        try:
            _, end_idx = decoder.raw_decode(text, idx)
            return text[idx:end_idx]
        except json.JSONDecodeError:
            pass

    # Forward scan: try raw_decode from each '{' in order.
    # This handles reasoning prefixes with stray braces (e.g. "Thinking {about} ... {json}").
    # Scanning forward (not backward) ensures we find the outermost JSON object
    # rather than an inner nested object.
    search_from = 0
    while True:
        idx = text.find("{", search_from)
        if idx < 0:
            break
        try:
            _, end_idx = decoder.raw_decode(text, idx)
            return text[idx:end_idx]
        except json.JSONDecodeError:
            search_from = idx + 1

    # Forward fallback: first '{' to end (may be truncated or invalid)
    idx = text.find("{")
    if idx >= 0:
        return text[idx:]

    # No JSON found — return original so caller's json.loads raises
    return text
