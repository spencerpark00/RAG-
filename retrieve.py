"""2단계: BM25 검색 (순수 Python, 외부 패키지 없음)

토큰화
- 한국어 형태소 분석기 없이 '문자 bigram'을 쓴다.
  예) '할인반환금은' → 할인 인반 반환 환금 금은
  조사가 붙어도('반환금은', '반환금을') 앞쪽 bigram이 겹쳐 매칭된다.
- 공백 단위 단어 전체도 토큰에 넣어 정확히 일치하면 가산점을 받게 한다.

실행: python retrieve.py "질문"   →  상위 k개 청크 출력
"""
import json
import math
import re
import sys
from collections import Counter
from pathlib import Path

CHUNKS_PATH = Path(__file__).parent / "chunks.jsonl"


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


def main():
    query = " ".join(sys.argv[1:]) or "5G 스탠다드 요금제 월정액은 얼마인가요?"
    print(f"질문: {query}\n")
    print("| 순위 | chunk_id | 점수 | 상태 | 섹션 |\n|---|---|---|---|---|")
    for rank, r in enumerate(BM25(load_chunks()).search(query), 1):
        print(f"| {rank} | {r['chunk_id']} | {r['score']} | {r['status']} | {r['title']} > {r['section']} |")


if __name__ == "__main__":
    main()
