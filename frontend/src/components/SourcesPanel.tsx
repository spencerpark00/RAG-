// 오른쪽 근거 패널: 선택한 답변이 참고한 검색 청크와 검색 과정을 보여준다.
import { AlertTriangle, ChevronDown, Search, X } from "lucide-react";
import { useEffect, useState } from "react";
import { RETRIEVER_LABEL } from "../lib/api";
import type { Turn } from "../lib/store";
import { Badge, Button, StatusBadge, cx } from "./ui";

/** 청크 본문: 첫 줄(머리말)은 카드 제목과 겹쳐 빼고, 마크다운 표는 <table>로 */
function ChunkBody({ text }: { text: string }) {
  const blocks: ({ kind: "text"; lines: string[] } | { kind: "table"; rows: string[][] })[] = [];
  for (const line of text.split("\n").slice(1)) {
    const t = line.trim();
    const last = blocks[blocks.length - 1];
    if (t.startsWith("|")) {
      if (/^\|\s*-/.test(t)) continue; // |---|---| 구분선
      const cells = t.replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
      if (last?.kind === "table") last.rows.push(cells);
      else blocks.push({ kind: "table", rows: [cells] });
    } else if (last?.kind === "text") last.lines.push(line);
    else blocks.push({ kind: "text", lines: [line] });
  }
  return (
    <div className="mt-2 space-y-2 text-[13px] leading-relaxed">
      {blocks.map((b, i) =>
        b.kind === "text" ? (
          <p key={i} className="whitespace-pre-wrap break-words">{b.lines.join("\n").trim()}</p>
        ) : (
          <div key={i} className="overflow-x-auto rounded-lg border border-line">
            <table className="w-full text-[12.5px]">
              <tbody>
                {b.rows.map((r, ri) => (
                  <tr key={ri} className={cx(ri === 0 && "bg-subtle font-semibold", "border-b border-line last:border-0")}>
                    {r.map((c, ci) => <td key={ci} className="px-2 py-1.5 align-top">{c}</td>)}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ),
      )}
    </div>
  );
}

export function SourcesPanel({ turn, focusId, onClose }: { turn?: Turn; focusId?: string; onClose: () => void }) {
  const [open, setOpen] = useState<Record<string, boolean>>({});

  // 인용된 청크는 기본으로 펼치고, 칩을 누른 청크로 스크롤
  useEffect(() => {
    if (!turn) return;
    setOpen(Object.fromEntries(turn.cited.map((id) => [id, true])));
  }, [turn?.id, turn?.cited.join()]);
  useEffect(() => {
    if (!focusId) return;
    setOpen((o) => ({ ...o, [focusId]: true }));
    const el = document.getElementById(`src-${focusId}`);
    el?.scrollIntoView({ behavior: "smooth", block: "center" });
    el?.classList.remove("animate-flash");
    void el?.offsetWidth;
    el?.classList.add("animate-flash");
  }, [focusId]);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-start gap-2 border-b border-line px-4 py-3.5">
        <div className="min-w-0 flex-1">
          <h3 className="text-sm font-semibold">근거 문서</h3>
          <p className="mt-0.5 truncate text-xs text-muted">
            {turn ? `“${turn.question}”` : "답변을 선택하면 검색된 문서가 표시됩니다"}
          </p>
        </div>
        <Button variant="ghost" size="icon" className="lg:hidden" onClick={onClose} aria-label="닫기">
          <X size={16} />
        </Button>
      </div>

      {turn && turn.chunks.length > 0 && (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-line bg-subtle/60 px-4 py-2 text-xs text-muted">
          <span className="inline-flex items-center gap-1"><Search size={12} />{RETRIEVER_LABEL[turn.retriever]} 상위 {turn.chunks.length}개</span>
          {turn.searchMs !== undefined && <span>검색 {(turn.searchMs / 1000).toFixed(1)}초</span>}
          {turn.seconds !== undefined && <span>전체 {turn.seconds}초</span>}
        </div>
      )}

      <div className="flex-1 space-y-2.5 overflow-y-auto p-3">
        {!turn && <p className="py-10 text-center text-sm text-muted">아직 질문이 없습니다.</p>}
        {turn && turn.chunks.length === 0 && <p className="py-10 text-center text-sm text-muted">문서를 검색하는 중…</p>}
        {turn?.chunks.map((c, i) => {
          const cited = turn.cited.includes(c.chunk_id);
          const isOpen = !!open[c.chunk_id];
          return (
            <div
              key={c.chunk_id}
              id={`src-${c.chunk_id}`}
              className={cx(
                "rounded-xl border bg-surface p-3 transition-shadow",
                cited ? "border-brand shadow-[0_0_0_3px_var(--brand-soft)]" : "border-line",
              )}
            >
              <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
                <span className="tabular-nums">#{i + 1}</span>
                <StatusBadge status={c.status} />
                {cited && <Badge tone="brand">답변에 인용</Badge>}
                <span>{c.doc_id}</span>
                {c.effective && <span>· {c.effective}</span>}
              </div>
              <div className="mt-1.5 text-sm font-semibold leading-snug">{c.title}</div>
              <div className="text-[13px] text-muted">{c.section} · {c.chunk_id}</div>
              {c.status === "폐지" && (
                <div className="mt-2 flex items-center gap-1.5 text-xs text-bad">
                  <AlertTriangle size={13} /> 폐지된 규정입니다. 과거 시점 문의에만 사용하세요.
                </div>
              )}
              <button
                className="mt-2 inline-flex cursor-pointer items-center gap-1 text-xs font-medium text-brand"
                onClick={() => setOpen((o) => ({ ...o, [c.chunk_id]: !isOpen }))}
              >
                <ChevronDown size={14} className={cx("transition-transform", !isOpen && "-rotate-90")} />
                원문 {isOpen ? "접기" : "보기"}
              </button>
              {isOpen && <ChunkBody text={c.text} />}
            </div>
          );
        })}
      </div>
    </div>
  );
}
