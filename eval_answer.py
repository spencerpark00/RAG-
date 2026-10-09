"""답변 평가: 검색 적중과 답변 정확성을 분리해 채점

판정 (자동, 키워드 기반)
- 정답: 필수 키워드가 모두 있고, 거부 문구·오답 키워드가 없음
- 오답: 필수 키워드 누락 / 답이 있는 질문에 거부 / 답없음 질문에 거부 안 함
- 검수: 필수 키워드는 있지만 거부 문구나 오답 키워드(구 규정 값)가 섞임 → 사람이 확인
비교 시 공백과 쉼표를 지운다 ('69,000 원' == '69000원').

실행
  python eval_answer.py                # 30문항 전체 (맥, Ollama 필요. i3 기준 수십 분 예상)
  python eval_answer.py Q08 Q14        # 일부만
  python eval_answer.py --fake         # Ollama 없이 흐름 점검
결과: answer_results.jsonl (전체 답변 원문 포함, 검수용)
"""
import json
import sys
import time
from collections import Counter
from pathlib import Path

from answer import NO_ANSWER, answer, call_ollama, fake_llm
from eval_retrieval import load_questions
from retrieve import BM25, load_chunks

OUT_PATH = Path(__file__).parent / "answer_results.jsonl"
REFUSAL = "확인할수없"  # 정규화 후 비교

# 정답 핵심(eval_questions.csv)을 채점 가능한 키워드로 옮긴 것
# must: 모두 포함해야 함 / must_not: 포함되면 '검수' (구 규정·구 요금 값)
GRADING = {
    "Q01": {"must": ["69,000"]},
    "Q02": {"must": ["400kbps"]},
    "Q03": {"must": ["66,750"]},
    "Q04": {"must": ["40GB"]},
    "Q05": {"must": ["12세", "18세", "법정대리인"]},
    "Q06": {"must": ["25%", "12개월", "24개월"]},
    "Q07": {"must": ["17,250"]},
    "Q08": {"must": ["72,450"]},  # 계산 과정에 103,500이 나올 수 있어 must_not으로 두지 않음
    "Q09": {"must": ["100%"]},
    "Q10": {"must": ["당일", "24시"]},
    "Q11": {"must": ["114", "대리점", "한빛 마이"]},
    "Q12": {"must": ["무료", "당일"]},
    "Q13": {"must": ["3개월"]},
    "Q14": {"must": ["11,000", "2GB", "3Mbps"], "must_not": ["9,900", "1GB"]},
    "Q15": {"must": ["8,800"]},
    "Q16": {"must": ["33,000"]},
    "Q17": {"must": ["60분"]},
    "Q18": {"must": ["3시간"]},
    "Q19": {"must": ["1년", "7일"]},
    "Q20": {"must": ["이용정지"]},
    "Q21": {"must": ["성명", "생년월일", "휴대폰 번호"]},
    "Q22": {"must": ["3회"]},
    "Q23": {"must": ["1년", "3년", "2%"]},
    "Q24": {"must": ["16,500"]},
    "Q25": {"must": ["800원", "70%"]},
}


def norm(s):
    return s.replace(" ", "").replace(",", "").lower()


def grade(qid, qtype, text):
    t = norm(text)
    refused = REFUSAL in t
    if qtype == "답없음":
        return ("정답", "") if refused else ("오답", "거부 안 함")
    rule = GRADING[qid]
    missing = [kw for kw in rule["must"] if norm(kw) not in t]
    bad = [kw for kw in rule.get("must_not", []) if norm(kw) in t]
    if missing:
        return "오답", ("거부함 " if refused else "") + f"누락: {', '.join(missing)}"
    if refused or bad:
        return "검수", ("거부 문구 섞임 " if refused else "") + (f"구 값: {', '.join(bad)}" if bad else "")
    return "정답", ""


def main():
    use_fake = "--fake" in sys.argv
    ids = [a for a in sys.argv[1:] if a.startswith("Q")]
    llm = fake_llm if use_fake else call_ollama
    bm25 = BM25(load_chunks())
    questions = [q for q in load_questions() if not ids or q["id"] in ids]

    rows = []
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for q in questions:
            start = time.time()
            r = answer(q["질문"], bm25, llm=llm)
            secs = time.time() - start
            gold = [d.strip() for d in q["근거문서번호"].split(",") if d.strip() != "-"]
            got = [c["doc_no"] for c in r["chunks"]]
            hit = "-" if not gold else ("O" if all(d in got for d in gold) else "△" if any(d in got for d in gold) else "X")
            verdict, note = grade(q["id"], q["유형"], r["answer"])
            row = {
                "id": q["id"], "유형": q["유형"], "질문": q["질문"], "정답 핵심": q["정답 핵심"],
                "검색": hit, "판정": verdict, "메모": note,
                "언어": "재작성" if r["retried"] else "", "남은 언어 문제": r["language_issues"],
                "답변": r["answer"], "검색 청크": [c["chunk_id"] for c in r["chunks"]], "초": round(secs, 1),
            }
            rows.append(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"{q['id']} {verdict} ({secs:.0f}초)", file=sys.stderr)

    if use_fake:
        print("※ --fake 모드: 가짜 모델 결과라 점수에 의미 없음. 흐름 점검용.\n")

    n = len(rows)
    count = Counter(r["판정"] for r in rows)
    print(f"## 요약 ({n}문항)\n")
    print("| 판정 | 문항 수 |\n|---|---|")
    for v in ("정답", "검수", "오답"):
        print(f"| {v} | {count[v]} |")
    print(f"| 언어 재작성 발생 | {sum(1 for r in rows if r['언어'])} |")
    print(f"| 재작성 후에도 언어 문제 | {sum(1 for r in rows if r['남은 언어 문제'])} |")

    # 검색 적중 × 답변 판정 교차표: 오답의 원인이 검색인지 생성인지 분리
    print("\n## 검색 × 답변 교차표\n")
    print("| 검색 \\ 답변 | 정답 | 검수 | 오답 |\n|---|---|---|---|")
    for h, label in (("O", "근거 전부 검색"), ("△", "일부만 검색"), ("X", "검색 실패"), ("-", "근거 없음(답없음)")):
        c = Counter(r["판정"] for r in rows if r["검색"] == h)
        if c:
            print(f"| {label} | {c['정답']} | {c['검수']} | {c['오답']} |")

    print("\n## 문항별\n")
    print("| id | 유형 | 검색 | 판정 | 메모 | 언어 | 초 |\n|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['id']} | {r['유형']} | {r['검색']} | {r['판정']} | {r['메모']} | {r['언어']} | {r['초']} |")
    print(f"\n답변 원문: {OUT_PATH.name}")


if __name__ == "__main__":
    main()
