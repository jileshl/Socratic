"""LLM invocation helpers for OpenRouter and structured prompts."""

import os
import json
from typing import Any
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage
from socratic_tutor import config


def get_llm(model: str = config.SPECIALIST_MODEL, temperature: float = 0.2) -> ChatOpenAI:
    """Return an initialized ChatOpenAI client configured for OpenRouter."""
    api_key = config.OPENROUTER_API_KEY or config.OPENAI_API_KEY or "placeholder"
    base_url = config.OPENROUTER_BASE_URL
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        api_key=api_key,
        base_url=base_url,
        max_tokens=config.LLM_MAX_TOKENS,
        extra_body={"usage": {"include": True}},
    )


def chat_json(prompt: str, system_prompt: str, model: str = config.SPECIALIST_MODEL) -> dict[str, Any]:
    """Execute a completion expecting structured JSON output."""
    try:
        llm = get_llm(model=model, temperature=0.0)
        messages = [
            SystemMessage(content=system_prompt + "\nOutput MUST be valid JSON and nothing else."),
            HumanMessage(content=prompt)
        ]
        response = llm.invoke(messages)
        content = str(response.content)
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()
        return json.loads(content)
    except Exception as e:
        return {"error": f"Failed to complete chat_json: {e}"}
