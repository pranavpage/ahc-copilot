"""The chat model: Gemma on OpenRouter, with a fallback model. Owner: D."""

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from langchain_openai import ChatOpenAI

from copilot.config import get_settings

OPENROUTER_URL = "https://openrouter.ai/api/v1"
TIMEOUT_S = 90
MAX_RETRIES = 3            # the OpenAI client retries 429 and 5xx with exponential backoff


def chat_model(model: str, max_retries: int = MAX_RETRIES) -> BaseChatModel:
    """One OpenRouter model, temperature 0."""
    return ChatOpenAI(
        base_url=OPENROUTER_URL,
        api_key=get_settings().openrouter_api_key or "missing",
        model=model,
        temperature=0,
        timeout=TIMEOUT_S,
        max_retries=max_retries,
    )


def get_llm() -> Runnable:
    """MODEL, falling back to FALLBACK_MODEL when MODEL fails (after its retries).

    `bind_tools` on the result binds the tools to both models.
    """
    s = get_settings()
    return chat_model(s.model).with_fallbacks([chat_model(s.fallback_model)])
