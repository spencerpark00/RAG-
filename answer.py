"""3단계: 근거 기반 답변 생성 (Ollama HTTP API, 표준 라이브러리만 사용)

흐름: 질문 → 검색(하이브리드/BM25) 상위 k개 청크 → 프롬프트 → qwen2.5:3b → 언어 검사(→ 1회 재작성)

실행
  python answer.py "질문"           # Ollama 호출 (맥에서)
  python answer.py "질문" --fake    # Ollama 없이 파이프라인만 점검
  python answer.py "질문" --prompt=v2b   # 프롬프트 버전 선택 (v1, v2a~v2d)
"""
import json
import re
import sys
import urllib.request

from retrieve import make_retriever, retriever_arg

OLLAMA_URL = "http://localhost:11434/api/chat"
MODEL = "qwen2.5:3b"
TOP_K = 5
NO_ANSWER = "제공된 문서에서 확인할 수 없습니다."

ROLE = "당신은 한빛텔레콤 고객센터 상담사를 돕는 업무지식 검색 도우미입니다."

# v1: 규칙 전체를 시스템 메시지에, 자료·질문은 사용자 메시지에 (맥 1차 실행: 답 있는 25문항 중 16개 거부)
SYSTEM_PROMPT = f"""{ROLE}
규칙:
1. 아래 [자료]에 적힌 내용만으로 답합니다. 자료에 없는 내용을 추측하거나 지어내지 않습니다.
2. 질문에 대한 답이 자료에 없으면 "{NO_ANSWER}"라고만 답합니다.
   일부만 있으면 있는 부분만 답하고, 없는 부분은 "{NO_ANSWER}"라고 밝힙니다.
3. 자료 머리말에 '폐지'라고 표시된 문서와 '개정 이력' 표의 이전 값은, 질문이 그 과거 시기를 물을 때만 사용합니다. 그 외에는 '현행' 값으로 답합니다.
4. 반드시 한국어로만 답합니다. 한자, 중국어, 영어 문장을 쓰지 않습니다. (GB, Mbps 같은 단위와 자료에 나온 고유명사는 그대로 씁니다.)
5. 2~3문장으로 간결하게 답하고, 마지막 줄에 사용한 자료 번호를 "(근거: 07-0, 07-2)"처럼 적습니다."""

# v2a: v1과 같은 규칙을 자료 '뒤'로 옮기고 질문을 맨 끝에 둔다
RULES_V2A = SYSTEM_PROMPT.split("규칙:\n", 1)[1]

# v2b: 거부 조건을 '관련 내용이 전혀 없을 때만'으로 좁히고 거부 문장은 한 번만 언급
RULES_V2B = f"""1. 자료에 질문과 관련된 내용이 있으면 반드시 그 내용으로 답합니다. 자료에 없는 내용은 지어내지 않습니다.
2. 자료 어디에도 관련 내용이 없을 때만 "{NO_ANSWER}"라고 답합니다. 일부만 있으면 있는 부분은 답하고, 없는 부분만 확인할 수 없다고 말합니다.
3. 머리말에 '폐지'로 표시된 문서와 '개정 이력' 표의 이전 값은, 질문이 그 과거 시기를 물을 때만 씁니다. 그 외에는 현행 값으로 답합니다.
4. 반드시 한국어로만 답합니다. 단위(GB, Mbps)와 자료에 나온 고유명사는 그대로 씁니다."""

# v2c: 근거 문장을 먼저 옮겨 적게 한 뒤 답하게 한다
FORMAT_V2C = """답변 형식 (두 줄):
근거: <자료에서 질문에 답하는 문장을 그대로 옮겨 적고, 끝에 자료 번호를 (02-0)처럼 붙임. 관련 문장이 없으면 '없음'>
답: <근거를 바탕으로 한두 문장>"""

# v2d: 말뭉치에 없는 가상 사례로 예시 2개 (답 있음 1, 답 없음 1)
EXAMPLES_V2D = f"""예시 1)
자료: <99-0> [문서 99 · 미표기] 데이터 쿠폰 > 사용 기준 - 쿠폰 1장당 1GB, 발급일로부터 30일 이내 사용
질문: 데이터 쿠폰 유효기간은?
근거: 발급일로부터 30일 이내 사용 (99-0)
답: 데이터 쿠폰은 발급일로부터 30일 이내에 사용해야 합니다.

예시 2)
자료: <99-0> [문서 99 · 미표기] 데이터 쿠폰 > 사용 기준 - 쿠폰 1장당 1GB, 발급일로부터 30일 이내 사용
질문: 데이터 쿠폰을 다른 사람에게 선물할 수 있나요?
근거: 없음
답: {NO_ANSWER}"""

PROMPT_VERSIONS = ("v1", "v2a", "v2b", "v2c", "v2d")
DEFAULT_PROMPT = "v2a"  # 실험 결과: experiments/prompt_v2.md

# 단위·고유명사처럼 영문이어도 허용하는 토큰 (소문자)
ALLOWED_LATIN = {"gb", "mb", "mbps", "kbps", "g", "p"}


def build_messages(question, chunks, version=DEFAULT_PROMPT):
    context = "\n\n".join(f"<{c['chunk_id']}>\n{c['text']}" for c in chunks)
    if version == "v1":
        user = f"[자료]\n{context}\n\n[질문]\n{question}"
        return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]
    rules = RULES_V2A if version == "v2a" else RULES_V2B
    parts = [f"[자료]\n{context}", f"[규칙]\n{rules}"]
    if version in ("v2c", "v2d"):
        parts.append(FORMAT_V2C)
    if version == "v2d":
        parts.append(EXAMPLES_V2D)
    parts.append(f"[질문]\n{question}")
    return [{"role": "system", "content": ROLE}, {"role": "user", "content": "\n\n".join(parts)}]


def final_answer(text):
    """'근거: ... / 답: ...' 형식이면 '답:' 뒤만, 아니면 전체. 채점은 이 부분으로 한다."""
    m = re.search(r"답\s*[:：]\s*(.*)", text, re.S)
    return m.group(1).strip() if m else text


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


# 3b 모델이 자주 쓰는 중국어식 문장부호 → 한국어 문장부호 (내용은 바꾸지 않음).
# 재작성 요청으로는 고쳐지지 않아서(실험에서 3건 모두 그대로) 후처리로 바꾼다.
PUNCT_MAP = str.maketrans({"。": ".", "，": ",", "、": ",", "：": ":", "；": ";", "（": "(", "）": ")"})


def fix_punct(text):
    return text.translate(PUNCT_MAP)


def language_issues(answer, allowed_text):
    """한국어 외 문자 검출: 한자·일본어 가나, 그리고 자료·질문에 없는 영단어."""
    # 한자(U+3400~, U+4E00~), 가나(U+3040~30FF), 중국어식 문장부호(。、「」 U+3001~303F, 전각 ，：)
    issues = re.findall("[㐀-䶿一-鿿぀-ヿ、-〿，：]+", answer)
    allowed = {w.lower() for w in re.findall(r"[A-Za-z]+", allowed_text)} | ALLOWED_LATIN
    issues += [w for w in re.findall(r"[A-Za-z]+", answer) if w.lower() not in allowed]
    return issues


def answer(question, retriever, llm=call_ollama, k=TOP_K, version=DEFAULT_PROMPT):
    chunks = retriever.search(question, k=k)
    messages = build_messages(question, chunks, version)
    text = fix_punct(llm(messages))
    issues = language_issues(text, messages[1]["content"])
    retried = False
    if issues:
        # temperature 0이라 같은 프롬프트로 재시도하면 같은 답이 나온다 → 재작성 지시를 덧붙인다
        retried = True
        messages += [
            {"role": "assistant", "content": text},
            {"role": "user", "content": f"위 답변에 한국어가 아닌 표현({', '.join(issues[:5])})이 있습니다. 같은 내용을 한국어로만 다시 써 주세요."},
        ]
        text = fix_punct(llm(messages))
        issues = language_issues(text, messages[1]["content"])
    return {
        "answer": text,
        "final": final_answer(text),
        "chunks": chunks,
        "language_issues": issues,
        "retried": retried,
    }


def main():
    version = next((a.split("=", 1)[1] for a in sys.argv[1:] if a.startswith("--prompt=")), DEFAULT_PROMPT)
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    llm = fake_llm if "--fake" in sys.argv else call_ollama
    question = " ".join(args) or "5G 스탠다드 요금제 월정액은 얼마인가요?"
    result = answer(question, make_retriever(retriever_arg(sys.argv[1:])), llm=llm, version=version)
    print(f"질문: {question}")
    print(f"검색: {', '.join(c['chunk_id'] for c in result['chunks'])}")
    print(f"\n{result['answer']}")
    if result["retried"] or result["language_issues"]:
        print(f"\n[언어 검사] 재작성={result['retried']} 남은 문제={result['language_issues']}")


if __name__ == "__main__":
    main()
