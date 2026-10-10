"""7단계: 질문 재작성(검색어 확장) + 못 찾았을 때 추천

① 질문 재작성
  사용자의 일상 표현("폰 잃어버렸어")과 문서 용어("분실·도난 일시정지")가 다르면
  의미 검색도 빗나간다. 검색 전에 LLM에게 '문서 목록(제목·섹션명)'을 보여 주고
  질문을 업무 용어 검색어로 바꾸게 한 뒤, 원래 질문과 검색어 두 결과를 RRF로 합친다.
  → 답변 생성에는 원래 질문을 그대로 쓴다 (검색만 넓힌다).

② 못 찾았을 때 추천
  "확인할 수 없습니다"로 끝내지 않고, 검색된 청크 중 서로 다른 문서 3개를
  '혹시 이걸 찾으셨나요?' 추천 질문으로 돌려준다 (추가 LLM 호출 없음).

실행: python query.py "폰 잃어버렸어"   → 재작성된 검색어와 검색 결과 비교
"""
import re
import sys

from chunk import iter_docs, split_sections

REWRITE_PROMPT = """너는 통신사 고객센터 업무 문서 검색을 돕는다.
사용자의 질문을 아래 [문서 목록]에서 쓰는 업무 용어로 바꾼 검색어를 만든다.

[문서 목록]
{doc_list}

[규칙]
- 질문과 관련된 업무 용어 3~6개를 공백으로 구분해 한 줄로만 출력한다.
- 문서 목록에 나오는 용어를 우선 쓴다. 설명, 문장, 따옴표는 쓰지 않는다.
- 반드시 한국어로 쓴다.

[예시]
질문: 남편 명의로 바꾸고 싶어요
검색어: 명의변경 양도인 양수인 필요 서류

질문: {question}
검색어:"""


def table_terms(body_lines, limit=6):
    """표의 첫 열 값(예: 분실·도난, 해외 체류, P1)을 뽑는다. 섹션명만으로는 드러나지 않는 핵심 용어."""
    terms = []
    for line in body_lines:
        t = line.strip()
        if not t.startswith("|") or re.match(r"^\|\s*-", t):
            continue
        first = t.strip("|").split("|")[0].strip()
        if first and first not in terms and not re.match(r"^[\d,.~\-원%일]+$", first):
            terms.append(first)
    # 각 표의 머리글 행(구분, 항목, 등급 …)은 일반 단어라 뺀다
    generic = {"구분", "항목", "유형", "등급", "시행일", "미납 경과", "결합 회선 수", "보관 기간", "기간"}
    return [x for x in terms if x not in generic][:limit]


def doc_catalog():
    """'- 제목: 섹션1, 섹션2 (표 핵심어…)' 형태의 문서 목록 (제외 문서 빼고, 업로드 문서 포함)."""
    lines = []
    for d in iter_docs():
        if d["excluded"]:
            continue
        sections = [s for s, _ in split_sections(d["body_lines"]) if s != "개요"]
        line = f"- {d['title']}" + (f": {', '.join(dict.fromkeys(sections))}" if sections else "")
        extra = table_terms(d["body_lines"])
        lines.append(line + (f" ({', '.join(extra)})" if extra else ""))
    return "\n".join(lines)


def clean_terms(text):
    line = text.strip().split("\n")[0]
    line = re.sub(r"^(검색어\s*[:：])", "", line).strip()
    line = re.sub(r"[\"'`·,]", " ", line)
    terms = [t for t in line.split() if re.search(r"[가-힣A-Za-z0-9]", t)]
    return " ".join(dict.fromkeys(terms))[:80]


def rewrite_query(question, llm_call):
    """llm_call: messages → 문자열 (llm.make_llm(pid)). 실패하면 None (원래 질문만으로 검색)."""
    prompt = REWRITE_PROMPT.format(doc_list=doc_catalog(), question=question)
    try:
        terms = clean_terms(llm_call([{"role": "user", "content": prompt}]))
    except OSError:
        return None
    return terms or None


def fused_search(retriever, queries, k=5, depth=10, rrf_k=60):
    """여러 검색어의 결과 순위를 RRF로 합친다. 검색어가 하나면 그냥 검색."""
    queries = [q for q in queries if q]
    if len(queries) == 1:
        return retriever.search(queries[0], k=k)
    fused, by_id = {}, {}
    for q in queries:
        for rank, r in enumerate(retriever.search(q, k=depth), 1):
            fused[r["chunk_id"]] = fused.get(r["chunk_id"], 0) + 1 / (rrf_k + rank)
            by_id.setdefault(r["chunk_id"], r)
    top = sorted(fused, key=fused.get, reverse=True)[:k]
    return [{**by_id[cid], "score": round(fused[cid], 4)} for cid in top]


def suggestions(chunks, n=3):
    """못 찾았을 때 보여줄 추천: 검색 결과에서 서로 다른 문서 n개 → 그 섹션을 묻는 질문."""
    out, seen = [], set()
    for c in chunks:
        if c["doc_no"] in seen:
            continue
        seen.add(c["doc_no"])
        section = re.sub(r"\s*\(\d+/\d+\)$", "", c["section"])
        q = f"{c['title']} 알려줘" if section == "개요" else f"{c['title']}의 '{section}' 내용 알려줘"
        out.append({"doc_no": c["doc_no"], "title": c["title"], "section": section, "status": c["status"], "question": q})
        if len(out) == n:
            break
    return out


def main():
    import llm
    from retrieve import make_retriever

    question = " ".join(a for a in sys.argv[1:] if not a.startswith("--")) or "폰 잃어버렸는데 어떻게 해야 돼?"
    pid = llm.llm_arg(sys.argv[1:])
    retriever = make_retriever()
    terms = rewrite_query(question, llm.make_llm(pid))
    print(f"질문: {question}\n재작성 검색어 ({llm.describe(pid)['model']}): {terms}\n")
    before = [f"{r['chunk_id']} {r['title']}" for r in retriever.search(question, k=3)]
    after = [f"{r['chunk_id']} {r['title']}" for r in fused_search(retriever, [question, terms], k=3)]
    print("| 순위 | 원래 질문만 | 질문 + 재작성 검색어 |\n|---|---|---|")
    for i, (b, a) in enumerate(zip(before, after), 1):
        print(f"| {i} | {b} | {a} |")


if __name__ == "__main__":
    main()
