"""2-b단계: 청크 임베딩 (Ollama bge-m3, 표준 라이브러리만 사용)

chunks.jsonl의 각 청크 text를 1024차원 벡터로 바꿔 embeddings.json에 저장한다.
벡터는 길이 1로 정규화해 두어, 검색 때 내적(dot product)만으로 코사인 유사도를 구한다.

실행: python embed.py   (문서나 청킹이 바뀌면 chunk.py 다음에 다시 실행)
"""
import json
import math
import time
import urllib.request
from pathlib import Path

from retrieve import load_chunks

EMBED_URL = "http://localhost:11434/api/embed"
EMBED_MODEL = "bge-m3"
OUT_PATH = Path(__file__).parent / "embeddings.json"
BATCH = 8  # 한 번에 보내는 청크 수 (8GB 맥 메모리 고려)


def normalize(v):
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


def embed_texts(texts, model=EMBED_MODEL, timeout=600):
    req = urllib.request.Request(
        EMBED_URL,
        data=json.dumps({"model": model, "input": texts}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return [normalize(v) for v in json.loads(resp.read())["embeddings"]]


def main():
    chunks = load_chunks()
    start = time.time()
    from indexer import text_hash
    vectors = {}
    for i in range(0, len(chunks), BATCH):
        batch = chunks[i:i + BATCH]
        for c, v in zip(batch, embed_texts([c["text"] for c in batch])):
            vectors[c["chunk_id"]] = [round(x, 6) for x in v]
        print(f"{min(i + BATCH, len(chunks))}/{len(chunks)}", end="\r", flush=True)
    hashes = {c["chunk_id"]: text_hash(c["text"]) for c in chunks}  # indexer.py 증분 색인이 재사용 판단에 씀
    OUT_PATH.write_text(json.dumps({"model": EMBED_MODEL, "vectors": vectors, "hashes": hashes}), encoding="utf-8")
    dim = len(next(iter(vectors.values())))
    print(f"청크 {len(vectors)}개 → {dim}차원 벡터, {time.time() - start:.0f}초. 저장: {OUT_PATH.name}")


if __name__ == "__main__":
    main()
