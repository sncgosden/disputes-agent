"""Unified streaming interface to the local Qwen models (via LM Studio) and Claude."""

import os
import time
from pathlib import Path

import anthropic
import openai
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

MODEL_ENV_VARS = {
    "qwen-small": "QWEN_SMALL",
    "qwen-large": "QWEN_LARGE",
    "claude": "CLAUDE_MODEL",
}

REQUEST_TIMEOUT_SECONDS = 120


class LLMError(RuntimeError):
    """Raised when a model is misconfigured, unreachable, or returns an error."""


def _require_env(name):
    value = os.getenv(name)
    if not value:
        raise LLMError(f"{name} is not set. Add it to .env in the project root.")
    return value


_clients = {}


def _openai_client():
    if "openai" not in _clients:
        _clients["openai"] = openai.OpenAI(
            base_url=_require_env("LMSTUDIO_BASE_URL"),
            api_key="lm-studio",
            timeout=REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        )
    return _clients["openai"]


def _anthropic_client():
    if "anthropic" not in _clients:
        _clients["anthropic"] = anthropic.Anthropic(
            api_key=_require_env("ANTHROPIC_API_KEY"),
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    return _clients["anthropic"]


# LM Studio's OpenAI endpoint ignores enable_thinking / reasoning_effort for
# Qwen, so thinking is skipped by prefilling an empty think block instead.
QWEN_NO_THINK_PREFILL = "<think>\n\n</think>\n\n"


def _stream_qwen(model_id, prompt, system, max_tokens, thinking, temperature=None):
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    if not thinking:
        messages.append({"role": "assistant", "content": QWEN_NO_THINK_PREFILL})

    start = time.perf_counter()
    first_token_at = None
    text_parts = []
    reasoning_parts = []
    output_tokens = None
    input_tokens = None

    try:
        stream = _openai_client().chat.completions.create(
            model=model_id,
            messages=messages,
            max_tokens=max_tokens,
            **({"temperature": temperature} if temperature is not None else {}),
            stream=True,
            stream_options={"include_usage": True},
        )
        for chunk in stream:
            if chunk.usage is not None:
                output_tokens = chunk.usage.completion_tokens
                input_tokens = chunk.usage.prompt_tokens
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            # Qwen thinking arrives as reasoning_content; it counts toward TTFT
            # and output_tokens but is returned separately from the text.
            reasoning = (delta.model_extra or {}).get("reasoning_content")
            if (delta.content or reasoning) and first_token_at is None:
                first_token_at = time.perf_counter()
            if reasoning:
                reasoning_parts.append(reasoning)
            if delta.content:
                text_parts.append(delta.content)
    except openai.APIConnectionError as e:
        raise LLMError(
            f"Could not reach LM Studio at {os.getenv('LMSTUDIO_BASE_URL')} for "
            f"model '{model_id}'. Is the LM Studio server running? ({e})"
        ) from e
    except openai.APIStatusError as e:
        raise LLMError(
            f"LM Studio returned HTTP {e.status_code} for model '{model_id}'. "
            f"Is the model loaded? ({e.message})"
        ) from e

    return "".join(text_parts), "".join(reasoning_parts), start, first_token_at, output_tokens, input_tokens


def _stream_claude(model_id, prompt, system, max_tokens, thinking, temperature=None):
    kwargs = {
        "model": model_id,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    # temperature is deliberately not sent: the Anthropic SDK in use
    # (anthropic==1.11.0) doesn't accept it for this model, so Claude always
    # runs at its default. The temperature argument is ignored for Claude.
    if thinking:
        # display defaults to omitted (empty thinking text); summarized returns
        # Claude's summary of its thinking so it isn't lost.
        kwargs["thinking"] = {"type": "adaptive", "display": "summarized"}

    start = time.perf_counter()
    first_token_at = None
    text_parts = []
    reasoning_parts = []

    try:
        with _anthropic_client().messages.stream(**kwargs) as stream:
            for event in stream:
                if event.type != "content_block_delta":
                    continue
                if event.delta.type == "text_delta":
                    piece, parts = event.delta.text, text_parts
                elif event.delta.type == "thinking_delta":
                    piece, parts = event.delta.thinking, reasoning_parts
                else:
                    continue
                if piece:
                    if first_token_at is None:
                        first_token_at = time.perf_counter()
                    parts.append(piece)
            final = stream.get_final_message()
    except anthropic.APIConnectionError as e:
        raise LLMError(f"Could not reach the Anthropic API for model '{model_id}'. ({e})") from e
    except anthropic.AuthenticationError as e:
        raise LLMError("Anthropic API rejected the API key. Check ANTHROPIC_API_KEY in .env.") from e
    except anthropic.APIStatusError as e:
        raise LLMError(
            f"Anthropic API returned HTTP {e.status_code} for model '{model_id}'. ({e.message})"
        ) from e

    output_tokens = final.usage.output_tokens if final.usage else None
    input_tokens = final.usage.input_tokens if final.usage else None
    return "".join(text_parts), "".join(reasoning_parts), start, first_token_at, output_tokens, input_tokens


def call(model_name, prompt, system=None, max_tokens=1000, thinking=False, temperature=None):
    """Send a prompt to a model and return its reply with timing metrics.

    model_name is one of "qwen-small", "qwen-large" or "claude". thinking
    turns on the model's reasoning step (off by default). temperature sets
    how random the output is (0 = most predictable); None uses the
    provider's default.

    Returns a dict with text, reasoning, model_id, ttft_seconds,
    total_seconds, input_tokens, output_tokens and tokens_per_second.
    input_tokens (prompt size) is needed to calculate API cost. reasoning holds any
    thinking the model streamed (for Claude, a summary of it), or "" if none.
    ttft_seconds measures the first token of either kind. tokens_per_second
    is the generation rate after the first token (output_tokens /
    (total - ttft)); it is None if the token count is unknown.
    """
    if model_name not in MODEL_ENV_VARS:
        raise ValueError(
            f"Unknown model_name '{model_name}'. Expected one of: {', '.join(MODEL_ENV_VARS)}"
        )
    model_id = _require_env(MODEL_ENV_VARS[model_name])

    stream_fn = _stream_claude if model_name == "claude" else _stream_qwen
    text, reasoning, start, first_token_at, output_tokens, input_tokens = stream_fn(
        model_id, prompt, system, max_tokens, thinking, temperature
    )
    end = time.perf_counter()

    ttft = (first_token_at - start) if first_token_at is not None else None
    total = end - start

    tokens_per_second = None
    if output_tokens is not None:
        generation_time = total - ttft if ttft is not None else total
        if generation_time > 0:
            tokens_per_second = output_tokens / generation_time

    return {
        "text": text,
        "reasoning": reasoning,
        "model_id": model_id,
        "ttft_seconds": ttft,
        "total_seconds": total,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "tokens_per_second": tokens_per_second,
    }
