"""2단계: BM25 검색 (순수 Python, 외부 패키지 없음)

토큰화
- 한국어 형태소 분석기 없이 '문자 bigram'을 쓴다.
  예) '할인반환금은' → 할인 인반 반환 환금 금은
  조사가 붙어도('반환금은', '반환금을') 앞쪽 bigram이 겹쳐 매칭된다.
- 공백 단위 단어 전체도 토큰에 넣어 정확히 일치하면 가산점을 받게 한다.

벡터 검색(VectorSearch)과 하이브리드(Hybrid)는 embed.py로 만든 embeddings.json을 쓴다.

실행: python retrieve.py "질문" [--retriever=bm25|vector|hybrid]   →  상위 k개 청크 출력
"""
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

CHUNKS_PATH = Path(__file__).parent / "chunks.jsonl"
EMBEDDINGS_PATH = Path(__file__).parent / "embeddings.json"
RETRIEVERS = ("bm25", "vector", "hybrid")


def tokenize(text):
    tokens = []
    for word in re.findall(r"[0-9a-z가-힣]+", text.lower()):
        tokens.append(word)
        if len(word) > 1:
            tokens.extend(word[i:i + 2] for i in range(len(word) - 1))
    return tokens


class BM25:
    def __init__(self, chunks, k1=1.5, b=0.75):
        self.chunks = chunks
        self.k1, self.b = k1, b
        self.doc_tfs = [Counter(tokenize(c["text"])) for c in chunks]
        self.doc_lens = [sum(tf.values()) for tf in self.doc_tfs]
        self.avg_len = sum(self.doc_lens) / len(self.doc_lens)
        df = Counter(t for tf in self.doc_tfs for t in tf)
        n = len(chunks)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def score(self, query_tokens, i):
        tf, dl = self.doc_tfs[i], self.doc_lens[i]
        s = 0.0
        for t in query_tokens:
            if t in tf:
                f = tf[t]
                s += self.idf[t] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * dl / self.avg_len))
        return s

    def search(self, query, k=5):
        q = tokenize(query)
        scored = [(self.score(q, i), i) for i in range(len(self.chunks))]
        scored.sort(reverse=True)
        return [{**self.chunks[i], "score": round(s, 2)} for s, i in scored[:k]]


def load_chunks(path=CHUNKS_PATH):
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f]


class VectorSearch:
    """질문을 bge-m3로 임베딩해 청크 벡터와의 코사인 유사도(정규화된 벡터의 내적)로 순위를 매긴다."""

    def __init__(self, chunks, path=EMBEDDINGS_PATH):
        vectors = json.loads(path.read_text(encoding="utf-8"))["vectors"]
        self.chunks = [c for c in chunks if c["chunk_id"] in vectors]
        self.vectors = [vectors[c["chunk_id"]] for c in self.chunks]

    def search(self, query, k=5):
        from embed import embed_texts  # embed.py가 이 모듈을 import하므로 순환 import를 피해 여기서 불러온다
        q = embed_texts([query])[0]
        scored = sorted(((sum(a * b for a, b in zip(q, v)), i) for i, v in enumerate(self.vectors)), reverse=True)
        return [{**self.chunks[i], "score": round(s, 3)} for s, i in scored[:k]]


class Hybrid:
    """BM25와 벡터 검색 결과를 RRF(Reciprocal Rank Fusion)로 합친다.
    점수 척도가 서로 달라서 점수 대신 '순위'만 쓴다: score = Σ 1 / (60 + 순위)."""

    def __init__(self, chunks, rrf_k=60, depth=20):
        self.retrievers = [BM25(chunks), VectorSearch(chunks)]
        self.rrf_k, self.depth = rrf_k, depth

    def search(self, query, k=5):
        fused, by_id = {}, {}
        for retriever in self.retrievers:
            for rank, r in enumerate(retriever.search(query, k=self.depth), 1):
                fused[r["chunk_id"]] = fused.get(r["chunk_id"], 0) + 1 / (self.rrf_k + rank)
                by_id[r["chunk_id"]] = r
        top = sorted(fused, key=fused.get, reverse=True)[:k]
        return [{**by_id[cid], "score": round(fused[cid], 4)} for cid in top]


def make_retriever(mode=None, chunks=None):
    """mode 생략 시: embeddings.json이 있으면 hybrid, 없으면 bm25."""
    chunks = chunks or load_chunks()
    if mode is None:
        mode = "hybrid" if EMBEDDINGS_PATH.exists() else "bm25"
    if mode != "bm25" and not EMBEDDINGS_PATH.exists():
        sys.exit(f"{EMBEDDINGS_PATH.name}이 없습니다. 먼저 'python embed.py'를 실행하세요.")
    return {"bm25": BM25, "vector": VectorSearch, "hybrid": Hybrid}[mode](chunks)


def retriever_arg(argv):
    """명령줄에서 --retriever=xxx 값을 꺼낸다 (없으면 None)."""
    mode = next((a.split("=", 1)[1] for a in argv if a.startswith("--retriever=")), None)
    if mode is not None and mode not in RETRIEVERS:
        sys.exit(f"--retriever는 {RETRIEVERS} 중 하나")
    return mode


def main():
    query = " ".join(a for a in sys.argv[1:] if not a.startswith("--")) or "5G 스탠다드 요금제 월정액은 얼마인가요?"
    retriever = make_retriever(retriever_arg(sys.argv[1:]))
    print(f"질문: {query}  (검색: {type(retriever).__name__})\n")
    print("| 순위 | chunk_id | 점수 | 상태 | 섹션 |\n|---|---|---|---|---|")
    for rank, r in enumerate(retriever.search(query), 1):
        print(f"| {rank} | {r['chunk_id']} | {r['score']} | {r['status']} | {r['title']} > {r['section']} |")


if __name__ == "__main__":
    main()
