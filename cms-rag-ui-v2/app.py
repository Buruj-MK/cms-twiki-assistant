"""
CMS Documentation Assistant - Web Interface
Flask backend: serves UI, proxies to RAG service, handles feedback & history.
"""

import json
import os
import uuid
from datetime import datetime, timezone

import httpx
from flask import Flask, Response, jsonify, request, send_from_directory

RAG_SERVICE_URL = os.environ.get("RAG_SERVICE_URL", "http://vocmsgpu.cern.ch:8080")
FEEDBACK_FILE = os.environ.get("FEEDBACK_FILE", "data/feedback.jsonl")
HISTORY_FILE = os.environ.get("HISTORY_FILE", "data/history.jsonl")
PORT = int(os.environ.get("PORT", 8000))
CONTEXT_TURNS = 3  # number of previous Q&A pairs to include

app = Flask(__name__, static_folder="static")


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/static/<path:path>")
def static_files(path):
    return send_from_directory("static", path)


def build_contextual_query(query, history):
    """Prepend recent conversation history to the query so the LLM has context."""
    if not history:
        return query
    recent = history[-(CONTEXT_TURNS * 2):]
    context_parts = []
    for msg in recent:
        role = "User" if msg.get("role") == "user" else "Assistant"
        content = msg.get("content", "")
        if len(content) > 300:
            content = content[:300] + "..."
        context_parts.append(f"{role}: {content}")
    context_str = "\n".join(context_parts)
    return f"[Previous conversation]\n{context_str}\n\n[Current question]\n{query}"


@app.route("/api/chat", methods=["POST"])
def chat():
    body = request.get_json(force=True)
    query = body.get("query", "")
    history = body.get("history", [])

    contextual_query = build_contextual_query(query, history)
    payload = {"query": contextual_query}

    def stream_response():
        try:
            with httpx.Client(timeout=120.0) as client:
                with client.stream(
                    "POST",
                    f"{RAG_SERVICE_URL}/chat",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                ) as resp:
                    for line in resp.iter_lines():
                        if not line or not line.startswith("data: "):
                            continue
                        data_str = line[6:].strip()
                        try:
                            chunk = json.loads(data_str)
                            msg_type = chunk.get("type", "")
                            if msg_type == "sources":
                                yield f"data: {json.dumps({'type': 'sources', 'sources': chunk.get('sources', [])})}\n\n"
                            elif msg_type == "token":
                                yield f"data: {json.dumps({'type': 'token', 'content': chunk.get('text', '')})}\n\n"
                            elif msg_type == "done":
                                yield "data: [DONE]\n\n"
                                break
                        except json.JSONDecodeError:
                            continue
        except httpx.ConnectError:
            yield f"data: {json.dumps({'type': 'error', 'content': 'Cannot reach RAG service at ' + RAG_SERVICE_URL})}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"

    return Response(stream_response(), mimetype="text/event-stream")


@app.route("/api/feedback", methods=["POST"])
def feedback():
    body = request.get_json(force=True)
    record = {
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "conversation_id": body.get("conversation_id", ""),
        "query": body.get("query", ""),
        "response": body.get("response", ""),
        "sources": body.get("sources", []),
        "rating": body.get("rating", ""),
        "comment": body.get("comment", ""),
    }
    os.makedirs(os.path.dirname(FEEDBACK_FILE), exist_ok=True)
    with open(FEEDBACK_FILE, "a") as f:
        f.write(json.dumps(record) + "\n")
    return jsonify({"status": "ok"})


@app.route("/api/feedback/stats", methods=["GET"])
def feedback_stats():
    if not os.path.exists(FEEDBACK_FILE):
        return jsonify({"total": 0, "up": 0, "down": 0, "entries": []})
    entries = []
    with open(FEEDBACK_FILE, "r") as f:
        for line in f:
            if line.strip():
                entries.append(json.loads(line))
    up = sum(1 for e in entries if e.get("rating") == "up")
    down = sum(1 for e in entries if e.get("rating") == "down")
    return jsonify({"total": len(entries), "up": up, "down": down, "recent": entries[-20:]})


@app.route("/api/history", methods=["GET"])
def list_history():
    if not os.path.exists(HISTORY_FILE):
        return jsonify([])
    convos = {}
    with open(HISTORY_FILE, "r") as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            cid = entry["conversation_id"]
            convos[cid] = {
                "conversation_id": cid,
                "title": entry.get("title", "Untitled"),
                "updated_at": entry.get("updated_at", ""),
                "message_count": entry.get("message_count", 0),
            }
    return jsonify(sorted(convos.values(), key=lambda x: x["updated_at"], reverse=True))


@app.route("/api/history/<conversation_id>", methods=["GET"])
def get_history(conversation_id):
    if not os.path.exists(HISTORY_FILE):
        return jsonify({"messages": []}), 404
    with open(HISTORY_FILE, "r") as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry["conversation_id"] == conversation_id:
                return jsonify(entry)
    return jsonify({"messages": []}), 404


@app.route("/api/history", methods=["POST"])
def save_history():
    body = request.get_json(force=True)
    body["updated_at"] = datetime.now(timezone.utc).isoformat()
    entries = []
    found = False
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r") as f:
            for line in f:
                if not line.strip():
                    continue
                entry = json.loads(line)
                if entry["conversation_id"] == body["conversation_id"]:
                    entries.append(body)
                    found = True
                else:
                    entries.append(entry)
    if not found:
        entries.append(body)
    os.makedirs(os.path.dirname(HISTORY_FILE), exist_ok=True)
    with open(HISTORY_FILE, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return jsonify({"status": "ok"})


@app.route("/api/history/<conversation_id>", methods=["DELETE"])
def delete_history(conversation_id):
    if not os.path.exists(HISTORY_FILE):
        return jsonify({"status": "ok"})
    entries = []
    with open(HISTORY_FILE, "r") as f:
        for line in f:
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry["conversation_id"] != conversation_id:
                entries.append(entry)
    with open(HISTORY_FILE, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")
    return jsonify({"status": "ok"})


@app.route("/api/health", methods=["GET"])
def health():
    rag_ok = False
    try:
        r = httpx.get(f"{RAG_SERVICE_URL}/health", timeout=5.0)
        rag_ok = r.status_code == 200
    except Exception:
        pass
    return jsonify({
        "status": "ok",
        "rag_service": "connected" if rag_ok else "unreachable",
        "rag_url": RAG_SERVICE_URL,
    })


if __name__ == "__main__":
    os.makedirs("data", exist_ok=True)
    print(f"CMS Docs Assistant UI starting on port {PORT}")
    print(f"RAG service: {RAG_SERVICE_URL}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
