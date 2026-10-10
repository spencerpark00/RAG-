"""생성 엔진(LLM) 선택: 로컬 Ollama 또는 OpenAI 호환 API(Groq)

- 검색·프롬프트는 그대로 두고, '답을 쓰는 모델'만 바꿔 끼우는 계층.
- Groq는 OpenAI 호환 API라서 주소·모델명만 바꾸면 다른 호환 서비스(OpenRouter, Gemini 호환 엔드포인트 등)도 같은 코드로 쓸 수 있다.
- API 키는 코드에 넣지 않는다: 환경 변수 GROQ_API_KEY 또는 프로젝트 폴더의 .env 파일(git 제외)에서 읽는다.

.env 예시 (.env.example 참고)
  GROQ_API_KEY=gsk_...
  GROQ_MODEL=openai/gpt-oss-120b
"""
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from answer import MODEL as OLLAMA_MODEL, call_ollama, fix_punct, stream_ollama

ROOT = Path(__file__).parent


def load_env(path=ROOT / ".env"):
    """KEY=VALUE 줄만 읽는 최소 .env 로더 (이미 설정된 환경 변수가 우선)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()

PROVIDERS = {
    "ollama": {"label": "로컬", "kind": "ollama", "model": OLLAMA_MODEL},
    "groq": {
        "label": "Groq",
        "kind": "openai",
        "base": os.environ.get("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
        "model": os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
        "key_env": "GROQ_API_KEY",
    },
}
DEFAULT_LLM = "ollama"


def _ssl_context():
    """HTTPS 인증서 확인용. python.org 설치판 macOS Python은 기본 인증서 목록이 비어 있어
    CERTIFICATE_VERIFY_FAILED가 나므로, certifi(Mozilla 인증서 묶음)가 있으면 함께 쓴다."""
    ctx = ssl.create_default_context()
    try:
        import certifi
        ctx.load_verify_locations(certifi.where())
    except ImportError:
        pass
    return ctx


SSL_CONTEXT = _ssl_context()


class LLMError(OSError):
    """모델 호출 실패 (OSError 하위라서 기존 '연결 실패' 처리에 그대로 걸린다)."""


def available():
    return [pid for pid, p in PROVIDERS.items() if p["kind"] == "ollama" or os.environ.get(p.get("key_env", ""))]


def describe(pid):
    p = PROVIDERS[pid]
    return {"id": pid, "label": p["label"], "model": p["model"]}


def _open(p, messages, stream, retries=3):
    body = {"model": p["model"], "messages": messages, "temperature": 0, "stream": stream}
    req = urllib.request.Request(
        f"{p['base']}/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ.get(p['key_env'], '')}",
            "User-Agent": "hanbit-rag/0.1",
        },
    )
    for attempt in range(retries + 1):
        try:
            return urllib.request.urlopen(req, timeout=120, context=SSL_CONTEXT)
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:300]
            if e.code == 429 and attempt < retries:
                # 무료 한도(분당 요청·토큰) 초과: 서버가 알려준 만큼 기다렸다 다시 시도
                wait = min(float(e.headers.get("retry-after") or 10), 60)
                print(f"[{p['label']}] 사용량 한도 도달, {wait:.0f}초 후 재시도", file=sys.stderr)
                time.sleep(wait)
                continue
            if e.code == 401:
                raise LLMError(f"{p['label']} API 키가 올바르지 않습니다 (401). .env의 {p['key_env']}를 확인하세요.") from e
            if e.code == 429:
                raise LLMError(f"{p['label']} 무료 사용량 한도를 넘었습니다 (429). 잠시 후 다시 시도하세요.") from e
            raise LLMError(f"{p['label']} 호출 실패 (HTTP {e.code}): {detail}") from e
        except urllib.error.URLError as e:
            hint = " → 'pip install -r requirements.txt'로 certifi를 설치한 뒤 서버를 다시 켜세요." if "CERTIFICATE_VERIFY_FAILED" in str(e.reason) else ""
            raise LLMError(f"{p['label']} 서버에 연결할 수 없습니다: {e.reason}{hint}") from e


THINK = re.compile(r"<think>.*?</think>\s*", re.S)  # 추론 과정을 본문에 섞어 내는 모델(qwen3 등) 대비


def call(messages, pid=DEFAULT_LLM):
    p = PROVIDERS[pid]
    if p["kind"] == "ollama":
        return call_ollama(messages)
    with _open(p, messages, stream=False) as resp:
        text = json.loads(resp.read())["choices"][0]["message"].get("content") or ""
    return fix_punct(THINK.sub("", text)).strip()


def stream(messages, pid=DEFAULT_LLM):
    """답 조각(str)을 생성되는 대로 yield. OpenAI 호환 SSE: 'data: {...}' 줄, 끝은 'data: [DONE]'."""
    p = PROVIDERS[pid]
    if p["kind"] == "ollama":
        yield from stream_ollama(messages)
        return
    in_think = False
    with _open(p, messages, stream=True) as resp:
        for raw in resp:
            line = raw.decode("utf-8").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            piece = (json.loads(data)["choices"] or [{}])[0].get("delta", {}).get("content") or ""
            # <think> … </think> 구간은 화면에 흘리지 않는다
            if "<think>" in piece:
                in_think, piece = True, piece.split("<think>")[0]
            if in_think:
                if "</think>" in piece:
                    in_think, piece = False, piece.split("</think>", 1)[1]
                else:
                    continue
            if piece:
                yield fix_punct(piece)


def make_llm(pid):
    """answer()에 넘길 'messages → 답 문자열' 함수."""
    return lambda messages: call(messages, pid)


def llm_arg(argv):
    """명령줄 --llm=groq 값을 꺼낸다 (없으면 기본값)."""
    pid = next((a.split("=", 1)[1] for a in argv if a.startswith("--llm=")), DEFAULT_LLM)
    if pid not in PROVIDERS:
        sys.exit(f"--llm은 {tuple(PROVIDERS)} 중 하나")
    if pid not in available():
        sys.exit(f"{PROVIDERS[pid]['label']} API 키가 없습니다. .env 파일에 {PROVIDERS[pid]['key_env']}=... 를 넣으세요.")
    return pid
