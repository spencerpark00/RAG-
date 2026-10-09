"""1단계: 문서 로딩 + 청킹 (순수 Python, 외부 패키지 없음)

규칙
- '## ' 섹션 1개 = 청크 1개. 섹션이 없는 문서는 본문 전체가 1청크.
- 첫 '## ' 앞에 본문이 있으면 '개요' 청크로 따로 만든다.
- 모든 청크 앞에 [문서번호 · 문서ID · 상태 · 시행일] 헤더를 붙여
  현행/폐지 정보가 청크 단위로 남게 한다.

실행: python chunk.py  →  chunks.jsonl 생성 + 요약 출력
"""
import json
from pathlib import Path

ROOT = Path(__file__).parent
DOCS_DIR = ROOT / "rag_dummy" / "docs"
OUT_PATH = ROOT / "chunks.jsonl"


def parse_meta(line):
    """'- 문서번호: X / 시행일: Y / 상태: Z' → {'문서번호': 'X', ...}"""
    meta = {}
    for part in line.lstrip("- ").split(" / "):
        if ":" in part:
            key, value = part.split(":", 1)
            meta[key.strip()] = value.strip()
    return meta


def load_doc(path):
    lines = path.read_text(encoding="utf-8").splitlines()
    title = lines[0].lstrip("# ").strip()
    meta_line = next((l for l in lines[1:3] if l.startswith("- 문서번호")), "")
    meta = parse_meta(meta_line)
    body_start = lines.index(meta_line) + 1 if meta_line else 1
    return {
        "doc_no": path.name[:2],
        "file": path.name,
        "title": title,
        "doc_id": meta.get("문서번호", ""),
        # 상태 표기가 없는 문서는 현행으로 간주하지 않고 그대로 '미표기'로 둔다
        "status": meta.get("상태", "미표기").split(" ")[0],
        # 헤더에 원문 표현 그대로 표시 (예: '시행일 2025-03-01', '적용기간 ~2025-02-28')
        "effective": next((f"{k} {meta[k]}" for k in ("시행일", "적용기간") if k in meta), ""),
        "body_lines": lines[body_start:],
    }


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
    return [(n, "\n".join(b).strip()) for n, b in sections if "\n".join(b).strip()]


def make_header(doc, section):
    tags = [f"문서 {doc['doc_no']}", doc["doc_id"], doc["status"]]
    if doc["effective"]:
        tags.append(doc["effective"])
    return f"[{' · '.join(tags)}] {doc['title']} > {section}"


def chunk_all(docs_dir=DOCS_DIR):
    chunks = []
    for path in sorted(docs_dir.glob("*.md")):
        doc = load_doc(path)
        for i, (section, body) in enumerate(split_sections(doc["body_lines"])):
            chunks.append({
                "chunk_id": f"{doc['doc_no']}-{i}",
                "doc_no": doc["doc_no"],
                "doc_id": doc["doc_id"],
                "title": doc["title"],
                "status": doc["status"],
                "effective": doc["effective"],
                "section": section,
                "text": make_header(doc, section) + "\n" + body,
            })
    return chunks


def main():
    chunks = chunk_all()
    with OUT_PATH.open("w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    lengths = [len(c["text"]) for c in chunks]
    print(f"문서 {len({c['doc_no'] for c in chunks})}개 → 청크 {len(chunks)}개")
    print(f"청크 길이(자): 최소 {min(lengths)} / 평균 {sum(lengths) // len(lengths)} / 최대 {max(lengths)}")
    print("\n| chunk_id | 상태 | 섹션 | 길이 |\n|---|---|---|---|")
    for c in chunks:
        print(f"| {c['chunk_id']} | {c['status']} | {c['section']} | {len(c['text'])} |")
    print(f"\n저장: {OUT_PATH.name}")


if __name__ == "__main__":
    main()
