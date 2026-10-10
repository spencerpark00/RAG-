// 대화 상태 타입과 브라우저 저장(localStorage). 서버 DB 없이 이 브라우저에만 남는다.
import type { Chunk, Retriever } from "./api";

export interface Turn {
  id: string;
  question: string;
  retriever: Retriever;
  llm?: string; // 답을 쓴 모델 이름 (예: openai/gpt-oss-120b)
  answer: string;
  chunks: Chunk[];
  cited: string[];
  refused: boolean;
  seconds?: number;
  searchMs?: number;
  notice?: string; // 검색 대체 등 안내
  stage: "searching" | "writing" | "done" | "error" | "stopped";
  error?: string;
  rating?: "up" | "down";
}

export interface Conversation {
  id: string;
  title: string;
  turns: Turn[];
  updatedAt: number;
}

const KEY = "hanbit-conversations-v1";

export const newId = () => Math.random().toString(36).slice(2, 10);

export function loadConversations(): Conversation[] {
  try {
    const raw = localStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Conversation[]) : [];
  } catch {
    return [];
  }
}

export function saveConversations(list: Conversation[]) {
  try {
    // 진행 중이던 답변은 저장하지 않는다(새로고침 시 '중단됨'으로 보이도록)
    const clean = list.map((c) => ({
      ...c,
      turns: c.turns.map((t) => (t.stage === "searching" || t.stage === "writing" ? { ...t, stage: "stopped" as const } : t)),
    }));
    localStorage.setItem(KEY, JSON.stringify(clean.slice(0, 30)));
  } catch {
    /* 저장 실패(사생활 보호 모드 등)는 무시: 화면 동작에는 영향 없음 */
  }
}

/** 답변 끝의 '(근거: 02-0, 12-1)' 표기를 지운다. 근거는 칩으로 따로 보여준다. */
export const stripCitation = (s: string) => s.replace(/\s*\(근거:[^)]*\)/g, "").trim();
