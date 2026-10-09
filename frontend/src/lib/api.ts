// FastAPI(server.py)와 통신하는 계층. 화면 컴포넌트는 이 파일의 함수만 쓴다.

export type Retriever = "bm25" | "vector" | "hybrid";

export interface Chunk {
  chunk_id: string;
  doc_no: string;
  doc_id: string;
  title: string;
  section: string;
  status: string; // 현행 | 폐지 | 미표기
  effective: string;
  text: string;
  score: number;
}

export interface Health {
  ollama: { ok: boolean; models?: string[]; error?: string };
  llm: string;
  retrievers: Retriever[];
  default_retriever: Retriever;
  chunks: number;
}

export interface DoneEvent {
  answer: string;
  cited: string[];
  refused: boolean;
  seconds: number;
}

export interface StreamHandlers {
  onSources: (d: { retriever: Retriever; chunks: Chunk[]; search_ms: number }) => void;
  onToken: (text: string) => void;
  onDone: (d: DoneEvent) => void;
  onError: (message: string) => void;
}

export const RETRIEVER_LABEL: Record<Retriever, string> = {
  hybrid: "하이브리드",
  bm25: "키워드",
  vector: "의미",
};

export async function getHealth(): Promise<Health> {
  const res = await fetch("/api/health");
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

/** POST /api/chat 의 SSE 스트림을 읽어 이벤트별 콜백을 부른다. */
export async function streamChat(question: string, retriever: Retriever, h: StreamHandlers, signal: AbortSignal) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, retriever }),
    signal,
  });
  if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    // SSE 한 건은 빈 줄(\n\n)로 끝난다: "event: 이름\ndata: JSON\n\n"
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const raw = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      const event = raw.match(/^event: (.*)$/m)?.[1];
      const data = JSON.parse(raw.match(/^data: (.*)$/m)?.[1] ?? "{}");
      if (event === "sources") h.onSources(data);
      else if (event === "token") h.onToken(data.text);
      else if (event === "done") h.onDone(data);
      else if (event === "error") h.onError(data.message);
    }
  }
}

export function sendFeedback(body: { question: string; answer: string; rating: "up" | "down"; retriever: Retriever }) {
  return fetch("/api/feedback", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
