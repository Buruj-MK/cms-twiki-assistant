#!/usr/bin/env python3
"""
CMS TWiki Embedding Pipeline - 2x T4 edition
Model:  WhereIsAI/UAE-Large-V1
Store:  ChromaDB (localhost:8000)
Input:  chunks.jsonl

Changes vs the single-GPU version:
  - encode_multi_process spreads the model across cuda:0 and cuda:1
  - ChromaDB uploads overlap with GPU work on a writer thread
  - length-sorted super-batches cut padding waste
  - upsert instead of add, so resuming can't collide on existing ids
  - atomic checkpoint write
"""

# sqlite3 fix for older systems
__import__('pysqlite3')
import sys
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')

import json
import os
import time
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from sentence_transformers import SentenceTransformer
import chromadb

INPUT_FILE      = "/var/tmp/embedder/chunks.jsonl"
MODEL_NAME      = "WhereIsAI/UAE-Large-V1"
CHROMA_HOST     = "localhost"
CHROMA_PORT     = 8000
COLLECTION_NAME = "cms_twiki"
BATCH_SIZE      = 256
CHROMA_BATCH    = 500
CHECKPOINT_FILE = "/var/tmp/embedder/chroma_checkpoint.json"

# --- new ---
DEVICES     = ["cuda:0", "cuda:1"]  # both T4s
SUPER_BATCH = 5_000                 # chunks per checkpoint / progress line
CHUNK_SIZE  = 250                   # work unit per worker; drives the bar
USE_FP16    = False                 # see note before enabling mid-corpus


def load_chunks(path):
    chunks = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                chunks.append(json.loads(line))
    return chunks


def get_checkpoint():
    if os.path.exists(CHECKPOINT_FILE):
        with open(CHECKPOINT_FILE, "r") as f:
            return json.load(f)
    return None


def save_checkpoint(processed, elapsed):
    tmp = CHECKPOINT_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump({"processed": processed, "elapsed": elapsed}, f)
    os.replace(tmp, CHECKPOINT_FILE)  # atomic; survives a kill mid-write


def build_metadata(c):
    return {
        "source_file":     c.get("source_file", ""),
        "page_title":      c.get("page_title", ""),
        "section_heading": c.get("section_heading", ""),
        "chunk_index":     c.get("chunk_index", 0),
        "total_chunks":    c.get("total_chunks", 0),
        "author":          c.get("author", ""),
        "date":            c.get("date", ""),
        "content_type":    c.get("content_type", ""),
        "char_count":      c.get("char_count", 0),
        "estimated_tokens": c.get("estimated_tokens", 0),
    }


def flush_to_chroma(collection, ids, embeddings, documents, metadatas):
    """Runs on a background thread so the GPUs keep working during upload."""
    for i in range(0, len(ids), CHROMA_BATCH):
        j = i + CHROMA_BATCH
        collection.upsert(
            ids=ids[i:j],
            embeddings=embeddings[i:j],
            documents=documents[i:j],
            metadatas=metadatas[i:j],
        )
    return len(ids)


def main():
    print(f"Loading chunks from {INPUT_FILE}...")
    chunks = load_chunks(INPUT_FILE)
    total = len(chunks)
    print(f"  Total chunks: {total:,}")

    checkpoint = get_checkpoint()
    start_idx = 0
    elapsed_prev = 0.0

    if checkpoint:
        start_idx = checkpoint["processed"]
        elapsed_prev = checkpoint["elapsed"]
        print(f"  Resuming from chunk {start_idx:,}")

    if start_idx >= total:
        print("  All chunks already embedded!")
        return

    print(f"Loading {MODEL_NAME}...")
    if USE_FP16:
        model = SentenceTransformer(
            MODEL_NAME, model_kwargs={"torch_dtype": "float16"}
        )
    else:
        model = SentenceTransformer(MODEL_NAME)
    dim = model.get_sentence_embedding_dimension()
    print(f"  Model loaded. Embedding dim: {dim}")

    print(f"Connecting to ChromaDB at {CHROMA_HOST}:{CHROMA_PORT}...")
    client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine"}
    )
    existing_count = collection.count()
    print(f"  Collection '{COLLECTION_NAME}': {existing_count:,} existing vectors")

    print(f"Starting workers on {DEVICES}...")
    pool = model.start_multi_process_pool(target_devices=DEVICES)

    remaining = total - start_idx
    print(f"Embedding {remaining:,} chunks (batch_size={BATCH_SIZE} per GPU)...")
    t0 = time.time()

    pending = None
    writer = ThreadPoolExecutor(max_workers=1)

    try:
        for base in range(start_idx, total, SUPER_BATCH):
            end = min(base + SUPER_BATCH, total)
            batch = chunks[base:end]
            print(f"  -> encoding {base:,}..{end:,}", flush=True)

            # Sort long->short so each worker's padding is tight, then restore
            # the original order before writing (ids must match content).
            order = sorted(range(len(batch)),
                           key=lambda k: -len(batch[k]["content"]))
            texts = [batch[k]["content"] for k in order]

            vecs_sorted = model.encode_multi_process(
                texts,
                pool,
                batch_size=BATCH_SIZE,
                chunk_size=CHUNK_SIZE,
                show_progress_bar=True,
                normalize_embeddings=True,
            )

            vecs = [None] * len(batch)
            for pos, k in enumerate(order):
                vecs[k] = vecs_sorted[pos]

            ids        = [f"chunk_{base + j}" for j in range(len(batch))]
            embeddings = [v.tolist() for v in vecs]
            documents  = [c["content"] for c in batch]
            metadatas  = [build_metadata(c) for c in batch]

            # Wait for the previous upload before queuing the next, so the
            # checkpoint only advances past data actually in ChromaDB.
            if pending is not None:
                pending.result()
                save_checkpoint(base, elapsed_prev + (time.time() - t0))

            pending = writer.submit(
                flush_to_chroma, collection, ids, embeddings,
                documents, metadatas
            )

            done = end - start_idx
            elapsed = time.time() - t0
            speed = done / elapsed if elapsed > 0 else 0
            eta = (remaining - done) / speed if speed > 0 else 0
            print(f"  [{end:>7,} / {total:,}]  "
                  f"{done/remaining*100:5.1f}%  "
                  f"{speed:.0f} chunks/s  "
                  f"ETA {eta/60:.1f} min")

        if pending is not None:
            pending.result()
            save_checkpoint(total, elapsed_prev + (time.time() - t0))

    finally:
        writer.shutdown(wait=True)
        model.stop_multi_process_pool(pool)

    elapsed_total = elapsed_prev + (time.time() - t0)

    final_count = collection.count()
    print(f"\n{'='*50}")
    print(f"  Model:            {MODEL_NAME}")
    print(f"  Embedding dim:    {dim}")
    print(f"  Chunks embedded:  {final_count:,}")
    print(f"  Collection:       {COLLECTION_NAME}")
    print(f"  Time:             {elapsed_total/60:.1f} minutes")
    print(f"  ChromaDB:         {CHROMA_HOST}:{CHROMA_PORT}")
    print(f"{'='*50}")
    print("Done! Ready for semantic search.")

    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)


if __name__ == "__main__":
    # Load-bearing: CUDA contexts do not survive fork(), which is what
    # produces "CUDA error: initialization error" / device-side asserts
    # when sentence-transformers multiprocessing is used naively.
    mp.set_start_method("spawn", force=True)
    main()
