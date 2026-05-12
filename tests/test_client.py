import asyncio
from types import SimpleNamespace

from tokentracker.client import _AsyncTrackedEmbeddings, _TrackedEmbeddings


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
