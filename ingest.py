"""
One-time (or repeatable) ingestion script: reads the sample Fetchly docs
corpus in docs.py, chunks + embeds each document, and writes it into the
vector store defined by --config's chunker/embedder/vectordb settings.

Run this once before querying any config that relies on
search_fetchly_docs, and re-run it whenever you change the chunker or
embedder for that config -- different chunk sizes or a different
embedding model mean the old vectors/chunk boundaries no longer match,
so they need to be regenerated, not just appended to.

    python ingest.py --config configs/groq_router_gemini_worker.yaml
"""
import argparse

import yaml

from core.factory import PipelineConfig, Rag
from docs import DOCUMENTS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True, help="Path to a YAML pipeline config")
    args = parser.parse_args()

    with open(args.config) as f:
        config_dict = yaml.safe_load(f)

    # Full PipelineConfig validation -- not just the RAG fields -- so a
    # typo anywhere in the file fails loudly here rather than at query time.
    config = PipelineConfig.model_validate(config_dict)

    chunker = config.chunker.build()
    embedder = config.embedder.build()
    vector_store = config.vectordb.build()
    rag = Rag(chunker=chunker, embedder=embedder, vector_store=vector_store)

    for doc in DOCUMENTS:
        rag.ingest(
            text=doc["text"].strip(),
            metadata={"id": doc["id"], "title": doc["title"]},
        )
        print(f"ingested: {doc['id']} ({doc['title']})")

    print(
        f"\nDone. Ingested {len(DOCUMENTS)} documents into "
        f"collection '{config.vectordb.collection_name}' "
        f"at '{config.vectordb.persist_directory}'."
    )


if __name__ == "__main__":
    main()
