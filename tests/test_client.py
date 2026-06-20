import asyncio
from types import SimpleNamespace

import pytest

from tokentracker.client import (
    _AsyncTrackedCompletions,
    _AsyncTrackedEmbeddings,
    _TrackedCompletions,
    _TrackedEmbeddings,
)


def _chunk(content=None, usage=None, model="gpt-4o"):
    choices = []
    if content is not None:
        choices = [SimpleNamespace(delta=SimpleNamespace(content=content))]
    return SimpleNamespace(model=model, usage=usage, choices=choices)


_USAGE = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)


class _StreamCompletions:
    """A sync completions resource whose create() returns a chunk stream."""

    def create(self, **kwargs):
        return iter([_chunk("Hello"), _chunk(" world"), _chunk(usage=_USAGE)])


class _NoUsageStreamCompletions:
    def create(self, **kwargs):
        return iter([_chunk("a"), _chunk("b")])


class _RaisingStreamCompletions:
    """A stream that fails partway through, like a dropped connection."""

    def create(self, **kwargs):
        def gen():
            yield _chunk("partial")
            raise RuntimeError("stream broke")

        return gen()


class _AsyncStreamCompletions:
    async def create(self, **kwargs):
        async def gen():
            yield _chunk("Hi")
            yield _chunk(usage=_USAGE)

        return gen()


class _EmbeddingsResource:
    def create(self, **kwargs):
        return SimpleNamespace(
            model=kwargs["model"],
            usage=SimpleNamespace(prompt_tokens=12, total_tokens=12),
        )


class _AsyncEmbeddingsResource:
    async def create(self, **kwargs):
        return SimpleNamespace(
            model=kwargs["model"],
            usage=SimpleNamespace(prompt_tokens=9, total_tokens=9),
        )


def test_embeddings_create_logs_endpoint(monkeypatch):
    calls = []
    monkeypatch.setattr("tokentracker.client.log_call", lambda **kwargs: calls.append(kwargs))

    response = _TrackedEmbeddings(_EmbeddingsResource()).create(
        model="text-embedding-3-small",
        input="hello",
    )

    assert response.usage.total_tokens == 12
    assert calls[0]["endpoint"] == "embeddings"
    assert calls[0]["model"] == "text-embedding-3-small"
    assert calls[0]["input_tokens"] == 12
    assert calls[0]["output_tokens"] == 0
    assert calls[0]["total_tokens"] == 12


def test_async_embeddings_create_logs_endpoint(monkeypatch):
    calls = []
    monkeypatch.setattr("tokentracker.client.log_call", lambda **kwargs: calls.append(kwargs))

    response = asyncio.run(
        _AsyncTrackedEmbeddings(_AsyncEmbeddingsResource()).create(
            model="text-embedding-3-small",
            input="hello",
        )
    )

    assert response.usage.total_tokens == 9
    assert calls[0]["endpoint"] == "embeddings"
    assert calls[0]["input_tokens"] == 9
    assert calls[0]["output_tokens"] == 0


def test_streaming_logs_usage_from_final_chunk(monkeypatch):
    calls = []
    monkeypatch.setattr("tokentracker.client.log_call", lambda **kw: calls.append(kw))

    stream = _TrackedCompletions(_StreamCompletions()).create(
        model="gpt-4o", stream=True, stream_options={"include_usage": True}
    )
    chunks = list(stream)  # consume the stream

    assert len(chunks) == 3  # chunks pass through unchanged
    assert len(calls) == 1  # logged exactly once, after consumption
    assert calls[0]["input_tokens"] == 10
    assert calls[0]["output_tokens"] == 5
    assert calls[0]["total_tokens"] == 15
    assert calls[0]["model"] == "gpt-4o"


def test_streaming_without_usage_still_logs_call(monkeypatch):
    calls = []
    monkeypatch.setattr("tokentracker.client.log_call", lambda **kw: calls.append(kw))

    stream = _TrackedCompletions(_NoUsageStreamCompletions()).create(model="gpt-4o", stream=True)
    list(stream)

    assert len(calls) == 1
    assert calls[0]["total_tokens"] == 0  # no usage chunk -> zero, but call still logged


def test_streaming_logs_once_on_early_break(monkeypatch):
    calls = []
    monkeypatch.setattr("tokentracker.client.log_call", lambda **kw: calls.append(kw))

    stream = _TrackedCompletions(_StreamCompletions()).create(model="gpt-4o", stream=True)
    for _chunk_ in stream:
        break  # stop early
    stream.close()  # closing the generator triggers the finally -> log once

    assert len(calls) == 1
    assert calls[0]["status"] == "ok"  # an early break is not a failure


def test_streaming_mid_stream_error_is_logged_as_error(monkeypatch):
    calls = []
    monkeypatch.setattr("tokentracker.client.log_call", lambda **kw: calls.append(kw))

    stream = _TrackedCompletions(_RaisingStreamCompletions()).create(model="gpt-4o", stream=True)
    with pytest.raises(RuntimeError, match="stream broke"):
        list(stream)

    assert len(calls) == 1  # the failed stream is still logged, once
    assert calls[0]["status"] == "error"  # ...as an error, not silent spend
    assert "stream broke" in (calls[0]["error"] or "")
    assert calls[0]["cost_usd"] is None


def test_async_streaming_logs_usage(monkeypatch):
    calls = []
    monkeypatch.setattr("tokentracker.client.log_call", lambda **kw: calls.append(kw))

    async def run():
        stream = await _AsyncTrackedCompletions(_AsyncStreamCompletions()).create(
            model="gpt-4o", stream=True, stream_options={"include_usage": True}
        )
        return [c async for c in stream]

    chunks = asyncio.run(run())

    assert len(chunks) == 2
    assert len(calls) == 1
    assert calls[0]["total_tokens"] == 15
