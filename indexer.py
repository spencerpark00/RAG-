"""6단계: 문서 관리 + 증분 색인

문서 관리 화면(server.py /api/docs, /api/index)이 쓰는 함수 모음.

색인(build_index) 흐름
  문서 폴더 2곳 + doc_overrides.json → 청킹(chunk.py) → chunks.jsonl
  → 청크 text의 해시가 바뀐 것만 bge-m3로 다시 임베딩 → embeddings.json
  (실무 색인 파이프라인의 핵심: 문서 1개가 바뀌어도 전체를 다시 임베딩하지 않는다)

실행: python indexer.py   (화면의 '재색인' 버튼과 같음)
"""
import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path

from chunk import DOCS_DIRS, OUT_PATH, OVERRIDES_PATH, UPLOAD_DIR, chunk_all, chunk_doc, iter_docs, load_overrides, write_chunks
from retrieve import EMBEDDINGS_PATH, load_chunks

ROOT = Path(__file__).parent
STATE_PATH = ROOT / "index_state.json"
STATUSES = ("현행", "폐지", "미표기")


def text_hash(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def docs_signature():
    """문서 파일들과 overrides의 변경 여부를 한 값으로 요약 (재색인이 필요한지 판단용)."""
    h = hashlib.sha1()
    for d in DOCS_DIRS:
        for p in sorted(d.glob("*.md")) if d.exists() else []:
            h.update(f"{p.name}:{p.stat().st_mtime_ns}:{p.stat().st_size}".encode())
    if OVERRIDES_PATH.exists():
        h.update(OVERRIDES_PATH.read_bytes())
    return h.hexdigest()[:16]


def load_state():
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def index_status():
    state = load_state()
    return {
        "indexed_at": state.get("indexed_at"),
        "needs_reindex": state.get("signature") != docs_signature(),
        "last": state.get("last"),
        "embeddings": EMBEDDINGS_PATH.exists(),
    }


# ---------------- 문서 목록·상세 ----------------

def list_docs():
    chunk_counts = {}
    if OUT_PATH.exists():
        for c in load_chunks():
            chunk_counts[c["doc_no"]] = chunk_counts.get(c["doc_no"], 0) + 1
    docs = []
    for d in iter_docs():
        docs.append({
            "doc_no": d["doc_no"], "file": d["file"], "title": d["title"], "doc_id": d["doc_id"],
            "status": d["status"], "effective": d["effective"], "source": d["source"],
            "excluded": d["excluded"], "overridden": d["overridden"],
            "chunks": chunk_counts.get(d["doc_no"], 0),
            "chars": sum(len(l) for l in d["body_lines"]),
        })
    return docs


def find_doc(doc_no):
    return next((d for d in iter_docs() if d["doc_no"] == doc_no), None)


def doc_detail(doc_no):
    d = find_doc(doc_no)
    if not d:
        return None
    folder = UPLOAD_DIR if d["source"] == "upload" else DOCS_DIRS[0]
    return {
        "doc_no": doc_no, "title": d["title"], "status": d["status"], "effective": d["effective"],
        "source": d["source"], "excluded": d["excluded"],
        "raw": (folder / d["file"]).read_text(encoding="utf-8"),
        "chunks": chunk_doc(d),  # 지금 설정으로 잘랐을 때의 청크 미리보기 (색인 전에도 확인 가능)
    }


# ---------------- 변경: 상태 지정·업로드·삭제 ----------------

def _save_overrides(o):
    OVERRIDES_PATH.write_text(json.dumps(o, ensure_ascii=False, indent=1), encoding="utf-8")


def set_override(doc_no, status=None, effective=None, excluded=None):
    if not find_doc(doc_no):
        raise KeyError(doc_no)
    o = load_overrides()
    cur = o.get(doc_no, {})
    if status is not None:
        if status not in STATUSES:
            raise ValueError(f"상태는 {STATUSES} 중 하나")
        cur["status"] = status
    if effective is not None:
        cur["effective"] = f"시행일 {effective}" if re.match(r"^\d{4}-\d{2}-\d{2}$", effective) else effective
    if excluded is not None:
        cur["excluded"] = excluded
    o[doc_no] = cur
    _save_overrides(o)


def add_upload(title, content, doc_id="", status="미표기", effective=""):
    """업로드 문서를 '# 제목 / - 문서번호: … / 시행일 / 상태' 머리말을 붙여 저장 → 청커가 그대로 읽는다."""
    if status not in STATUSES:
        raise ValueError(f"상태는 {STATUSES} 중 하나")
    title = title.strip() or "제목 없음"
    used = {int(d["doc_no"]) for d in iter_docs() if d["doc_no"].isdigit()}
    doc_no = f"{max(used | {0}) + 1:02d}"
    meta = [f"문서번호: {doc_id.strip() or 'UP-' + doc_no}"]
    if effective.strip():
        meta.append(f"시행일: {effective.strip()}")
    if status != "미표기":
        meta.append(f"상태: {status}")
    body = content.strip()
    if body.startswith("# "):  # 업로드 파일에 이미 제목 줄이 있으면 본문에서 뺀다
        body = body.split("\n", 1)[1].strip() if "\n" in body else ""
    safe = re.sub(r"[^\w가-힣]+", "_", title)[:40].strip("_") or "doc"
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / f"{doc_no}_{safe}.md").write_text(f"# {title}\n- {' / '.join(meta)}\n\n{body}\n", encoding="utf-8")
    return doc_no


def delete_upload(doc_no):
    d = find_doc(doc_no)
    if not d or d["source"] != "upload":
        raise ValueError("업로드한 문서만 삭제할 수 있습니다. 샘플 문서는 '색인 제외'를 쓰세요.")
    (UPLOAD_DIR / d["file"]).unlink()
    o = load_overrides()
    if o.pop(doc_no, None) is not None:
        _save_overrides(o)


# ---------------- 색인 ----------------

def build_index(embed=True):
    """청킹 → chunks.jsonl, 바뀐 청크만 임베딩 → embeddings.json. 통계를 돌려준다."""
    start = time.time()
    signature = docs_signature()
    chunks = chunk_all()
    write_chunks(chunks)
    stats = {"docs": len({c["doc_no"] for c in chunks}), "chunks": len(chunks), "embedded": 0, "reused": 0,
             "removed": 0, "embedding_error": None}

    if embed:
        try:
            old = json.loads(EMBEDDINGS_PATH.read_text(encoding="utf-8")) if EMBEDDINGS_PATH.exists() else {}
        except ValueError:
            old = {}
        old_vecs, old_hashes = old.get("vectors", {}), old.get("hashes", {})
        vectors, hashes, todo = {}, {}, []
        for c in chunks:
            h = text_hash(c["text"])
            hashes[c["chunk_id"]] = h
            if old_hashes.get(c["chunk_id"]) == h and c["chunk_id"] in old_vecs:
                vectors[c["chunk_id"]] = old_vecs[c["chunk_id"]]
                stats["reused"] += 1
            else:
                todo.append(c)
        try:
            from embed import BATCH, EMBED_MODEL, embed_texts
            for i in range(0, len(todo), BATCH):
                batch = todo[i:i + BATCH]
                for c, v in zip(batch, embed_texts([c["text"] for c in batch])):
                    vectors[c["chunk_id"]] = [round(x, 6) for x in v]
            stats["embedded"] = len(todo)
            stats["removed"] = len(set(old_vecs) - set(vectors))
            EMBEDDINGS_PATH.write_text(json.dumps({"model": EMBED_MODEL, "vectors": vectors, "hashes": hashes}), encoding="utf-8")
        except OSError as e:  # Ollama 꺼짐 등: BM25만으로도 검색은 되도록 청크는 저장해 둔다
            stats["embedding_error"] = f"임베딩 실패 (키워드 검색만 갱신됨): {e}"

    stats["seconds"] = round(time.time() - start, 1)
    STATE_PATH.write_text(json.dumps({
        "indexed_at": datetime.now().isoformat(timespec="seconds"),
        "signature": signature,
        "last": stats,
    }, ensure_ascii=False), encoding="utf-8")
    return stats


if __name__ == "__main__":
    s = build_index()
    print(f"문서 {s['docs']}개 → 청크 {s['chunks']}개 | 새로 임베딩 {s['embedded']} · 재사용 {s['reused']} · 삭제 {s['removed']} | {s['seconds']}초")
    if s["embedding_error"]:
        print(s["embedding_error"])
