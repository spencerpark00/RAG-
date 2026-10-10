// 화면 전체 상태와 레이아웃: [사이드바 | 대화 | 근거 패널]
import { ArrowUp, FileText, Menu, Moon, Square, Sun } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { DocsPage } from "./components/DocsPage";
import { Message } from "./components/Message";
import { Sidebar } from "./components/Sidebar";
import { SourcesPanel } from "./components/SourcesPanel";
import { Button, Logo, cx } from "./components/ui";
import { RETRIEVER_LABEL, getHealth, sendFeedback, streamChat } from "./lib/api";
import type { Health, Retriever } from "./lib/api";
import type { Conversation, Turn } from "./lib/store";
import { loadConversations, newId, saveConversations } from "./lib/store";

const EXAMPLES = [
  ["요금제", "5G 스탠다드 요금제 월정액은 얼마인가요?"],
  ["약정", "선택약정 할인율과 약정 기간 선택지는?"],
  ["로밍", "현재 하루 로밍 패스 요금과 제공 데이터는?"],
  ["장애", "장애 보상 대상이 되려면 몇 시간 이상 끊겨야 하나요?"],
];

const emptyConversation = (): Conversation => ({ id: newId(), title: "새 대화", turns: [], updatedAt: Date.now() });

export default function App() {
  const [conversations, setConversations] = useState<Conversation[]>(() => {
    const saved = loadConversations();
    return saved.length ? saved : [emptyConversation()];
  });
  const [activeId, setActiveId] = useState(() => conversations[0].id);
  const [selectedTurnId, setSelectedTurnId] = useState<string>();
  const [focusChunk, setFocusChunk] = useState<string>();
  const [health, setHealth] = useState<Health>();
  const [healthError, setHealthError] = useState(false);
  const [retriever, setRetriever] = useState<Retriever>("hybrid");
  const [llm, setLlm] = useState("ollama");
  const [input, setInput] = useState("");
  const [dark, setDark] = useState(() => document.documentElement.classList.contains("dark"));
  const [showSidebar, setShowSidebar] = useState(false);
  const [showSources, setShowSources] = useState(false);
  // 화면 전환: 주소 끝 #/docs 이면 문서 관리 (새로고침해도 유지)
  const [view, setView] = useState<"chat" | "docs">(() => (location.hash === "#/docs" ? "docs" : "chat"));
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const conv = conversations.find((c) => c.id === activeId) ?? conversations[0];
  const selectedTurn = conv.turns.find((t) => t.id === selectedTurnId) ?? conv.turns[conv.turns.length - 1];
  const busy = conv.turns.some((t) => t.stage === "searching" || t.stage === "writing");

  const loadHealth = () =>
    getHealth()
      .then((h) => { setHealth(h); setHealthError(false); setRetriever((r) => (h.retrievers.includes(r) ? r : h.default_retriever)); setLlm((l) => (h.llms.some((x) => x.id === l) ? l : h.default_llm)); })
      .catch(() => setHealthError(true));
  useEffect(() => { loadHealth(); }, []);
  useEffect(() => {
    history.replaceState(null, "", view === "docs" ? "#/docs" : "#/");
    setShowSidebar(false);
  }, [view]);
  useEffect(() => saveConversations(conversations), [conversations]);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch { /* 무시 */ }
  }, [dark]);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [conv.turns.length, conv.turns[conv.turns.length - 1]?.answer]);

  /** 특정 대화의 특정 턴을 갱신 */
  const patchTurn = (convId: string, turnId: string, patch: Partial<Turn>) =>
    setConversations((list) =>
      list.map((c) => c.id !== convId ? c : { ...c, updatedAt: Date.now(), turns: c.turns.map((t) => (t.id === turnId ? { ...t, ...patch } : t)) }),
    );

  async function ask(raw: string) {
    const question = raw.trim();
    if (!question || busy) return;
    const convId = conv.id;
    const turn: Turn = { id: newId(), question, retriever, answer: "", chunks: [], cited: [], refused: false, stage: "searching" };
    setConversations((list) =>
      list
        .map((c) => c.id !== convId ? c : { ...c, title: c.turns.length ? c.title : question.slice(0, 30), updatedAt: Date.now(), turns: [...c.turns, turn] })
        .sort((a, b) => b.updatedAt - a.updatedAt),
    );
    setSelectedTurnId(turn.id);
    setInput("");

    const controller = new AbortController();
    abortRef.current = controller;
    let text = "";
    try {
      await streamChat(question, retriever, llm, {
        onSources: (d) => patchTurn(convId, turn.id, { chunks: d.chunks, retriever: d.retriever, searchMs: d.search_ms, notice: d.notice ?? undefined, stage: "writing" }),
        onToken: (t) => { text += t; patchTurn(convId, turn.id, { answer: text }); },
        onDone: (d) => patchTurn(convId, turn.id, { answer: d.answer, cited: d.cited, refused: d.refused, seconds: d.seconds, llm: d.llm?.model, stage: "done" }),
        onError: (m) => patchTurn(convId, turn.id, { stage: "error", error: m }),
      }, controller.signal);
    } catch (e) {
      const stopped = (e as Error).name === "AbortError";
      patchTurn(convId, turn.id, stopped ? { stage: "stopped" } : { stage: "error", error: `서버 연결 실패: ${(e as Error).message}` });
    } finally {
      abortRef.current = null;
      inputRef.current?.focus();
    }
  }

  function newChat() {
    const fresh = emptyConversation();
    setConversations((list) => [fresh, ...list.filter((c) => c.turns.length > 0)]);
    setActiveId(fresh.id);
    setSelectedTurnId(undefined);
    setView("chat");
    setShowSidebar(false);
  }

  function deleteChat(id: string) {
    setConversations((list) => {
      const rest = list.filter((c) => c.id !== id);
      const next = rest.length ? rest : [emptyConversation()];
      if (id === activeId) setActiveId(next[0].id);
      return next;
    });
  }

  // 상태 점: 서버 연결 + (로컬 모델을 고른 경우) Ollama 연결
  const status = healthError ? false : !health ? undefined : llm !== "ollama" || health.ollama.ok;

  return (
    <div className="flex h-full">
      {/* 사이드바: 데스크톱 고정, 모바일은 서랍 */}
      <aside className={cx(
        "fixed inset-y-0 left-0 z-30 w-72 border-r border-line bg-surface transition-transform md:static md:translate-x-0",
        showSidebar ? "translate-x-0 shadow-xl" : "-translate-x-full",
      )}>
        <Sidebar
          conversations={conversations}
          activeId={conv.id}
          view={view}
          onView={setView}
          health={health}
          onNew={newChat}
          onSelect={(id) => { setActiveId(id); setSelectedTurnId(undefined); setShowSidebar(false); setView("chat"); }}
          onDelete={deleteChat}
          onClose={() => setShowSidebar(false)}
        />
      </aside>
      {(showSidebar || showSources) && (
        <div className="fixed inset-0 z-20 bg-black/30 lg:hidden" onClick={() => { setShowSidebar(false); setShowSources(false); }} />
      )}

      {view === "docs" ? (
        <main className="flex min-w-0 flex-1 flex-col">
          <header className="flex h-15 shrink-0 items-center gap-2 border-b border-line bg-surface px-4">
            <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setShowSidebar(true)} aria-label="메뉴"><Menu size={18} /></Button>
            <h1 className="min-w-0 flex-1 truncate text-[15px] font-semibold">문서 관리</h1>
            <Button variant="ghost" size="icon" onClick={() => setDark((d) => !d)} aria-label="테마 전환">{dark ? <Sun size={16} /> : <Moon size={16} />}</Button>
          </header>
          <div className="min-h-0 flex-1"><DocsPage onIndexed={loadHealth} /></div>
        </main>
      ) : (<>
      <main className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-15 shrink-0 items-center gap-2 border-b border-line bg-surface px-4">
          <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setShowSidebar(true)} aria-label="메뉴"><Menu size={18} /></Button>
          <h1 className="min-w-0 flex-1 truncate text-[15px] font-semibold"><span className="hidden sm:inline">{conv.title}</span></h1>
          {/* 생성 모델 선택: .env에 GROQ_API_KEY가 있으면 Groq가 목록에 나타난다 */}
          <label className="hidden h-8 items-center gap-1.5 rounded-lg border border-line bg-subtle pl-2.5 text-xs text-muted sm:inline-flex" title={healthError ? "서버 연결 안 됨" : health && !health.ollama.ok && llm === "ollama" ? "Ollama 연결 안 됨" : "생성 모델"}>
            <span className={cx("size-1.5 shrink-0 rounded-full", status === true && "bg-ok", status === false && "bg-bad", status === undefined && "bg-muted")} />
            <select value={llm} onChange={(e) => setLlm(e.target.value)} className="h-full cursor-pointer bg-transparent pr-2 font-medium text-ink outline-none">
              {(health?.llms ?? [{ id: "ollama", label: "로컬", model: "qwen2.5:3b" }]).map((m) => (
                <option key={m.id} value={m.id}>{m.label} · {m.model.replace(/^.*\//, "")}</option>
              ))}
            </select>
          </label>
          {/* 검색 방식 세그먼트 컨트롤 */}
          <div className="flex rounded-lg border border-line bg-subtle p-0.5 text-xs">
            {(health?.retrievers ?? ["bm25", "vector", "hybrid"] as Retriever[]).slice().reverse().map((m) => (
              <button
                key={m}
                onClick={() => setRetriever(m)}
                className={cx("cursor-pointer rounded-md px-2.5 py-1 font-medium transition-colors", retriever === m ? "bg-surface text-ink shadow-sm" : "text-muted hover:text-ink")}
              >
                {RETRIEVER_LABEL[m]}
              </button>
            ))}
          </div>
          <Button variant="ghost" size="icon" onClick={() => setDark((d) => !d)} aria-label="테마 전환">{dark ? <Sun size={16} /> : <Moon size={16} />}</Button>
          <Button variant="ghost" size="icon" className="lg:hidden" onClick={() => setShowSources(true)} aria-label="근거 문서"><FileText size={16} /></Button>
        </header>

        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl space-y-6 px-4 py-7 sm:px-6">
            {conv.turns.length === 0 ? (
              <div className="pt-[8vh] text-center">
                <div className="flex justify-center"><Logo size={46} /></div>
                <h2 className="mt-4 text-2xl font-bold tracking-tight">무엇을 찾아드릴까요?</h2>
                <p className="mt-1.5 text-muted">요금제·약정·해지·로밍 등 상담 규정을 문서 근거와 함께 답합니다.</p>
                <div className="mt-7 grid gap-2.5 text-left sm:grid-cols-2">
                  {EXAMPLES.map(([tag, q]) => (
                    <button key={q} onClick={() => ask(q)} className="cursor-pointer rounded-xl border border-line bg-surface p-3.5 text-left text-sm transition hover:-translate-y-px hover:border-brand">
                      <span className="block text-xs font-semibold text-brand">{tag}</span>{q}
                    </button>
                  ))}
                </div>
              </div>
            ) : (
              conv.turns.map((t) => (
                <Message
                  key={t.id}
                  turn={t}
                  active={t.id === selectedTurn?.id}
                  onSelect={() => setSelectedTurnId(t.id)}
                  onCite={(id) => { setFocusChunk(undefined); setTimeout(() => setFocusChunk(id)); setShowSources(true); }}
                  onRate={(r) => {
                    patchTurn(conv.id, t.id, { rating: r });
                    sendFeedback({ question: t.question, answer: t.answer, rating: r, retriever: t.retriever }).catch(() => {});
                  }}
                  onRetry={() => ask(t.question)}
                />
              ))
            )}
          </div>
        </div>

        <div className="shrink-0 px-4 pb-4 pt-2 sm:px-6">
          <div className="mx-auto flex max-w-3xl items-end gap-2 rounded-2xl border border-line bg-surface p-2 pl-4 shadow-sm focus-within:border-brand">
            <textarea
              ref={inputRef}
              rows={1}
              value={input}
              onChange={(e) => {
                setInput(e.target.value);
                e.target.style.height = "auto";
                e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); ask(input); }
              }}
              placeholder="질문을 입력하세요"
              className="max-h-40 flex-1 resize-none bg-transparent py-2 outline-none placeholder:text-muted"
            />
            {busy ? (
              <Button variant="outline" size="icon" onClick={() => abortRef.current?.abort()} aria-label="중단"><Square size={14} /></Button>
            ) : (
              <Button variant="primary" size="icon" disabled={!input.trim()} onClick={() => ask(input)} aria-label="전송"><ArrowUp size={18} /></Button>
            )}
          </div>
          <p className="mx-auto mt-1.5 max-w-3xl text-center text-xs text-muted">
            Enter 전송 · Shift+Enter 줄바꿈 · 등록된 문서에서만 답하며 근거가 없으면 “확인할 수 없습니다”라고 답합니다.
          </p>
        </div>
      </main>

      {/* 근거 패널: 큰 화면 고정, 작은 화면은 서랍 */}
      <aside className={cx(
        "fixed inset-y-0 right-0 z-30 w-[min(400px,100%)] border-l border-line bg-surface transition-transform lg:static lg:w-[400px] lg:translate-x-0",
        showSources ? "translate-x-0 shadow-xl" : "translate-x-full",
      )}>
        <SourcesPanel turn={selectedTurn} focusId={focusChunk} onClose={() => setShowSources(false)} />
      </aside>
      </>)}
    </div>
  );
}
