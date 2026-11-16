"""Build the search index: filings -> text -> chunks -> embeddings -> Qdrant.

Usage:
    filingsqa-index                      # baseline: 400-word chunks, 50-word overlap
    filingsqa-index --name w400 --chunk-words 400 --overlap 50

Writes data/index/<name>/chunks.jsonl and a Qdrant collection stored under
data/qdrant (local mode: no server, no account). Re-running replaces the collection.
Embeddings are cached per document in data/embed_cache, so an interrupted build
resumes where it stopped.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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


def _cache_path(cache_dir: Path, model: str, texts: list[str]) -> Path:
    """One file per (embedding model, exact list of chunk texts) for a document."""
    digest = hashlib.sha256(("\x00".join([model, *texts])).encode("utf-8")).hexdigest()[:24]
    return cache_dir / re.sub(r"[^A-Za-z0-9._-]", "_", model) / f"{digest}.json"


def build_index(
    manifest: list[dict],
    embedder: Embedder,
    client,
    name: str,
    words: int = 400,
    overlap: int = 50,
    out_dir: Path = Path("data/index"),
    cache_dir: Path = Path("data/embed_cache"),
    batch: int = 64,
    progress=print,
) -> dict:
    """Embed every chunk and load it into a fresh Qdrant collection.

    Embeddings are cached per document, so an interrupted build resumes where it
    stopped, and rebuilding with the same chunks and model costs only the upload.
    """
    from qdrant_client import models

    coll = collection_name(name)
    if client.collection_exists(coll):
        client.delete_collection(coll)
    client.create_collection(
        coll, vectors_config=models.VectorParams(size=embedder.dim, distance=models.Distance.COSINE)
    )
    folder = out_dir / name
    folder.mkdir(parents=True, exist_ok=True)

    # Group chunks by document: the unit of caching and of progress reporting.
    docs: dict[tuple[str, str], list[dict]] = {}
    for chunk in iter_chunks(manifest, words, overlap):
        docs.setdefault((chunk["accession"], chunk["document"]), []).append(chunk)
    total = sum(len(c) for c in docs.values())
    with (folder / "chunks.jsonl").open("w", encoding="utf-8") as fh:
        for chunks in docs.values():
            for c in chunks:
                fh.write(json.dumps(c) + "\n")

    started, done, embedded, embed_seconds, reused = time.time(), 0, 0, 0.0, 0
    for (_, doc_name), chunks in docs.items():
        texts = [c["text"] for c in chunks]
        cache = _cache_path(cache_dir, embedder.name, texts)
        if cache.is_file():
            vectors = json.loads(cache.read_text())
            reused += len(chunks)
        else:
            t = time.time()
            vectors = []
            for i in range(0, len(texts), batch):
                vectors.extend(embedder.embed_documents(texts[i : i + batch]))
            embed_seconds += time.time() - t
            embedded += len(chunks)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps([[round(x, 6) for x in v] for v in vectors]))
        for i in range(0, len(chunks), 256):
            client.upsert(
                coll,
                points=[
                    models.PointStruct(id=c["id"], vector=v, payload=c)
                    for c, v in zip(chunks[i : i + 256], vectors[i : i + 256], strict=True)
                ],
            )
        done += len(chunks)
        rate = embedded / embed_seconds if embed_seconds else 0.0
        eta = (total - done) / rate / 60 if rate else 0.0
        progress(
            f"  {done:,}/{total:,} chunks ({doc_name})"
            + (f"  ~{rate:.0f} chunks/s, ~{eta:.0f} min left" if rate else "  (from cache)")
        )
    info = {
        "name": name,
        "collection": coll,
        "embedding_model": embedder.name,
        "dim": embedder.dim,
        "chunker": "fixed_word_chunks",
        "chunk_words": words,
        "overlap": overlap,
        "chunks": total,
        "documents": len(docs),
        "filings": len(manifest),
        "embedded_now": embedded,
        "reused_from_cache": reused,
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
        f"({info['embedded_now']} embedded now, {info['reused_from_cache']} reused from cache) "
        f"-> collection {info['collection']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
