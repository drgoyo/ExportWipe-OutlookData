"""Deterministic test ports; real production adapters are tested separately."""

from collections.abc import Sequence


class TestEmbedder:
    __test__ = False

    def embed(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]:
        return [
            [
                float(len(text) + 1),
                float(text.lower().count("contract") + 1),
                float(text.lower().count("renewal") + 1),
                1.0,
            ]
            for text in texts
        ]


class RecordingLLM:
    def __init__(self) -> None:
        self.contexts: list[str] = []

    def complete(self, system: str, context: str, question: str) -> str:
        self.contexts.append(context)
        return "Answer based on the supplied evidence."
