"""BAAI/bge-m3 (MIT) lexical weights through FlagEmbedding (MIT).

Install with ``pip install "hanchi[neural]"``. The model (~2 GB in fp32, ~1.1 GB fp16)
is downloaded by FlagEmbedding on first use.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

INSTALL_HINT = 'the bge-m3 backend needs the neural extra: pip install "hanchi[neural]"'


def _load_model(name: str, use_fp16: bool) -> Any:
    try:
        from FlagEmbedding import BGEM3FlagModel  # type: ignore[import-not-found]
    except ImportError as e:
        raise ImportError(INSTALL_HINT) from e
    return BGEM3FlagModel(name, use_fp16=use_fp16)


class BgeM3Encoder:
    def __init__(
        self, model: str = "BAAI/bge-m3", use_fp16: bool = True, _model: Any = None
    ) -> None:
        self.model = _model if _model is not None else _load_model(model, use_fp16)

    def token_weights(self, text: str) -> list[tuple[int, int, float]]:
        out = self.model.encode([text], return_dense=False, return_sparse=True)
        lexical: dict[str, float] = out["lexical_weights"][0]
        enc = self.model.tokenizer(text, return_offsets_mapping=True, add_special_tokens=False)
        weights = []
        for tid, (a, b) in zip(enc["input_ids"], enc["offset_mapping"], strict=True):
            w = float(lexical.get(str(tid), 0.0))
            if b > a:
                weights.append((int(a), int(b), w))
        return weights

    def dense(self, texts: Sequence[str]) -> list[list[float]]:
        out = self.model.encode(list(texts), return_dense=True, return_sparse=False)
        return [list(map(float, v)) for v in out["dense_vecs"]]
