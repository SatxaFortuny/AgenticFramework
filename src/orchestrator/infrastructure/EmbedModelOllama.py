import logging
import time

import ollama

from core.IEmbeddingModel import IEmbeddingModel
from core.logging_utils import elapsed_ms

logger = logging.getLogger(__name__)


class EmbedModelOllama(IEmbeddingModel):
    
    def __init__(self, model_name: str):
        self.model = model_name
    
    def embed(self, content: list[str]) -> list[list[float]]:
        start = time.perf_counter()
        try:
            embeddings = ollama.embed(model=self.model, input=content)["embeddings"]
        except Exception as exc:
            logger.error(
                "Embedding failed after %.0f ms (model=%s, texts=%d): %s",
                elapsed_ms(start),
                self.model,
                len(content),
                exc,
            )
            raise
        logger.info(
            "Embedded %d text(s) with '%s' in %.0f ms",
            len(content),
            self.model,
            elapsed_ms(start),
        )
        return embeddings
