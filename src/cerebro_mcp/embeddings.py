"""Local CPU embeddings through ONNX Runtime (fastembed). Nothing leaves the machine
except the one-time model download.

The model is `multilingual-e5-small` (384 dims, ~100 languages). e5 needs
prefixes: "passage: " for what is indexed and "query: " for the question;
leaving them out silently degrades search.

Two builds are available:

- `e5-small-int8` (default): the int8-quantized ONNX export
  (`Xenova/multilingual-e5-small`, `onnx/model_quantized.onnx`, ~118 MB).
- `e5-small`: the full-precision ONNX export published with the original model
  (`intfloat/multilingual-e5-small`, `onnx/model.onnx`, ~470 MB); its vectors
  match the sentence-transformers ones to 4 decimals.

The model cache is fastembed's (honors `FASTEMBED_CACHE_PATH`); set
`CEREBRO_MODEL_CACHE` to put it somewhere else.
"""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

log = logging.getLogger("cerebro")

DIMS = 384


@dataclass(frozen=True)
class ModelSpec:
    key: str
    repo: str
    file: str
    size_mb: int


MODELS = {
    "e5-small-int8": ModelSpec("e5-small-int8", "Xenova/multilingual-e5-small", "onnx/model_quantized.onnx", 118),
    "e5-small": ModelSpec("e5-small", "intfloat/multilingual-e5-small", "onnx/model.onnx", 470),
}
DEFAULT_MODEL = "e5-small-int8"


class ModelUnavailable(RuntimeError):
    """The model is not cached and could not be downloaded (or fastembed is missing)."""


class Embedder(Protocol):
    name: str
    dims: int

    def passages(self, texts: list[str]) -> np.ndarray: ...

    def query(self, text: str) -> np.ndarray: ...


def spec(key: str | None) -> ModelSpec:
    key = key or os.environ.get("CEREBRO_MODEL") or DEFAULT_MODEL
    if key not in MODELS:
        raise ValueError(f"unknown model {key!r} (known: {', '.join(MODELS)})")
    return MODELS[key]


def cache_dir() -> Path:
    """Where the model files live (same rule fastembed uses)."""
    own = os.environ.get("CEREBRO_MODEL_CACHE")
    if own:
        return Path(own).expanduser()
    return Path(os.environ.get("FASTEMBED_CACHE_PATH", os.path.join(tempfile.gettempdir(), "fastembed_cache")))


def is_cached(key: str | None = None) -> bool:
    s = spec(key)
    folder = cache_dir() / f"models--{s.repo.replace('/', '--')}" / "snapshots"
    return folder.is_dir() and any((snap / s.file).is_file() for snap in folder.iterdir())


_registered: set[str] = set()
_register_lock = threading.Lock()


def _register(s: ModelSpec) -> str:
    from fastembed import TextEmbedding
    from fastembed.common.model_description import ModelSource, PoolingType

    name = f"cerebro/{s.key}"
    with _register_lock:
        if name not in _registered:
            known = {m["model"] for m in TextEmbedding.list_supported_models()}
            if name not in known:
                TextEmbedding.add_custom_model(
                    model=name,
                    pooling=PoolingType.MEAN,
                    normalization=True,
                    sources=ModelSource(hf=s.repo),
                    dim=DIMS,
                    model_file=s.file,
                )
            _registered.add(name)
    return name


class E5Embedder:
    """multilingual-e5-small on ONNX Runtime, loaded lazily on first use."""

    dims = DIMS

    def __init__(self, model: str | None = None, threads: int | None = None, offline: bool = False):
        self.spec = spec(model)
        self.name = f"multilingual-e5-small:{self.spec.key}"
        self._threads = threads or int(os.environ.get("CEREBRO_THREADS", "0")) or min(4, os.cpu_count() or 1)
        self._offline = offline
        self._model = None
        self._lock = threading.Lock()

    def _load(self):
        with self._lock:
            if self._model is None:
                # Before huggingface_hub is imported: it reads these once.
                os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
                os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
                os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "1")
                try:
                    from fastembed import TextEmbedding
                except ImportError as e:  # pragma: no cover - fastembed is a dependency
                    raise ModelUnavailable("fastembed is not installed") from e
                name = _register(self.spec)
                kwargs = {"threads": self._threads}
                if os.environ.get("CEREBRO_MODEL_CACHE"):
                    kwargs["cache_dir"] = str(cache_dir())
                if self._offline:
                    kwargs["local_files_only"] = True
                try:
                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        self._model = TextEmbedding(name, **kwargs)
                except Exception as e:
                    raise ModelUnavailable(
                        f"could not load {self.spec.repo} ({type(e).__name__}: {e}). "
                        "Connect once to download it, or use --text for keyword-only search."
                    ) from e
        return self._model

    def load(self) -> None:
        self._load()

    def _encode(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, DIMS), dtype=np.float32)
        vectors = list(self._load().embed(texts, batch_size=16))
        return np.asarray(vectors, dtype=np.float32)

    def passages(self, texts: list[str]) -> np.ndarray:
        return self._encode([f"passage: {t}" for t in texts])

    def query(self, text: str) -> np.ndarray:
        return self._encode([f"query: {text}"])[0]
