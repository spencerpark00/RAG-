"""4단계: 터미널 챗봇 (검색 → 근거 기반 답변 → 근거 표시)

실행
  python chat.py          # Ollama 필요
  python chat.py --fake   # Ollama 없이 흐름만 점검

명령: /근거 (직전 답변의 근거 원문), /종료
매 질문은 독립적으로 처리한다 (이전 대화를 모델에 넣지 않음).
"""
import sys
import time
import urllib.error

from answer import answer, call_ollama, fake_llm
from retrieve import BM25, load_chunks


def cited_chunks(result):
    """답변에 '(근거: 02-0, 12-1)'로 적힌 청크만 고른다. 표기가 없으면 검색 상위 3개."""
    text = result["answer"]
    cited = [c for c in result["chunks"] if c["chunk_id"] in text]
    return cited or result["chunks"][:3]


def main():
    llm = fake_llm if "--fake" in sys.argv else call_ollama
    bm25 = BM25(load_chunks())
    last = None
    print("한빛텔레콤 업무지식 검색 챗봇입니다. 질문을 입력하세요. (/근거, /종료)")

    while True:
        try:
            question = input("\n질문> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question in ("/종료", "/q", "exit"):
            break
        if question == "/근거":
            if not last:
                print("아직 답변이 없습니다.")
                continue
            for c in cited_chunks(last):
                print(f"\n<{c['chunk_id']}>\n{c['text']}")
            continue

        start = time.time()
        try:
            last = answer(question, bm25, llm=llm)
        except urllib.error.URLError:
            print("Ollama 서버에 연결할 수 없습니다. 'open -a Ollama' 또는 'ollama serve'로 서버를 켜 주세요.")
            continue
        print(f"\n{last['final']}")
        if "확인할수없" in last["final"].replace(" ", ""):
            print(f"\n(검색된 문서에서 근거를 찾지 못함, {time.time() - start:.0f}초)")
            continue
        print(f"\n참고 문서 ({time.time() - start:.0f}초):")
        for c in cited_chunks(last):
            print(f"  - {c['chunk_id']} [{c['status']}] {c['title']} > {c['section']}")


if __name__ == "__main__":
    main()
