"""5단계: 웹 API 서버 (FastAPI)

브라우저 ↔ 이 서버(/api/*) ↔ RAG(retrieve.py, answer.py) ↔ Ollama

엔드포인트
  GET  /               채팅 화면 (static/index.html)
  GET  /api/health     Ollama 연결, 사용 가능한 검색 방식
  POST /api/chat       {"question", "retriever"} → SSE 스트림
                       event: sources (검색 청크) → token (답 조각, 여러 번) → done (최종 정리)
  POST /api/feedback   {"question", "answer", "rating": "up"|"down"} → feedback.jsonl에 추가

실행: python server.py   →  http://localhost:8000
"""
import json
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from answer import DEFAULT_PROMPT, MODEL, TOP_K, build_messages, final_answer, stream_ollama
from retrieve import EMBEDDINGS_PATH, RETRIEVERS, load_chunks, make_retriever

ROOT = Path(__file__).parent
FEEDBACK_PATH = ROOT / "feedback.jsonl"

app = FastAPI(title="한빛텔레콤 업무지식 검색 API")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

# 검색기는 서버 시작 때 한 번 만든다 (BM25 색인·벡터 로딩 비용을 질문마다 내지 않도록)
CHUNKS = load_chunks()
AVAILABLE = [m for m in RETRIEVERS if m == "bm25" or EMBEDDINGS_PATH.exists()]
RETRIEVER_OBJS = {m: make_retriever(m, CHUNKS) for m in AVAILABLE}
DEFAULT_RETRIEVER = "hybrid" if "hybrid" in AVAILABLE else "bm25"


class ChatRequest(BaseModel):
    question: str
    retriever: str | None = None


class Feedback(BaseModel):
    question: str
    answer: str
    rating: str
    retriever: str | None = None


def sse(event, data):
    """Server-Sent Events 한 건: 'event: 이름\\ndata: JSON\\n\\n'"""
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def chunk_view(c):
    keys = ("chunk_id", "doc_no", "doc_id", "title", "section", "status", "effective", "text", "score")
    return {k: c.get(k) for k in keys}


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/health")
def health():
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=3) as r:
            models = [m["name"] for m in json.loads(r.read())["models"]]
        ollama = {"ok": True, "models": models}
    except OSError as e:
        ollama = {"ok": False, "error": str(e)}
    return {"ollama": ollama, "llm": MODEL, "retrievers": AVAILABLE, "default_retriever": DEFAULT_RETRIEVER,
            "chunks": len(CHUNKS)}


@app.post("/api/chat")
def chat(req: ChatRequest):
    mode = req.retriever if req.retriever in RETRIEVER_OBJS else DEFAULT_RETRIEVER

    def events():
        start = time.time()
        try:
            chunks = RETRIEVER_OBJS[mode].search(req.question, k=TOP_K)
            yield sse("sources", {"retriever": mode, "chunks": [chunk_view(c) for c in chunks],
                                  "search_ms": int((time.time() - start) * 1000)})
            text = ""
            for piece in stream_ollama(build_messages(req.question, chunks, DEFAULT_PROMPT)):
                text += piece
                yield sse("token", {"text": piece})
        except OSError as e:  # Ollama 꺼짐 등 (URLError는 OSError의 하위 클래스)
            yield sse("error", {"message": f"Ollama 서버에 연결할 수 없습니다: {e}"})
            return
        final = final_answer(text)
        refused = "확인할수없" in final.replace(" ", "")
        # 거부한 답에 모델이 '(근거: 07-0)'을 붙이는 경우가 있어, 거부면 인용 목록을 비운다
        cited = [] if refused else [c["chunk_id"] for c in chunks if c["chunk_id"] in text]
        yield sse("done", {"answer": final, "cited": cited, "refused": refused,
                           "seconds": round(time.time() - start, 1)})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/feedback")
def feedback(fb: Feedback):
    record = {"time": datetime.now().isoformat(timespec="seconds"), **fb.model_dump()}
    with FEEDBACK_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True}


if __name__ == "__main__":
    print("브라우저에서 http://localhost:8000 을 여세요. (종료: Ctrl+C)")
    uvicorn.run(app, host="127.0.0.1", port=8000)
