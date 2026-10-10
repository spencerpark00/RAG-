// 대화 한 턴: 사용자 질문 말풍선 + 어시스턴트 답변 카드
import { Check, Copy, Info, RotateCcw, ThumbsDown, ThumbsUp } from "lucide-react";
import { useState } from "react";
import type { Turn } from "../lib/store";
import { stripCitation } from "../lib/store";
import { Button, cx } from "./ui";

interface Props {
  turn: Turn;
  active: boolean;
  onSelect: () => void;
  onCite: (chunkId: string) => void;
  onRate: (r: "up" | "down") => void;
  onRetry: () => void;
}

function Stage({ text }: { text: string }) {
  return (
    <div className="flex items-center gap-2 text-sm text-muted">
      <span className="size-3.5 animate-spin rounded-full border-2 border-line border-t-brand" />
      {text}
    </div>
  );
}

export function Message({ turn, active, onSelect, onCite, onRate, onRetry }: Props) {
  const [copied, setCopied] = useState(false);
  const answer = stripCitation(turn.answer);

  return (
    <div className="animate-rise space-y-3">
      <div className="flex justify-end">
        <div className="max-w-[80%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-[var(--bubble)] px-4 py-2.5 text-white">
          {turn.question}
        </div>
      </div>

      <div
        onClick={onSelect}
        className={cx(
          "max-w-[92%] cursor-pointer rounded-2xl rounded-tl-md border p-4 transition-colors",
          turn.refused ? "bg-subtle" : "bg-surface",
          active ? "border-brand" : "border-line hover:border-muted/40",
        )}
      >
        {turn.stage === "searching" && <Stage text="문서를 검색하는 중…" />}
        {turn.stage === "writing" && !turn.answer && <Stage text={`문서 ${turn.chunks.length}개를 읽고 답변을 작성하는 중…`} />}
        {answer && (
          <p className={cx("whitespace-pre-wrap break-words leading-relaxed", turn.stage === "writing" && "after:ml-0.5 after:inline-block after:h-[1.05em] after:w-[7px] after:animate-blink after:bg-brand after:align-[-2px] after:content-['']")}>
            {answer}
          </p>
        )}
        {turn.notice && <p className="mt-2 flex items-start gap-1.5 text-xs text-muted"><Info size={13} className="mt-0.5 shrink-0" />{turn.notice}</p>}
        {turn.stage === "error" && <p className="text-sm text-bad">{turn.error}</p>}
        {turn.stage === "stopped" && <p className="mt-1 text-xs text-muted">중단됨</p>}
        {turn.refused && turn.stage === "done" && (
          <p className="mt-2 flex items-start gap-1.5 text-[13px] text-muted">
            <Info size={14} className="mt-0.5 shrink-0" /> 등록된 문서에서 근거를 찾지 못했습니다. 담당 부서 확인이 필요합니다.
          </p>
        )}

        {(turn.stage === "done" || turn.stage === "error" || turn.stage === "stopped") && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5 border-t border-dashed border-line pt-2.5 text-xs text-muted" onClick={(e) => e.stopPropagation()}>
            {turn.cited.length > 0 && <span>근거</span>}
            {turn.cited.map((id) => (
              <button
                key={id}
                onClick={() => { onSelect(); onCite(id); }}
                className="cursor-pointer rounded-md border border-line bg-subtle px-1.5 py-px tabular-nums hover:border-brand hover:text-brand"
              >
                {id}
              </button>
            ))}
            {turn.seconds !== undefined && <span className="ml-1">{turn.seconds}초</span>}
            {turn.llm && <span className="hidden sm:inline">· {turn.llm.replace(/^.*\//, "")}</span>}
            <span className="flex-1" />
            {turn.stage === "done" && (
              <>
                <Button variant="ghost" size="sm" onClick={async () => {
                  try { await navigator.clipboard.writeText(answer); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* 권한 없음 */ }
                }}>
                  {copied ? <Check size={13} /> : <Copy size={13} />}{copied ? "복사됨" : "복사"}
                </Button>
                <Button variant="ghost" size="sm" className={cx(turn.rating === "up" && "bg-brand-soft text-brand")} onClick={() => onRate("up")} aria-label="도움됨"><ThumbsUp size={13} /></Button>
                <Button variant="ghost" size="sm" className={cx(turn.rating === "down" && "bg-brand-soft text-brand")} onClick={() => onRate("down")} aria-label="도움 안 됨"><ThumbsDown size={13} /></Button>
              </>
            )}
            {(turn.stage === "error" || turn.stage === "stopped") && (
              <Button variant="ghost" size="sm" onClick={onRetry}><RotateCcw size={13} />다시 시도</Button>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
