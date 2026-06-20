"""Drop-in replacement for openai.OpenAI that logs every call."""

from __future__ import annotations

import time
from typing import Any

import openai

from tokentracker.db import log_call
from tokentracker.pricing import estimate_cost


def _counts_from_usage(usage: Any) -> tuple[int, int, int]:
    inp = getattr(usage, "prompt_tokens", 0) or 0
    out = getattr(usage, "completion_tokens", 0) or 0
    total = getattr(usage, "total_tokens", 0) or (inp + out)
    return inp, out, total


def _usage_counts(response: Any) -> tuple[int, int, int]:
    return _counts_from_usage(getattr(response, "usage", None))


class _StreamLogger:
    """Capture usage from a streaming response and log once it's consumed.

    A ``stream=True`` call returns an iterator of chunks, not a response with
    ``.usage`` — so the old path logged zero tokens for every streamed call.
    OpenAI puts the usage in the final chunk when the caller sets
    ``stream_options={"include_usage": True}``; this passes chunks through
    untouched, remembers the latest ``usage``/``model`` it sees, and logs the
    call when the stream finishes or is closed (early ``break`` included).
    """

    def __init__(self, model: str, t0: float, endpoint: str | None = None):
        self._model = model
        self._t0 = t0
        self._endpoint = endpoint
        self._usage: Any = None
        self._logged = False

    def observe(self, chunk: Any) -> None:
        usage = getattr(chunk, "usage", None)
        if usage is not None:
            self._usage = usage
        model = getattr(chunk, "model", None)
        if model:
            self._model = model

    def finish(self, error: str | None = None) -> None:
        if self._logged:
            return
        self._logged = True
        elapsed = (time.perf_counter() - self._t0) * 1000
        inp, out, total = _counts_from_usage(self._usage)
        # A stream that broke mid-flight is an error, not a successful call —
        # otherwise it would be counted as spend like the non-streaming path
        # already avoids. Don't price a failed call.
        cost = None if error else estimate_cost(self._model, inp, out)
        extra = {"endpoint": self._endpoint} if self._endpoint else {}
        log_call(
            model=self._model,
            input_tokens=inp,
            output_tokens=out,
            total_tokens=total,
            cost_usd=cost,
            latency_ms=elapsed,
            status="error" if error else "ok",
            error=error[:500] if error else None,
            **extra,
        )


def _wrap_stream(stream: Any, logger: _StreamLogger) -> Any:
    """Yield a sync stream's chunks, logging usage when it's exhausted."""
    error: str | None = None
    try:
        for chunk in stream:
            logger.observe(chunk)
            yield chunk
    except Exception as e:
        error = str(e)
        raise
    finally:
        # A consumer's early break raises GeneratorExit (not Exception), so it
        # still logs as a normal call; only a real stream failure marks an error.
        logger.finish(error=error)


async def _wrap_async_stream(stream: Any, logger: _StreamLogger) -> Any:
    """Yield an async stream's chunks, logging usage when it's exhausted."""
    error: str | None = None
    try:
        async for chunk in stream:
            logger.observe(chunk)
            yield chunk
    except Exception as e:
        error = str(e)
        raise
    finally:
        logger.finish(error=error)


class _TrackedCompletions:
    """Wraps chat.completions to intercept create() calls."""

    def __init__(self, original_completions):
        self._original = original_completions

    def create(self, **kwargs) -> Any:
        model = kwargs.get("model", "unknown")
        t0 = time.perf_counter()
        try:
            response = self._original.create(**kwargs)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log_call(
                model=model,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                cost_usd=None,
                latency_ms=elapsed,
                status="error",
                error=str(e)[:500],
            )
            raise

        if kwargs.get("stream"):
            return _wrap_stream(response, _StreamLogger(model, t0))

        elapsed = (time.perf_counter() - t0) * 1000
        inp, out, total = _usage_counts(response)
        resp_model = getattr(response, "model", model) or model
        cost = estimate_cost(resp_model, inp, out)

        log_call(
            model=resp_model,
            input_tokens=inp,
            output_tokens=out,
            total_tokens=total,
            cost_usd=cost,
            latency_ms=elapsed,
        )
        return response

    def __getattr__(self, name):
        return getattr(self._original, name)


class _TrackedEmbeddings:
    """Wraps embeddings.create() calls."""

    def __init__(self, original_embeddings):
        self._original = original_embeddings

    def create(self, **kwargs) -> Any:
        model = kwargs.get("model", "unknown")
        t0 = time.perf_counter()
        try:
            response = self._original.create(**kwargs)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log_call(
                model=model,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                cost_usd=None,
                latency_ms=elapsed,
                endpoint="embeddings",
                status="error",
                error=str(e)[:500],
            )
            raise

        elapsed = (time.perf_counter() - t0) * 1000
        inp, _out, total = _usage_counts(response)
        resp_model = getattr(response, "model", model) or model
        cost = estimate_cost(resp_model, inp, 0)

        log_call(
            model=resp_model,
            input_tokens=inp,
            output_tokens=0,
            total_tokens=total,
            cost_usd=cost,
            latency_ms=elapsed,
            endpoint="embeddings",
        )
        return response

    def __getattr__(self, name):
        return getattr(self._original, name)


class _TrackedChat:
    """Wraps client.chat to intercept chat.completions."""

    def __init__(self, original_chat):
        self._original = original_chat
        self.completions = _TrackedCompletions(original_chat.completions)

    def __getattr__(self, name):
        return getattr(self._original, name)


class OpenAI(openai.OpenAI):
    """Drop-in replacement for openai.OpenAI that tracks token usage and cost.

    Usage:
        # Change this:
        from openai import OpenAI
        # To this:
        from tokentracker import OpenAI

        # Everything else stays the same.
        client = OpenAI()
        response = client.chat.completions.create(model="gpt-4o", messages=[...])

        # That's it. All calls are logged to ~/.tokentracker/usage.db
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.chat = _TrackedChat(super().chat)
        self.embeddings = _TrackedEmbeddings(super().embeddings)


class _AsyncTrackedCompletions:
    """Wraps async chat.completions to intercept create() calls."""

    def __init__(self, original_completions):
        self._original = original_completions

    async def create(self, **kwargs) -> Any:
        model = kwargs.get("model", "unknown")
        t0 = time.perf_counter()
        try:
            response = await self._original.create(**kwargs)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log_call(
                model=model,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                cost_usd=None,
                latency_ms=elapsed,
                status="error",
                error=str(e)[:500],
            )
            raise

        if kwargs.get("stream"):
            return _wrap_async_stream(response, _StreamLogger(model, t0))

        elapsed = (time.perf_counter() - t0) * 1000
        inp, out, total = _usage_counts(response)
        resp_model = getattr(response, "model", model) or model
        cost = estimate_cost(resp_model, inp, out)

        log_call(
            model=resp_model,
            input_tokens=inp,
            output_tokens=out,
            total_tokens=total,
            cost_usd=cost,
            latency_ms=elapsed,
        )
        return response

    def __getattr__(self, name):
        return getattr(self._original, name)


class _AsyncTrackedEmbeddings:
    def __init__(self, original_embeddings):
        self._original = original_embeddings

    async def create(self, **kwargs) -> Any:
        model = kwargs.get("model", "unknown")
        t0 = time.perf_counter()
        try:
            response = await self._original.create(**kwargs)
        except Exception as e:
            elapsed = (time.perf_counter() - t0) * 1000
            log_call(
                model=model,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                cost_usd=None,
                latency_ms=elapsed,
                endpoint="embeddings",
                status="error",
                error=str(e)[:500],
            )
            raise

        elapsed = (time.perf_counter() - t0) * 1000
        inp, _out, total = _usage_counts(response)
        resp_model = getattr(response, "model", model) or model
        cost = estimate_cost(resp_model, inp, 0)

        log_call(
            model=resp_model,
            input_tokens=inp,
            output_tokens=0,
            total_tokens=total,
            cost_usd=cost,
            latency_ms=elapsed,
            endpoint="embeddings",
        )
        return response

    def __getattr__(self, name):
        return getattr(self._original, name)


class _AsyncTrackedChat:
    def __init__(self, original_chat):
        self._original = original_chat
        self.completions = _AsyncTrackedCompletions(original_chat.completions)

    def __getattr__(self, name):
        return getattr(self._original, name)


class AsyncOpenAI(openai.AsyncOpenAI):
    """Async version. Same drop-in replacement, same tracking."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.chat = _AsyncTrackedChat(super().chat)
        self.embeddings = _AsyncTrackedEmbeddings(super().embeddings)
