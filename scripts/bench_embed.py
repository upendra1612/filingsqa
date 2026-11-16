"""Measure embedding speed on this machine under a few settings.

Usage: python scripts/bench_embed.py   (writes data/bench_embed.log)
"""

import json
import os
import platform
import time

N = 48


def main():
    import onnxruntime as ort
    from fastembed import TextEmbedding

    with open("data/index/baseline/chunks.jsonl", encoding="utf-8") as fh:
        chunks = [json.loads(next(fh))["text"] for _ in range(N)]
    short = [" ".join(c.split()[:200]) for c in chunks]
    lines = [
        f"python {platform.python_version()} on {platform.platform()}",
        f"cpu_count={os.cpu_count()} onnxruntime={ort.__version__}",
        f"providers={ort.get_available_providers()}",
    ]
    t = time.time()
    model = TextEmbedding("BAAI/bge-small-en-v1.5")
    lines.append(f"model load: {time.time() - t:.1f}s")
    list(model.embed(chunks[:4]))  # warm-up
    for label, texts, kw in [
        ("400 words, batch 64 (current setting)", chunks, {"batch_size": 64}),
        ("400 words, batch 8", chunks, {"batch_size": 8}),
        ("200 words, batch 64", short, {"batch_size": 64}),
        ("400 words, batch 16, all cores in parallel", chunks, {"batch_size": 16, "parallel": 0}),
    ]:
        t = time.time()
        list(model.embed(texts, **kw))
        dt = time.time() - t
        lines.append(f"{label:45} {len(texts) / dt:7.1f} chunks/s")
        print(lines[-1], flush=True)
    for name in ("BAAI/bge-small-en-v1.5",):
        t = time.time()
        m2 = TextEmbedding(name, threads=os.cpu_count())
        list(m2.embed(chunks[:4]))
        t = time.time()
        list(m2.embed(chunks, batch_size=64))
        lines.append(
            f"{'400 words, batch 64, threads=cpu_count':45} {N / (time.time() - t):7.1f} chunks/s"
        )
    open("data/bench_embed.log", "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
