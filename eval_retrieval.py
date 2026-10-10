"""검색 평가: 근거 문서가 상위 k개 청크 안에 있는가 (답변 정확성과 분리)

- 근거문서번호가 '-'인 질문(답없음 3개)은 적중 계산에서 제외하고,
  1위 점수만 기록한다. 나중에 '모른다' 판정 임계값을 정할 때 참고용.
- 근거 문서가 2개인 질문은 '하나라도(any)'와 '모두(all)'를 따로 센다.

실행: python eval_retrieval.py [--retriever=bm25|vector|hybrid] [--set=colloquial] [--rewrite --llm=groq]
  --set=colloquial : 문서 용어를 쓰지 않은 일상 표현 질문 15개 (experiments/colloquial_questions.csv)
  --rewrite        : 검색 전에 LLM이 질문을 업무 용어 검색어로 바꿔 함께 검색 (query.py)
"""
import csv
import sys
from pathlib import Path

from retrieve import make_retriever, retriever_arg

EVAL_PATH = Path(__file__).parent / "rag_dummy" / "eval_questions.csv"
COLLOQUIAL_PATH = Path(__file__).parent / "experiments" / "colloquial_questions.csv"
KS = (1, 3, 5)


def load_questions(path=EVAL_PATH):
    with path.open(encoding="utf-8-sig") as f:  # 파일에 BOM이 있음
        return list(csv.DictReader(f))


def main():
    retriever = make_retriever(retriever_arg(sys.argv[1:]))
    questions = load_questions(COLLOQUIAL_PATH if "--set=colloquial" in sys.argv else EVAL_PATH)
    rewrite = None
    if "--rewrite" in sys.argv:
        import llm
        from query import fused_search, rewrite_query
        pid = llm.llm_arg(sys.argv[1:])
        call = llm.make_llm(pid)
        rewrite = lambda q: rewrite_query(q, call)
        print(f"질문 재작성: {llm.describe(pid)['model']}\n")
    rewritten = {}
    hits_any = {k: 0 for k in KS}
    hits_all = {k: 0 for k in KS}
    answerable, rows = 0, []

    for q in questions:
        if rewrite:
            terms = rewritten[q["id"]] = rewrite(q["질문"])
            results = fused_search(retriever, [q["질문"], terms], k=max(KS))
        else:
            results = retriever.search(q["질문"], k=max(KS))
        ranked_docs = [r["doc_no"] for r in results]
        gold = [d.strip() for d in q["근거문서번호"].split(",") if d.strip() != "-"]
        top = f"{results[0]['chunk_id']}({results[0]['score']})"

        if not gold:
            rows.append((q["id"], q["유형"], "-", "-", top, " ".join(ranked_docs)))
            continue

        answerable += 1
        first_rank = next((i + 1 for i, d in enumerate(ranked_docs) if d in gold), None)
        for k in KS:
            hits_any[k] += any(d in ranked_docs[:k] for d in gold)
            hits_all[k] += all(d in ranked_docs[:k] for d in gold)
        rows.append((q["id"], q["유형"], ",".join(gold), first_rank or "미검색", top, " ".join(ranked_docs) + (f" ← {rewritten[q['id']]}" if rewrite else "")))

    print(f"## 검색 적중률 ({type(retriever).__name__}, 근거 문서가 있는 {answerable}문항)\n")
    print("| 지표 | " + " | ".join(f"Hit@{k}" for k in KS) + " |")
    print("|---|" + "---|" * len(KS))
    print("| any (근거 문서 하나라도) | " + " | ".join(f"{hits_any[k]}/{answerable}" for k in KS) + " |")
    print("| all (근거 문서 전부) | " + " | ".join(f"{hits_all[k]}/{answerable}" for k in KS) + " |")

    print("\n## 문항별\n")
    print("| id | 유형 | 근거 | 첫 적중 순위 | 1위 청크(점수) | 상위5 문서 |\n|---|---|---|---|---|---|")
    for row in rows:
        print("| " + " | ".join(str(x) for x in row) + " |")


if __name__ == "__main__":
    main()
