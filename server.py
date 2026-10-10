"""5단계: 웹 API 서버 (FastAPI)

브라우저 ↔ 이 서버(/api/*) ↔ RAG(retrieve.py, answer.py) ↔ Ollama

엔드포인트
  GET  /               채팅 화면: React 빌드(frontend/dist)가 있으면 그것, 없으면 static/index.html
  GET  /classic        단일 HTML 버전 화면 (static/index.html)
  GET  /api/health     Ollama 연결, 사용 가능한 검색 방식
  POST /api/chat       {"question", "retriever", "llm", "rewrite"} → SSE 스트림
                       event: rewrite (보강 검색어) → sources (검색 청크) → token (답 조각, 여러 번) → done (최종 정리)
                       rewrite 생략 시: API 모델(Groq)이면 켜고, 로컬 모델이면 끈다 (로컬은 느려서)
  POST /api/feedback   {"question", "answer", "rating": "up"|"down"} → feedback.jsonl에 추가

  문서 관리 (indexer.py)
  GET    /api/docs              문서 목록 + 색인 상태
  GET    /api/docs/{no}         원문 + 청크 미리보기
  POST   /api/docs              업로드 {"title", "content", "doc_id", "status", "effective"}
  PATCH  /api/docs/{no}         {"status", "effective", "excluded"} → doc_overrides.json
  DELETE /api/docs/{no}         업로드 문서 삭제
  POST   /api/index             재색인 (바뀐 청크만 임베딩) → 검색기 다시 로딩

실행: python server.py   →  http://localhost:8000
"""
import json
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import llm
from answer import DEFAULT_PROMPT, MODEL, TOP_K, build_messages, final_answer
from query import fused_search, rewrite_query, suggestions
import indexer
from retrieve import EMBEDDINGS_PATH, RETRIEVERS, load_chunks, make_retriever

ROOT = Path(__file__).parent
FEEDBACK_PATH = ROOT / "feedback.jsonl"
DIST = ROOT / "frontend" / "dist"  # cd frontend && npm run build 결과물

app = FastAPI(title="한빛텔레콤 업무지식 검색 API")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
if (DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

# 검색기는 서버 시작 때(그리고 재색인 직후) 한 번 만든다 (BM25 색인·벡터 로딩 비용을 질문마다 내지 않도록)
CHUNKS, AVAILABLE, RETRIEVER_OBJS, DEFAULT_RETRIEVER = [], [], {}, "bm25"
INDEX_LOCK = threading.Lock()


def load_retrievers():
    global CHUNKS, AVAILABLE, RETRIEVER_OBJS, DEFAULT_RETRIEVER
    chunks = load_chunks()
    vectors_ok = False
    if EMBEDDINGS_PATH.exists():
        ids = set(json.loads(EMBEDDINGS_PATH.read_text(encoding="utf-8"))["vectors"])
        vectors_ok = all(c["chunk_id"] in ids for c in chunks)  # 청크와 벡터가 어긋나면 벡터 검색을 끈다
    available = [m for m in RETRIEVERS if m == "bm25" or vectors_ok]
    objs = {m: make_retriever(m, chunks) for m in available}
    CHUNKS, AVAILABLE, RETRIEVER_OBJS = chunks, available, objs  # 한 번에 교체 → 진행 중인 질문은 이전 검색기로 끝남
    DEFAULT_RETRIEVER = "hybrid" if "hybrid" in available else "bm25"


load_retrievers()


class ChatRequest(BaseModel):
    question: str
    retriever: str | None = None
    llm: str | None = None
    rewrite: bool | None = None


class DocUpload(BaseModel):
    title: str
    content: str
    doc_id: str = ""
    status: str = "미표기"
    effective: str = ""


class DocPatch(BaseModel):
    status: str | None = None
    effective: str | None = None
    excluded: bool | None = None


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
    react = DIST / "index.html"
    return FileResponse(react if react.exists() else ROOT / "static" / "index.html")


@app.get("/classic")
def classic():
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
            "chunks": len(CHUNKS), "llms": [llm.describe(p) for p in llm.available()], "default_llm": llm.DEFAULT_LLM}


@app.post("/api/chat")
def chat(req: ChatRequest):
    objs = RETRIEVER_OBJS  # 재색인으로 교체되더라도 이 질문은 같은 검색기로 끝내도록 잡아 둔다
    mode = req.retriever if req.retriever in objs else DEFAULT_RETRIEVER
    engine = req.llm if req.llm in llm.available() else llm.DEFAULT_LLM
    do_rewrite = req.rewrite if req.rewrite is not None else engine != "ollama"

    def events():
        start = time.time()
        used, notice, terms = mode, None, None
        try:
            if do_rewrite:
                # ① 질문 재작성: 일상 표현 → 업무 용어 검색어 (검색만 넓히고, 답변에는 원래 질문을 쓴다)
                terms = rewrite_query(req.question, llm.make_llm(engine))
                yield sse("rewrite", {"terms": terms})
            queries = [req.question, terms]
            try:
                chunks = fused_search(objs[mode], queries, k=TOP_K)
            except OSError:
                if mode == "bm25":
                    raise
                # 의미·하이브리드 검색은 질문 임베딩에 로컬 Ollama(bge-m3)가 필요 → 꺼져 있으면 키워드 검색으로 대체
                chunks, used = fused_search(objs["bm25"], queries, k=TOP_K), "bm25"
                notice = "Ollama(bge-m3)에 연결할 수 없어 키워드 검색으로 대체했습니다."
            yield sse("sources", {"retriever": used, "notice": notice, "terms": terms,
                                  "chunks": [chunk_view(c) for c in chunks],
                                  "search_ms": int((time.time() - start) * 1000)})
            text = ""
            for piece in llm.stream(build_messages(req.question, chunks, DEFAULT_PROMPT), engine):
                text += piece
                yield sse("token", {"text": piece})
        except llm.LLMError as e:  # API 키 오류·사용량 한도 등 (메시지에 원인이 들어 있음)
            yield sse("error", {"message": str(e)})
            return
        except OSError as e:  # Ollama 꺼짐 등 (URLError는 OSError의 하위 클래스)
            yield sse("error", {"message": f"Ollama 서버에 연결할 수 없습니다: {e}"})
            return
        final = final_answer(text)
        refused = "확인할수없" in final.replace(" ", "")
        # 거부한 답에 모델이 '(근거: 07-0)'을 붙이는 경우가 있어, 거부면 인용 목록을 비운다
        cited = [] if refused else [c["chunk_id"] for c in chunks if c["chunk_id"] in text]
        yield sse("done", {"answer": final, "cited": cited, "refused": refused,
                           "seconds": round(time.time() - start, 1), "llm": llm.describe(engine),
                           # ② 못 찾았을 때: 검색된 문서 중 관련 있어 보이는 것을 추천 질문으로
                           "suggestions": suggestions(chunks) if refused else []})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/feedback")
def feedback(fb: Feedback):
    record = {"time": datetime.now().isoformat(timespec="seconds"), **fb.model_dump()}
    with FEEDBACK_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return {"ok": True}


# ---------------- 문서 관리 ----------------

@app.get("/api/docs")
def docs_list():
    return {"docs": indexer.list_docs(), "index": indexer.index_status(), "retrievers": AVAILABLE}


@app.get("/api/docs/{doc_no}")
def docs_detail(doc_no: str):
    d = indexer.doc_detail(doc_no)
    if not d:
        raise HTTPException(404, "문서를 찾을 수 없습니다")
    return d


@app.post("/api/docs")
def docs_upload(body: DocUpload):
    if not body.content.strip():
        raise HTTPException(400, "본문이 비어 있습니다")
    try:
        return {"doc_no": indexer.add_upload(body.title, body.content, body.doc_id, body.status, body.effective)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.patch("/api/docs/{doc_no}")
def docs_patch(doc_no: str, body: DocPatch):
    try:
        indexer.set_override(doc_no, body.status, body.effective, body.excluded)
    except KeyError:
        raise HTTPException(404, "문서를 찾을 수 없습니다")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.delete("/api/docs/{doc_no}")
def docs_delete(doc_no: str):
    try:
        indexer.delete_upload(doc_no)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.post("/api/index")
def reindex():
    if not INDEX_LOCK.acquire(blocking=False):
        raise HTTPException(409, "이미 색인 중입니다")
    try:
        stats = indexer.build_index()
        load_retrievers()
        return {"stats": stats, "retrievers": AVAILABLE}
    finally:
        INDEX_LOCK.release()


if __name__ == "__main__":
    print("브라우저에서 http://localhost:8000 을 여세요. (종료: Ctrl+C)")
    uvicorn.run(app, host="127.0.0.1", port=8000)
