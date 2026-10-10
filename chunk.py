"""1단계: 문서 로딩 + 청킹 (순수 Python, 외부 패키지 없음)

규칙
- '## ' 섹션 1개 = 청크 1개. 섹션이 없는 문서는 본문 전체가 1청크.
- 첫 '## ' 앞에 본문이 있으면 '개요' 청크로 따로 만든다.
- 모든 청크 앞에 [문서번호 · 문서ID · 상태 · 시행일] 헤더를 붙여
  현행/폐지 정보가 청크 단위로 남게 한다.
- 섹션이 MAX_CHARS보다 길면 줄 단위로 나눠 여러 청크로 만든다 (업로드 문서 대비).
- 문서 폴더는 두 곳: 샘플(rag_dummy/docs)과 업로드(uploads/docs).
- doc_overrides.json(문서 관리 화면에서 저장)의 상태·시행일·제외 설정을 원본보다 우선 적용한다.

실행: python chunk.py  →  chunks.jsonl 생성 + 요약 출력
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent
DOCS_DIR = ROOT / "rag_dummy" / "docs"
UPLOAD_DIR = ROOT / "uploads" / "docs"
DOCS_DIRS = (DOCS_DIR, UPLOAD_DIR)
OVERRIDES_PATH = ROOT / "doc_overrides.json"
OUT_PATH = ROOT / "chunks.jsonl"
MAX_CHARS = 800


def load_overrides():
    try:
        return json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def parse_meta(line):
    """'- 문서번호: X / 시행일: Y / 상태: Z' → {'문서번호': 'X', ...}"""
    meta = {}
    for part in line.lstrip("- ").split(" / "):
        if ":" in part:
            key, value = part.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta


def load_doc(path, overrides=None):
    lines = path.read_text(encoding="utf-8").splitlines() or [""]
    has_title = lines[0].startswith("# ")
    title = lines[0][2:].strip() if has_title else path.stem[3:] or path.stem
    meta_line = next((l for l in lines[1:3] if l.startswith("- 문서번호")), "")
    meta = parse_meta(meta_line)
    body_start = lines.index(meta_line) + 1 if meta_line else (1 if has_title else 0)
    doc = {
        "doc_no": path.name[:2],
        "file": path.name,
        "title": title,
        "doc_id": meta.get("문서번호", ""),
        # 상태 표기가 없는 문서는 현행으로 간주하지 않고 그대로 '미표기'로 둔다
        "status": meta.get("상태", "미표기").split(" ")[0],
        # 헤더에 원문 표현 그대로 표시 (예: '시행일 2025-03-01', '적용기간 ~2025-02-28')
        "effective": next((f"{k} {meta[k]}" for k in ("시행일", "적용기간") if k in meta), ""),
        "body_lines": lines[body_start:],
        "source": "upload" if path.parent == UPLOAD_DIR else "sample",
        "excluded": False,
    }
    o = (overrides or {}).get(doc["doc_no"], {})
    if o.get("status"):
        doc["status"] = o["status"]
    if o.get("effective") is not None:
        doc["effective"] = o["effective"]
    doc["excluded"] = bool(o.get("excluded"))
    doc["overridden"] = bool(o)
    return doc


def iter_docs(dirs=DOCS_DIRS, overrides=None):
    """두 폴더의 문서를 문서번호 순으로 (제외 문서 포함) 돌려준다."""
    overrides = load_overrides() if overrides is None else overrides
    paths = sorted((p for d in dirs if d.exists() for p in d.glob("*.md")), key=lambda p: p.name)
    return [load_doc(p, overrides) for p in paths]


def split_sections(body_lines):
    """[(섹션명, 본문), ...]. 첫 '## ' 앞 내용은 '개요'."""
    sections, name, buf = [], "개요", []
    for line in body_lines:
        if line.startswith("## "):
            sections.append((name, buf))
            name, buf = line[3:].strip(), []
        else:
            buf.append(line)
    sections.append((name, buf))
    out = []
    for n, b in sections:
        body = "\n".join(b).strip()
        if body:
            out.extend(split_long(n, body))
    return out


def split_long(name, body, max_chars=MAX_CHARS):
    """긴 섹션을 줄 경계에서 max_chars 이하 조각으로. 표(|로 시작하는 줄)는 중간에 자르지 않는다."""
    if len(body) <= max_chars:
        return [(name, body)]
    pieces, cur = [], []
    for line in body.split("\n"):
        in_table = line.lstrip().startswith("|") and cur and cur[-1].lstrip().startswith("|")
        if cur and len("\n".join(cur + [line])) > max_chars and not in_table:
            pieces.append("\n".join(cur).strip())
            cur = []
        cur.append(line)
    pieces.append("\n".join(cur).strip())
    pieces = [p for p in pieces if p]
    return [(f"{name} ({i}/{len(pieces)})", p) for i, p in enumerate(pieces, 1)]


def make_header(doc, section):
    tags = [f"문서 {doc['doc_no']}", doc["doc_id"], doc["status"]]
    if doc["effective"]:
        tags.append(doc["effective"])
    return f"[{' · '.join(tags)}] {doc['title']} > {section}"


def chunk_doc(doc):
    return [
        {
            "chunk_id": f"{doc['doc_no']}-{i}",
            "doc_no": doc["doc_no"],
            "doc_id": doc["doc_id"],
            "title": doc["title"],
            "status": doc["status"],
            "effective": doc["effective"],
            "section": section,
            "text": make_header(doc, section) + "\n" + body,
        }
        for i, (section, body) in enumerate(split_sections(doc["body_lines"]))
    ]


def chunk_all(dirs=DOCS_DIRS, overrides=None):
    return [c for doc in iter_docs(dirs, overrides) if not doc["excluded"] for c in chunk_doc(doc)]


def write_chunks(chunks, path=OUT_PATH):
    with path.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")


def main():
    chunks = chunk_all()
    write_chunks(chunks)

    lengths = [len(c["text"]) for c in chunks]
    print(f"문서 {len({c['doc_no'] for c in chunks})}개 → 청크 {len(chunks)}개")
    print(f"청크 길이(자): 최소 {min(lengths)} / 평균 {sum(lengths) // len(lengths)} / 최대 {max(lengths)}")
    print("\n| chunk_id | 상태 | 섹션 | 길이 |\n|---|---|---|---|")
    for c in chunks:
        print(f"| {c['chunk_id']} | {c['status']} | {c['section']} | {len(c['text'])} |")
    print(f"\n저장: {OUT_PATH.name}")


if __name__ == "__main__":
    main()
