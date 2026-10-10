// 왼쪽 사이드바: 새 대화, 대화 목록(이 브라우저에만 저장), 파이프라인 요약
import { FolderCog, MessageSquare, MessagesSquare, Plus, Trash2, X } from "lucide-react";
import type { Health } from "../lib/api";
import type { Conversation } from "../lib/store";
import { Button, Logo, cx } from "./ui";

interface Props {
  conversations: Conversation[];
  activeId: string;
  view: "chat" | "docs";
  onView: (v: "chat" | "docs") => void;
  health?: Health;
  onNew: () => void;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onClose: () => void;
}

export function Sidebar({ conversations, activeId, view, onView, health, onNew, onSelect, onDelete, onClose }: Props) {
  return (
    <div className="flex h-full flex-col">
      <div className="flex h-15 items-center gap-2.5 px-4">
        <Logo />
        <div className="min-w-0 flex-1 leading-tight">
          <div className="text-[15px] font-bold tracking-tight">업무지식 Assistant</div>
          <div className="text-xs text-muted">한빛텔레콤 고객센터</div>
        </div>
        <Button variant="ghost" size="icon" className="md:hidden" onClick={onClose} aria-label="닫기"><X size={16} /></Button>
      </div>

      <div className="space-y-0.5 px-2 pb-3">
        {([["chat", "대화", MessagesSquare], ["docs", "문서 관리", FolderCog]] as const).map(([v, label, Icon]) => (
          <button
            key={v}
            onClick={() => onView(v)}
            className={cx("flex w-full cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm font-medium",
              view === v ? "bg-brand-soft text-brand" : "text-muted hover:bg-subtle hover:text-ink")}
          >
            <Icon size={15} />{label}
          </button>
        ))}
      </div>

      <div className="flex items-center justify-between border-t border-line px-4 pt-3 pb-1.5 text-xs font-medium text-muted">
        대화 기록
        <button onClick={onNew} className="inline-flex cursor-pointer items-center gap-1 rounded-md px-1.5 py-0.5 hover:bg-subtle hover:text-ink"><Plus size={13} />새 대화</button>
      </div>

      <nav className="flex-1 space-y-0.5 overflow-y-auto px-2">
        {conversations.length === 0 && <p className="px-3 py-4 text-xs text-muted">대화 기록이 없습니다.</p>}
        {conversations.map((c) => (
          <div
            key={c.id}
            onClick={() => onSelect(c.id)}
            className={cx(
              "group flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm",
              c.id === activeId && view === "chat" ? "bg-subtle font-medium" : "text-muted hover:bg-subtle hover:text-ink",
            )}
          >
            <MessageSquare size={14} className="shrink-0" />
            <span className="min-w-0 flex-1 truncate">{c.title}</span>
            <button
              onClick={(e) => { e.stopPropagation(); onDelete(c.id); }}
              className="cursor-pointer text-muted opacity-0 hover:text-bad group-hover:opacity-100"
              aria-label="대화 삭제"
            >
              <Trash2 size={13} />
            </button>
          </div>
        ))}
      </nav>

      <div className="space-y-1 border-t border-line p-4 text-xs text-muted">
        <div className="font-medium text-ink">RAG 파이프라인</div>
        <div>색인된 청크 {health?.chunks ?? "-"}개</div>
        <div>검색: BM25 + bge-m3 벡터 (RRF)</div>
        <div>생성: {(health?.llms ?? []).map((m) => m.model.replace(/^.*\//, "")).join(" / ") || "-"}</div>
      </div>
    </div>
  );
}
