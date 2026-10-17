"""The chat model: Gemma on OpenRouter, with a fallback model. Owner: D."""

import os

from langchain_core.language_models import BaseChatModel
from langchain_core.outputs import ChatResult
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI

from copilot.config import get_settings

OPENROUTER_URL = "https://openrouter.ai/api/v1"
TIMEOUT_S = 90
MAX_RETRIES = 3            # the OpenAI client retries 429 and 5xx with exponential backoff

# REASONING=1 asks OpenRouter for the model's reasoning ({"reasoning": {"enabled": true}}). Gemma
# returns none without it. Off by default: it adds output tokens and may change the answers.
REASONING = os.getenv("REASONING", "") == "1"


class OpenRouterChat(ChatOpenAI):
    """ChatOpenAI that keeps OpenRouter's `message.reasoning` in `additional_kwargs["reasoning"]`
    (ChatOpenAI drops it)."""

    def _create_chat_result(self, response, generation_info: dict | None = None) -> ChatResult:
        result = super()._create_chat_result(response, generation_info)
        raw = response if isinstance(response, dict) else response.model_dump()
        for gen, choice in zip(result.generations, raw.get("choices") or []):
            reasoning = (choice.get("message") or {}).get("reasoning")
            if reasoning:
                gen.message.additional_kwargs["reasoning"] = reasoning
        return result


def chat_model(model: str, max_retries: int = MAX_RETRIES) -> BaseChatModel:
    """One OpenRouter model, temperature 0."""
    return OpenRouterChat(
        base_url=OPENROUTER_URL,
        api_key=get_settings().openrouter_api_key or "missing",
        model=model,
        temperature=0,
        timeout=TIMEOUT_S,
        max_retries=max_retries,
        extra_body={"reasoning": {"enabled": True}} if REASONING else None,
    )


def get_llm() -> Runnable:
    """MODEL, falling back to FALLBACK_MODEL when MODEL fails (after its retries).

    `bind_tools` on the result binds the tools to both models.
    """
    s = get_settings()
    return chat_model(s.model).with_fallbacks([chat_model(s.fallback_model)])
