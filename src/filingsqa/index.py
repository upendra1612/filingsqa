"""Build the search index: filings -> text -> chunks -> embeddings -> Qdrant.

Usage:
    filingsqa-index                      # baseline: 400-word chunks, 50-word overlap
    filingsqa-index --name w400 --chunk-words 400 --overlap 50

Writes data/index/<name>/chunks.jsonl and a Qdrant collection stored under
data/qdrant (local mode: no server, no account). Re-running replaces the collection.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path

from .chunking import fixed_word_chunks
from .embeddings import DEFAULT_MODEL, Embedder, FastEmbedder
from .text import html_to_text

QDRANT_PATH = "data/qdrant"


def collection_name(name: str) -> str:
    return f"filingsqa_{name}"


def iter_chunks(manifest: list[dict], words: int, overlap: int):
    """Yield one record per chunk, with the metadata needed to cite it."""
    for filing in manifest:
        docs = filing.get("documents") or [filing["local_path"]]
        types = ["10-K"] + [e["type"] for e in filing.get("exhibits", [])]
        for doc, doc_type in zip(docs, types, strict=False):
            raw = Path(doc).read_text(encoding="utf-8", errors="ignore")
            for i, text in enumerate(fixed_word_chunks(html_to_text(raw), words, overlap)):
                key = f"{filing['accession']}/{Path(doc).name}/{i}"
                yield {
                    "id": str(uuid.uuid5(uuid.NAMESPACE_URL, key)),
                    "text": text,
                    "ticker": filing["ticker"],
                    "company": filing["company"],
                    "period_end": filing["report_date"],
                    "accession": filing["accession"],
                    "document": Path(doc).name,
                    "doc_type": doc_type,
                    "chunk_index": i,
                }


def build_index(
    manifest: list[dict],
    embedder: Embedder,
    client,
    name: str,
    words: int = 400,
    overlap: int = 50,
    out_dir: Path = Path("data/index"),
    batch: int = 256,
) -> dict:
    from qdrant_client import models

    coll = collection_name(name)
    if client.collection_exists(coll):
        client.delete_collection(coll)
    client.create_collection(
        coll, vectors_config=models.VectorParams(size=embedder.dim, distance=models.Distance.COSINE)
    )
    folder = out_dir / name
    folder.mkdir(parents=True, exist_ok=True)
    n, started, pending = 0, time.time(), []

    def flush():
        vectors = embedder.embed_documents([c["text"] for c in pending])
        client.upsert(
            coll,
            points=[
                models.PointStruct(id=c["id"], vector=v, payload=c)
                for c, v in zip(pending, vectors, strict=True)
            ],
        )
        pending.clear()

    with (folder / "chunks.jsonl").open("w", encoding="utf-8") as fh:
        for chunk in iter_chunks(manifest, words, overlap):
            fh.write(json.dumps(chunk) + "\n")
            pending.append(chunk)
            n += 1
            if len(pending) >= batch:
                flush()
                print(f"  {n} chunks embedded", end="\r", flush=True)
        if pending:
            flush()
    info = {
        "name": name,
        "collection": coll,
        "embedding_model": embedder.name,
        "dim": embedder.dim,
        "chunker": "fixed_word_chunks",
        "chunk_words": words,
        "overlap": overlap,
        "chunks": n,
        "filings": len(manifest),
        "seconds": round(time.time() - started, 1),
    }
    (folder / "index_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    return info


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--name", default="baseline", help="index name, used by --index in evals")
    ap.add_argument("--manifest", default="data/manifest.jsonl")
    ap.add_argument("--chunk-words", type=int, default=400)
    ap.add_argument("--overlap", type=int, default=50)
    ap.add_argument("--model", default=DEFAULT_MODEL)
    args = ap.parse_args(argv)

    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        print(f"error: {manifest_path} not found; run filingsqa-download first", file=sys.stderr)
        return 2
    manifest = [json.loads(line) for line in manifest_path.read_text().splitlines() if line]

    from qdrant_client import QdrantClient

    print(f"Loading embedding model {args.model} (downloads once, ~70 MB)...")
    embedder = FastEmbedder(args.model)
    client = QdrantClient(path=QDRANT_PATH)
    info = build_index(manifest, embedder, client, args.name, args.chunk_words, args.overlap)
    print(
        f"\n{info['chunks']} chunks from {info['filings']} filings in {info['seconds']}s "
        f"-> collection {info['collection']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
