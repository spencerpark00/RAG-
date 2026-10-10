// 문서 관리 화면: 문서 목록·상태 지정·업로드·청크 미리보기·재색인
import { ArrowRight, Ban, Eye, FileUp, Loader2, RefreshCw, Search, Trash2, Upload, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { DocDetail, DocItem, DocStatus, IndexStats, IndexStatus } from "../lib/api";
import { deleteDoc, getDoc, getDocs, patchDoc, reindex, uploadDoc } from "../lib/api";
import { ChunkBody } from "./SourcesPanel";
import { Badge, Button, StatusBadge, cx } from "./ui";

const STATUSES: DocStatus[] = ["현행", "폐지", "미표기"];
type Filter = "전체" | DocStatus | "제외" | "업로드";

const input = "h-9 w-full rounded-lg border border-line bg-surface px-3 text-sm outline-none focus:border-brand";

export function DocsPage({ onIndexed }: { onIndexed: () => void }) {
  const [docs, setDocs] = useState<DocItem[]>([]);
  const [index, setIndex] = useState<IndexStatus>();
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("전체");
  const [detailNo, setDetailNo] = useState<string>();
  const [showUpload, setShowUpload] = useState(false);
  const [indexing, setIndexing] = useState(false);
  const [lastRun, setLastRun] = useState<IndexStats>();
  const [toast, setToast] = useState<{ text: string; bad?: boolean }>();

  const notify = (text: string, bad = false) => { setToast({ text, bad }); setTimeout(() => setToast(undefined), 3500); };
  const refresh = () => getDocs().then((d) => { setDocs(d.docs); setIndex(d.index); }).catch((e) => notify(e.message, true));
  useEffect(() => { refresh(); }, []);

  const counts = useMemo(() => ({
    현행: docs.filter((d) => d.status === "현행" && !d.excluded).length,
    폐지: docs.filter((d) => d.status === "폐지" && !d.excluded).length,
    미표기: docs.filter((d) => d.status === "미표기" && !d.excluded).length,
    제외: docs.filter((d) => d.excluded).length,
    업로드: docs.filter((d) => d.source === "upload").length,
  }), [docs]);

  const shown = docs.filter((d) => {
    const q = query.trim();
    if (q && !`${d.title} ${d.doc_id} ${d.doc_no}`.includes(q)) return false;
    if (filter === "전체") return true;
    if (filter === "제외") return d.excluded;
    if (filter === "업로드") return d.source === "upload";
    return d.status === filter && !d.excluded;
  });

  async function change(no: string, body: Parameters<typeof patchDoc>[1]) {
    try { await patchDoc(no, body); await refresh(); } catch (e) { notify((e as Error).message, true); }
  }

  async function runIndex() {
    setIndexing(true);
    try {
      const r = await reindex();
      setLastRun(r.stats);
      notify(r.stats.embedding_error ?? `색인 완료: 새로 임베딩 ${r.stats.embedded} · 재사용 ${r.stats.reused}`, !!r.stats.embedding_error);
      await refresh();
      onIndexed();
    } catch (e) {
      notify((e as Error).message, true);
    } finally {
      setIndexing(false);
    }
  }

  const stats = lastRun ?? index?.last ?? undefined;
  const totalChunks = docs.reduce((s, d) => s + (d.excluded ? 0 : d.chunks), 0);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-6xl space-y-5 px-4 py-6 sm:px-6">
          {/* 머리말 + 재색인 */}
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-0 flex-1">
              <h2 className="text-xl font-bold tracking-tight">문서 관리</h2>
              <p className="mt-0.5 text-sm text-muted">문서를 추가하거나 상태를 바꾼 뒤 재색인하면 챗봇 검색에 반영됩니다.</p>
            </div>
            {index?.needs_reindex && !indexing && (
              <span className="inline-flex items-center gap-1.5 rounded-full bg-brand-soft px-3 py-1 text-xs font-medium text-brand">
                <span className="size-1.5 animate-pulse rounded-full bg-brand" />반영 안 된 변경 사항 있음
              </span>
            )}
            <Button variant={index?.needs_reindex ? "primary" : "outline"} onClick={runIndex} disabled={indexing}>
              {indexing ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
              {indexing ? "색인 중…" : "재색인"}
            </Button>
            <Button variant="outline" onClick={() => setShowUpload(true)}><Upload size={15} />문서 추가</Button>
          </div>

          {/* 색인 파이프라인 */}
          <div className="grid gap-2 rounded-2xl border border-line bg-surface p-3 sm:grid-cols-[1fr_auto_1fr_auto_1fr_auto_1fr] sm:items-center">
            <Step label="문서" value={`${docs.length - counts.제외}개`} sub={`샘플 ${docs.length - counts.업로드} · 업로드 ${counts.업로드}${counts.제외 ? ` · 제외 ${counts.제외}` : ""}`} />
            <ArrowRight size={16} className="mx-auto hidden text-muted sm:block" />
            <Step label="청킹" value={`${totalChunks}개 청크`} sub="## 섹션 단위, 800자 초과 시 분할" />
            <ArrowRight size={16} className="mx-auto hidden text-muted sm:block" />
            <Step
              label="임베딩"
              value={index?.embeddings ? "bge-m3 · 1024차원" : "없음"}
              sub={stats ? `새로 ${stats.embedded} · 재사용 ${stats.reused}${stats.removed ? ` · 삭제 ${stats.removed}` : ""}` : "-"}
            />
            <ArrowRight size={16} className="mx-auto hidden text-muted sm:block" />
            <Step
              label="검색 반영"
              value={index?.indexed_at ? index.indexed_at.replace("T", " ").slice(5, 16) : "색인 전"}
              sub={stats ? `${stats.seconds}초 소요` : "-"}
              highlight={index?.needs_reindex}
            />
          </div>

          {/* 검색·필터 */}
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative w-full sm:w-64">
              <Search size={15} className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted" />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="제목·문서번호 검색" className={cx(input, "pl-9")} />
            </div>
            {(["전체", "현행", "폐지", "미표기", "제외", "업로드"] as Filter[]).map((f) => (
              <button
                key={f}
                onClick={() => setFilter(f)}
                className={cx("cursor-pointer rounded-full border px-3 py-1 text-xs font-medium",
                  filter === f ? "border-brand bg-brand-soft text-brand" : "border-line bg-surface text-muted hover:text-ink")}
              >
                {f} {f === "전체" ? docs.length : counts[f]}
              </button>
            ))}
          </div>

          {/* 문서 표 */}
          <div className="overflow-hidden rounded-2xl border border-line bg-surface">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[720px] text-sm">
                <thead className="bg-subtle text-left text-xs text-muted">
                  <tr>
                    <th className="px-4 py-2.5 font-medium">번호</th>
                    <th className="px-2 py-2.5 font-medium">제목</th>
                    <th className="px-2 py-2.5 font-medium">상태</th>
                    <th className="px-2 py-2.5 font-medium">시행·적용</th>
                    <th className="px-2 py-2.5 text-right font-medium">청크</th>
                    <th className="px-2 py-2.5 font-medium">출처</th>
                    <th className="px-4 py-2.5 text-right font-medium">동작</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map((d) => (
                    <tr key={d.doc_no} className={cx("border-t border-line", d.excluded && "opacity-50")}>
                      <td className="px-4 py-2.5 tabular-nums text-muted">{d.doc_no}</td>
                      <td className="max-w-[320px] px-2 py-2.5">
                        <button onClick={() => setDetailNo(d.doc_no)} className="block max-w-full cursor-pointer truncate text-left font-medium hover:text-brand">{d.title}</button>
                        <div className="text-xs text-muted">{d.doc_id}{d.excluded && " · 색인 제외"}{d.overridden && !d.excluded && " · 상태 수정됨"}</div>
                      </td>
                      <td className="px-2 py-2.5">
                        <select
                          value={d.status}
                          onChange={(e) => change(d.doc_no, { status: e.target.value as DocStatus })}
                          className={cx("h-8 cursor-pointer rounded-lg border border-line bg-surface px-2 text-xs font-semibold outline-none",
                            d.status === "현행" && "text-ok", d.status === "폐지" && "text-bad", d.status === "미표기" && "text-muted")}
                        >
                          {STATUSES.map((s) => <option key={s}>{s}</option>)}
                        </select>
                      </td>
                      <td className="px-2 py-2.5 text-xs whitespace-nowrap text-muted">{d.effective || "-"}</td>
                      <td className="px-2 py-2.5 text-right tabular-nums">{d.excluded ? "-" : d.chunks}</td>
                      <td className="px-2 py-2.5"><Badge tone={d.source === "upload" ? "brand" : "neutral"}>{d.source === "upload" ? "업로드" : "샘플"}</Badge></td>
                      <td className="px-4 py-2.5">
                        <div className="flex justify-end gap-1">
                          <Button variant="ghost" size="sm" onClick={() => setDetailNo(d.doc_no)}><Eye size={13} />보기</Button>
                          {d.source === "upload" ? (
                            <Button variant="ghost" size="sm" className="hover:text-bad" onClick={async () => {
                              if (!confirm(`'${d.title}' 문서를 삭제할까요?`)) return;
                              try { await deleteDoc(d.doc_no); await refresh(); notify("삭제했습니다. 재색인하면 검색에서도 빠집니다."); } catch (e) { notify((e as Error).message, true); }
                            }}><Trash2 size={13} />삭제</Button>
                          ) : (
                            <Button variant="ghost" size="sm" onClick={() => change(d.doc_no, { excluded: !d.excluded })}>
                              <Ban size={13} />{d.excluded ? "포함" : "제외"}
                            </Button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {shown.length === 0 && (
                    <tr><td colSpan={7} className="px-4 py-10 text-center text-sm text-muted">조건에 맞는 문서가 없습니다.</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </div>
          <p className="text-xs text-muted">
            샘플 문서는 원본을 바꾸지 않고 상태·제외 설정만 따로 저장합니다(doc_overrides.json). 폐지 문서도 색인에 남겨 두어 과거 시점 문의에 답할 수 있게 하고, 답변 시 '폐지' 표시로 구분합니다.
          </p>
        </div>
      </div>

      {detailNo && <DetailDrawer no={detailNo} onClose={() => setDetailNo(undefined)} onChanged={refresh} notify={notify} />}
      {showUpload && <UploadModal onClose={() => setShowUpload(false)} onDone={async (no) => { setShowUpload(false); await refresh(); notify(`문서 ${no}을(를) 추가했습니다. 재색인하면 검색에 반영됩니다.`); }} notify={notify} />}
      {toast && (
        <div className={cx("fixed bottom-5 left-1/2 z-50 -translate-x-1/2 rounded-xl px-4 py-2.5 text-sm shadow-lg animate-rise",
          toast.bad ? "bg-bad text-white" : "bg-ink text-canvas")}>{toast.text}</div>
      )}
    </div>
  );
}

function Step({ label, value, sub, highlight }: { label: string; value: string; sub: string; highlight?: boolean }) {
  return (
    <div className={cx("rounded-xl px-3 py-2", highlight ? "bg-brand-soft" : "bg-subtle/60")}>
      <div className="text-xs text-muted">{label}</div>
      <div className="text-[15px] font-semibold tabular-nums">{value}</div>
      <div className="truncate text-xs text-muted">{sub}</div>
    </div>
  );
}

function Shell({ title, onClose, children, wide }: { title: string; onClose: () => void; children: React.ReactNode; wide?: boolean }) {
  return (
    <div className="fixed inset-0 z-40 flex justify-end bg-black/30" onClick={onClose}>
      <div className={cx("flex h-full w-full flex-col bg-surface shadow-2xl animate-rise", wide ? "max-w-2xl" : "max-w-lg")} onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-2 border-b border-line px-5 py-3.5">
          <h3 className="min-w-0 flex-1 truncate font-semibold">{title}</h3>
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="닫기"><X size={16} /></Button>
        </div>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
      </div>
    </div>
  );
}

function DetailDrawer({ no, onClose, onChanged, notify }: { no: string; onClose: () => void; onChanged: () => void; notify: (t: string, bad?: boolean) => void }) {
  const [d, setD] = useState<DocDetail>();
  const [tab, setTab] = useState<"chunks" | "raw">("chunks");
  const [effective, setEffective] = useState("");
  const load = () => getDoc(no).then((x) => { setD(x); setEffective(x.effective.replace(/^(시행일|적용기간)\s*/, "")); }).catch((e) => notify(e.message, true));
  useEffect(() => { load(); }, [no]);

  async function save(body: Parameters<typeof patchDoc>[1]) {
    try { await patchDoc(no, body); await load(); onChanged(); notify("저장했습니다. 재색인하면 반영됩니다."); } catch (e) { notify((e as Error).message, true); }
  }

  return (
    <Shell title={d ? `${d.doc_no} · ${d.title}` : "불러오는 중…"} onClose={onClose} wide>
      {d && (
        <div className="space-y-5">
          <div className="grid gap-3 sm:grid-cols-3">
            <label className="space-y-1 text-xs text-muted">상태
              <select value={d.status} onChange={(e) => save({ status: e.target.value as DocStatus })} className={input}>
                {STATUSES.map((s) => <option key={s}>{s}</option>)}
              </select>
            </label>
            <label className="space-y-1 text-xs text-muted sm:col-span-2">시행일
              <div className="flex gap-2">
                <input value={effective} onChange={(e) => setEffective(e.target.value)} placeholder="2025-03-01" className={input} />
                <Button variant="outline" onClick={() => save({ effective })}>저장</Button>
              </div>
            </label>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex rounded-lg border border-line bg-subtle p-0.5 text-xs">
              {(["chunks", "raw"] as const).map((t) => (
                <button key={t} onClick={() => setTab(t)} className={cx("cursor-pointer rounded-md px-3 py-1 font-medium", tab === t ? "bg-surface shadow-sm" : "text-muted")}>
                  {t === "chunks" ? `청크 미리보기 (${d.chunks.length})` : "원문"}
                </button>
              ))}
            </div>
            {d.excluded && <Badge tone="bad">색인 제외됨</Badge>}
          </div>

          {tab === "raw" ? (
            <pre className="overflow-x-auto rounded-xl bg-subtle p-4 text-[13px] leading-relaxed whitespace-pre-wrap">{d.raw}</pre>
          ) : (
            <div className="space-y-3">
              <p className="text-xs text-muted">지금 설정으로 잘랐을 때의 모습입니다. 각 청크 첫 줄의 머리말(문서번호·상태·시행일)이 검색과 답변 생성에 함께 들어갑니다.</p>
              {d.chunks.map((c) => (
                <div key={c.chunk_id} className="rounded-xl border border-line p-3">
                  <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
                    <span className="font-semibold text-ink">{c.chunk_id}</span>
                    <StatusBadge status={c.status} />
                    <span>{c.section}</span>
                    <span className="ml-auto tabular-nums">{c.text.length}자</span>
                  </div>
                  <div className="mt-2 rounded-md bg-brand-soft px-2 py-1 font-mono text-[11.5px] text-brand">{c.text.split("\n")[0]}</div>
                  <ChunkBody text={c.text} />
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </Shell>
  );
}

function UploadModal({ onClose, onDone, notify }: { onClose: () => void; onDone: (no: string) => void; notify: (t: string, bad?: boolean) => void }) {
  const [title, setTitle] = useState("");
  const [docId, setDocId] = useState("");
  const [status, setStatus] = useState<DocStatus>("현행");
  const [effective, setEffective] = useState("");
  const [content, setContent] = useState("");
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  async function readFile(f: File) {
    if (!/\.(md|txt)$/i.test(f.name)) { notify("지금은 .md, .txt 파일만 지원합니다.", true); return; }
    const text = await f.text();
    setContent(text);
    const h1 = text.match(/^#\s+(.+)$/m)?.[1];
    if (!title) setTitle(h1 ?? f.name.replace(/\.(md|txt)$/i, ""));
  }

  async function submit() {
    setBusy(true);
    try { const r = await uploadDoc({ title, content, doc_id: docId, status, effective }); onDone(r.doc_no); }
    catch (e) { notify((e as Error).message, true); }
    finally { setBusy(false); }
  }

  const sections = (content.match(/^## /gm) ?? []).length;

  return (
    <Shell title="문서 추가" onClose={onClose}>
      <div className="space-y-4">
        <div
          onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
          onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); const f = e.dataTransfer.files[0]; if (f) readFile(f); }}
          onClick={() => fileRef.current?.click()}
          className={cx("flex cursor-pointer flex-col items-center gap-1.5 rounded-xl border-2 border-dashed p-6 text-center text-sm",
            drag ? "border-brand bg-brand-soft" : "border-line hover:border-brand")}
        >
          <FileUp size={22} className="text-brand" />
          <span className="font-medium">.md / .txt 파일을 끌어다 놓거나 클릭</span>
          <span className="text-xs text-muted">또는 아래에 본문을 직접 붙여 넣으세요</span>
          <input ref={fileRef} type="file" accept=".md,.txt" hidden onChange={(e) => e.target.files?.[0] && readFile(e.target.files[0])} />
        </div>

        <label className="block space-y-1 text-xs text-muted">제목
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="예) 데이터 쿠폰 운영 지침" className={input} />
        </label>
        <div className="grid grid-cols-3 gap-3">
          <label className="space-y-1 text-xs text-muted">문서 ID
            <input value={docId} onChange={(e) => setDocId(e.target.value)} placeholder="CPN-001" className={input} />
          </label>
          <label className="space-y-1 text-xs text-muted">상태
            <select value={status} onChange={(e) => setStatus(e.target.value as DocStatus)} className={input}>
              {STATUSES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </label>
          <label className="space-y-1 text-xs text-muted">시행일
            <input value={effective} onChange={(e) => setEffective(e.target.value)} placeholder="2026-01-01" className={input} />
          </label>
        </div>
        <label className="block space-y-1 text-xs text-muted">본문 (## 제목으로 섹션을 나누면 섹션마다 청크가 됩니다)
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            rows={12}
            placeholder={"## 사용 기준\n- 쿠폰 1장당 1GB\n- 발급일로부터 30일 이내 사용\n\n## 발급\n- 매월 1일 VIP 등급에 2장 자동 발급"}
            className="w-full rounded-lg border border-line bg-surface p-3 font-mono text-[13px] text-ink outline-none focus:border-brand"
          />
        </label>
        <p className="text-xs text-muted">{content.length}자 · 섹션 {sections}개 → 약 {Math.max(sections, content.trim() ? 1 : 0)}개 이상의 청크</p>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>취소</Button>
          <Button variant="primary" disabled={!title.trim() || !content.trim() || busy} onClick={submit}>
            {busy && <Loader2 size={15} className="animate-spin" />}추가
          </Button>
        </div>
      </div>
    </Shell>
  );
}
