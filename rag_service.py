#!/usr/bin/env python3
"""
CMS TWiki RAG service.

  GPU 0 : UAE-Large-V1 embedder + bge-reranker-base  (this process)
  GPU 1 : vLLM OpenAI-compatible server on :8001     (serve_llm.sh)

Retrieval pipeline:
  query -> dense (Chroma) + lexical (BM25) -> RRF fusion
        -> cross-encoder rerank -> neighbour expansion -> context

Run:  uvicorn rag_service:app --host 0.0.0.0 --port 8000
      (use a different port if ChromaDB already owns 8000)
"""

__import__('pysqlite3')
import sys
sys.modules['sqlite3'] = sys.modules.pop('pysqlite3')

import json
import os
import re
import logging
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import numpy as np
import torch
import chromadb
from rank_bm25 import BM25Okapi
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sentence_transformers import SentenceTransformer, CrossEncoder

# ------------------------------------------------------------------ config
CHROMA_HOST     = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT     = int(os.environ.get("CHROMA_PORT", 8000))
COLLECTION_NAME = os.environ.get("COLLECTION_NAME", "cms_twiki")

EMBED_MODEL    = "WhereIsAI/UAE-Large-V1"
RERANK_MODEL   = "BAAI/bge-reranker-base"
RETRIEVAL_GPU  = "cuda:0"

VLLM_URL   = os.environ.get("VLLM_URL", "http://localhost:8001/v1/chat/completions")
VLLM_MODEL = os.environ.get("VLLM_MODEL", "Qwen/Qwen2.5-14B-Instruct-AWQ")

# UAE-Large-V1 is AnglE-trained: queries get this prefix, documents do not.
# The embedding run indexed documents bare, which is correct. Keeping this
# inside embed_query() means no call site can forget it.
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

K_DENSE    = 30    # candidates from the vector store
K_LEXICAL  = 30    # candidates from BM25
K_RERANK   = 40    # fused candidates fed to the cross-encoder
K_FINAL    = 6     # chunks that reach the prompt
RRF_K      = 60    # reciprocal rank fusion constant
CTX_CHARS  = 14000 # rough context budget; ~4k tokens, leaves room to generate

SYSTEM_PROMPT = """You answer questions about CMS experiment documentation \
using only the numbered sources provided.

Rules:
- Cite the source number in brackets after each claim, like [2].
- If the sources do not contain the answer, say so plainly. Do not fill gaps \
from general knowledge about CMS or physics software.
- TWiki pages go stale. If sources disagree, prefer the one with the more \
recent date and say that they conflict.
- Preserve exact identifiers verbatim: release names, dataset paths, config \
parameters, command flags."""

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("rag")

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def tokenize(text: str) -> list[str]:
    """Lexical tokens, keeping identifiers whole AND split.

    CMSSW_14_0_X stays as one token so an exact query matches it, and also
    yields cmssw/14/0/x so a partial query still hits. This is the main
    reason BM25 earns its place next to the dense index.
    """
    out = []
    for tok in TOKEN_RE.findall(text.lower()):
        out.append(tok)
        if "_" in tok:
            out.extend(p for p in tok.split("_") if p)
    return out


# --------------------------------------------------------------- retriever
class Retriever:
    def __init__(self):
        log.info("Loading embedder %s on %s", EMBED_MODEL, RETRIEVAL_GPU)
        self.embedder = SentenceTransformer(EMBED_MODEL, device=RETRIEVAL_GPU)

        log.info("Loading reranker %s on %s", RERANK_MODEL, RETRIEVAL_GPU)
        self.reranker = CrossEncoder(RERANK_MODEL, device=RETRIEVAL_GPU,
                                     max_length=512)

        log.info("Connecting to ChromaDB %s:%s", CHROMA_HOST, CHROMA_PORT)
        client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
        self.col = client.get_collection(COLLECTION_NAME)
        log.info("  %s: %d vectors", COLLECTION_NAME, self.col.count())

        self._build_lexical_index()

    def _build_lexical_index(self):
        """Pull the whole corpus once for BM25 and neighbour lookup.

        Chroma has no lexical index, so BM25 lives in-process. This also
        gives free O(1) neighbour expansion later - no extra round trips.
        """
        log.info("Building lexical index (one-time corpus fetch)...")
        self.docs, self.metas, self.ids = [], [], []
        offset, page = 0, 5000
        while True:
            batch = self.col.get(limit=page, offset=offset,
                                 include=["documents", "metadatas"])
            if not batch["ids"]:
                break
            self.ids.extend(batch["ids"])
            self.docs.extend(batch["documents"])
            self.metas.extend(batch["metadatas"])
            offset += len(batch["ids"])
            log.info("  fetched %d", offset)

        self.pos = {cid: i for i, cid in enumerate(self.ids)}
        self.bm25 = BM25Okapi([tokenize(d) for d in self.docs])
        log.info("Lexical index ready: %d documents", len(self.docs))

    def embed_query(self, query: str) -> list[float]:
        vec = self.embedder.encode([QUERY_PREFIX + query],
                                   normalize_embeddings=True)
        return vec[0].tolist()

    def _dense(self, query: str, where: Optional[dict]) -> list[str]:
        res = self.col.query(
            query_embeddings=[self.embed_query(query)],
            n_results=K_DENSE,
            where=where or None,
            include=["metadatas"],
        )
        return res["ids"][0]

    def _lexical(self, query: str) -> list[str]:
        scores = self.bm25.get_scores(tokenize(query))
        top = np.argsort(scores)[::-1][:K_LEXICAL]
        return [self.ids[i] for i in top if scores[i] > 0]

    @staticmethod
    def _rrf(*rankings: list[str]) -> list[str]:
        """Reciprocal rank fusion - combines lists without needing the
        dense and lexical scores to be on a comparable scale."""
        fused: dict[str, float] = {}
        for ranking in rankings:
            for rank, cid in enumerate(ranking):
                fused[cid] = fused.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
        return sorted(fused, key=fused.get, reverse=True)

    def _neighbours(self, cid: str) -> list[str]:
        """Adjacent chunks from the same page, for continuous context.

        Ids are globally sequential, so neighbours are cid +/- 1 - but only
        if they belong to the same source_file and are adjacent by
        chunk_index. Without that guard you splice in the tail of an
        unrelated page.
        """
        i = self.pos.get(cid)
        if i is None:
            return []
        meta = self.metas[i]
        out = []
        for j in (i - 1, i + 1):
            if 0 <= j < len(self.ids):
                m = self.metas[j]
                same_page = m.get("source_file") == meta.get("source_file")
                adjacent = abs(m.get("chunk_index", -99)
                               - meta.get("chunk_index", 99)) == 1
                if same_page and adjacent:
                    out.append(self.ids[j])
        return out

    def search(self, query: str, k: int = K_FINAL,
               where: Optional[dict] = None,
               expand: bool = True) -> list[dict]:
        candidates = self._rrf(self._dense(query, where),
                               self._lexical(query))[:K_RERANK]
        if not candidates:
            return []

        pairs = [(query, self.docs[self.pos[c]]) for c in candidates
                 if c in self.pos]
        valid = [c for c in candidates if c in self.pos]
        scores = self.reranker.predict(pairs, batch_size=32)

        ranked = sorted(zip(valid, scores), key=lambda t: -t[1])[:k]

        results, seen = [], set()
        for cid, score in ranked:
            i = self.pos[cid]
            text = self.docs[i]
            if expand:
                parts = []
                for nid in self._neighbours(cid):
                    if nid not in seen:
                        parts.append(self.docs[self.pos[nid]])
                        seen.add(nid)
                if parts:
                    text = "\n".join(parts[:1] + [text] + parts[1:])
            seen.add(cid)
            results.append({
                "id": cid,
                "score": float(score),
                "text": text,
                "page_title": self.metas[i].get("page_title", ""),
                "section_heading": self.metas[i].get("section_heading", ""),
                "source_file": self.metas[i].get("source_file", ""),
                "date": self.metas[i].get("date", ""),
                "author": self.metas[i].get("author", ""),
            })
        return results


# ------------------------------------------------------------------- app
retriever: Optional[Retriever] = None
http_client: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global retriever, http_client
    retriever = Retriever()
    http_client = httpx.AsyncClient(timeout=httpx.Timeout(300.0))
    yield
    await http_client.aclose()


app = FastAPI(title="CMS TWiki RAG", lifespan=lifespan)


class SearchRequest(BaseModel):
    query: str
    k: int = Field(default=K_FINAL, ge=1, le=20)
    expand: bool = True


class ChatRequest(BaseModel):
    query: str
    k: int = Field(default=K_FINAL, ge=1, le=20)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=1024, ge=1, le=4096)
    stream: bool = True


@app.get("/health")
async def health():
    llm_ok = False
    try:
        r = await http_client.get(VLLM_URL.replace("/chat/completions", "/models"))
        llm_ok = r.status_code == 200
    except Exception:
        pass
    return {
        "chunks": len(retriever.docs) if retriever else 0,
        "gpu_retrieval": torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
        "llm_reachable": llm_ok,
    }


@app.post("/search")
async def search(req: SearchRequest):
    """Retrieval only - use this to debug relevance without burning
    generation time. Returns reranker scores so you can see the margin."""
    hits = retriever.search(req.query, k=req.k, expand=req.expand)
    return {"query": req.query, "results": hits}


def build_context(hits: list[dict]) -> tuple[str, list[dict]]:
    blocks, sources, used = [], [], 0
    for n, h in enumerate(hits, 1):
        header = f"[{n}] {h['page_title']}"
        if h["section_heading"]:
            header += f" - {h['section_heading']}"
        if h["date"]:
            header += f" (last modified {h['date']})"
        block = f"{header}\n{h['text']}"
        if used + len(block) > CTX_CHARS:
            break
        blocks.append(block)
        used += len(block)
        sources.append({k: h[k] for k in
                        ("id", "page_title", "section_heading",
                         "source_file", "date", "score")})
    return "\n\n---\n\n".join(blocks), sources


@app.post("/chat")
async def chat(req: ChatRequest):
    hits = retriever.search(req.query, k=req.k)
    if not hits:
        raise HTTPException(404, "No relevant documents found")

    context, sources = build_context(hits)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user",
         "content": f"Sources:\n\n{context}\n\nQuestion: {req.query}"},
    ]
    payload = {
        "model": VLLM_MODEL,
        "messages": messages,
        "temperature": req.temperature,
        "max_tokens": req.max_tokens,
        "stream": req.stream,
    }

    if not req.stream:
        r = await http_client.post(VLLM_URL, json=payload)
        r.raise_for_status()
        answer = r.json()["choices"][0]["message"]["content"]
        return {"answer": answer, "sources": sources}

    async def event_stream():
        # Sources first, so the client can render citations before the
        # answer finishes streaming.
        yield f"data: {json.dumps({'type': 'sources', 'sources': sources})}\n\n"
        async with http_client.stream("POST", VLLM_URL, json=payload) as r:
            async for line in r.aiter_lines():
                if not line.startswith("data: "):
                    continue
                data = line[6:]
                if data.strip() == "[DONE]":
                    break
                try:
                    delta = json.loads(data)["choices"][0]["delta"]
                except (json.JSONDecodeError, KeyError, IndexError):
                    continue
                if "content" in delta and delta["content"]:
                    yield f"data: {json.dumps({'type': 'token', 'text': delta['content']})}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
