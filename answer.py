"""3단계: 근거 기반 답변 생성 (Ollama HTTP API, 표준 라이브러리만 사용)

흐름: 질문 → BM25 상위 k개 청크 → 프롬프트 → qwen2.5:3b → 언어 검사(→ 1회 재작성)

실행
  python answer.py "질문"           # Ollama 호출 (맥에서)
  python answer.py "질문" --fake    # Ollama 없이 파이프라인만 점검
"""
import json
import re
import sys
import urllib.request

from retrieve import BM25, load_chunks

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5:3b"
TOP_K = 5
NO_ANSWER = "제공된 문서에서 확인할 수 없습니다."

SYSTEM_PROMPT = f"""당신은 한빛텔레콤 고객센터 상담사를 돕는 업무지식 검색 도우미입니다.
규칙:
1. 아래 [자료]에 적힌 내용만으로 답합니다. 자료에 없는 내용을 추측하거나 지어내지 않습니다.
2. 질문에 대한 답이 자료에 없으면 "{NO_ANSWER}"라고만 답합니다.
   일부만 있으면 있는 부분만 답하고, 없는 부분은 "{NO_ANSWER}"라고 밝힙니다.
3. 자료 머리말에 '폐지'라고 표시된 문서와 '개정 이력' 표의 이전 값은, 질문이 그 과거 시기를 물을 때만 사용합니다. 그 외에는 '현행' 값으로 답합니다.
4. 반드시 한국어로만 답합니다. 한자, 중국어, 영어 문장을 쓰지 않습니다. (GB, Mbps 같은 단위와 자료에 나온 고유명사는 그대로 씁니다.)
5. 2~3문장으로 간결하게 답하고, 마지막 줄에 사용한 자료 번호를 "(근거: 07-0, 07-2)"처럼 적습니다."""

# 단위·고유명사처럼 영문이어도 허용하는 토큰 (소문자)
ALLOWED_LATIN = {"gb", "mb", "mbps", "kbps", "g", "p"}


def build_messages(question, chunks):
    context = "\n\n".join(f"<{c['chunk_id']}>\n{c['text']}" for c in chunks)
    user = f"[자료]\n{context}\n\n[질문]\n{question}"
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]


def call_ollama(messages, model=MODEL, timeout=600):
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {"temperature": 0, "num_ctx": 4096},
    }
    req = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())["message"]["content"].strip()


def fake_llm(messages):
    """Ollama 없이 흐름만 점검하는 가짜 모델: 첫 번째 자료의 본문 첫 줄을 그대로 돌려준다."""
    user = messages[1]["content"]
    first = re.search(r"<(\d\d-\d+)>\n[^\n]*\n([^\n]*)", user)
    return f"{first.group(2).lstrip('- ')}\n(근거: {first.group(1)})" if first else NO_ANSWER


def language_issues(answer, allowed_text):
    """한국어 외 문자 검출: 한자·일본어 가나, 그리고 자료·질문에 없는 영단어."""
    issues = re.findall(r"[㐀-䶿一-鿿぀-ヿ]+", answer)
    allowed = {w.lower() for w in re.findall(r"[A-Za-z]+", allowed_text)} | ALLOWED_LATIN
    issues += [w for w in re.findall(r"[A-Za-z]+", answer) if w.lower() not in allowed]
    return issues


def answer(question, bm25, llm=call_ollama, k=TOP_K):
    chunks = bm25.search(question, k=k)
    messages = build_messages(question, chunks)
    text = llm(messages)
    issues = language_issues(text, messages[1]["content"])
    retried = False
    if issues:
        # temperature 0이라 같은 프롬프트로 재시도하면 같은 답이 나온다 → 재작성 지시를 덧붙인다
        retried = True
        messages += [
            {"role": "assistant", "content": text},
            {"role": "user", "content": f"위 답변에 한국어가 아닌 표현({', '.join(issues[:5])})이 있습니다. 같은 내용을 한국어로만 다시 써 주세요."},
        ]
        text = llm(messages)
        issues = language_issues(text, messages[1]["content"])
    return {
        "answer": text,
        "chunks": chunks,
        "language_issues": issues,
        "retried": retried,
    }


def main():
    args = [a for a in sys.argv[1:] if a != "--fake"]
    llm = fake_llm if "--fake" in sys.argv else call_ollama
    question = " ".join(args) or "5G 스탠다드 요금제 월정액은 얼마인가요?"
    result = answer(question, BM25(load_chunks()), llm=llm)
    print(f"질문: {question}")
    print(f"검색: {', '.join(c['chunk_id'] for c in result['chunks'])}")
    print(f"\n{result['answer']}")
    if result["retried"] or result["language_issues"]:
        print(f"\n[언어 검사] 재작성={result['retried']} 남은 문제={result['language_issues']}")


if __name__ == "__main__":
    main()
