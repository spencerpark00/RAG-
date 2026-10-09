# 한빛텔레콤 업무지식 검색 챗봇 (RAG 프로토타입)

가상 통신사 고객센터 문서 25개로 만든 RAG 챗봇. 프레임워크 없이 순수 Python + Ollama(qwen2.5:3b 답변, bge-m3 임베딩).

## 빠른 실행

```bash
source .venv/bin/activate        # 맥: ~/Documents/agent-practice/.venv
ollama pull bge-m3               # 처음 한 번 (임베딩 모델, 약 1.2GB)
python embed.py                  # 처음 한 번 (청크 55개 → embeddings.json)
python chat.py                   # Ollama 서버가 켜져 있어야 함 (curl localhost:11434 → "Ollama is running")
```

```
질문> 5G 스탠다드 월정액은?
5G 스탠다드 월정액은 69,000원입니다. (근거: 02-0)
참고 문서: 02-0 [미표기] 한빛텔레콤 5G 스탠다드 요금제 > 요금 및 제공량
질문> /근거        ← 근거 청크 원문 보기
질문> /종료
```

## 실행 구조

```
[색인: 한 번만]                         [질문할 때마다]
rag_dummy/docs/*.md                      질문
      │ chunk.py                           │
      ▼                                    ▼
chunks.jsonl (55청크) ──────────────▶ retrieve.py  하이브리드 검색 상위 5개 청크
 '## 섹션' 1개 = 1청크                 ├ BM25 (키워드, 글자 bigram)
 + [문서번호·상태·시행일] 머리말        ├ 벡터 (질문을 bge-m3로 임베딩 → 코사인 유사도)
      │ embed.py                       └ 두 순위를 RRF로 합침
      ▼                                    │
embeddings.json (55 × 1024차원) ──────────┘ ▼
                                     answer.py   프롬프트 조립 → Ollama(qwen2.5:3b)
                                           │       → 문장부호 정리·언어 검사
                                           ▼
                                     chat.py     답 + 참고 문서 출력
```

| 단계 | 파일 | 하는 일 | 실무(KTcs)에서 바뀔 부분 |
|---|---|---|---|
| 로딩·청킹 | `chunk.py` | md를 섹션 단위로 자르고 메타데이터(현행/폐지, 시행일)를 청크마다 붙임 | PDF·HWP·엑셀 파서, 표·이미지 처리, 길이 상한 |
| 임베딩 | `embed.py` | 청크를 bge-m3로 1024차원 벡터로 바꿔 JSON 파일에 저장 | 벡터 DB(FAISS·pgvector 등), 문서 변경 시 증분 갱신 |
| 검색 | `retrieve.py` | BM25 + 벡터 검색을 RRF로 합친 하이브리드 (`--retriever=bm25\|vector\|hybrid`) | 재순위(reranker), 메타데이터 필터(현행만 등) |
| 생성 | `answer.py` | 자료 → 규칙 → 질문 순서의 프롬프트, 근거 없으면 "확인할 수 없습니다" | 더 큰 모델, 출처 링크, 권한별 문서 필터 |
| 인터페이스 | `chat.py` | 터미널 대화 | 웹 UI·상담 시스템 연동 |
| 평가 | `eval_retrieval.py`, `eval_answer.py` | 검색 적중(Hit@k)과 답변 정확성을 분리 채점 | 실제 상담 질문 세트, 사람 검수 |

## 평가 (30문항, 참고용)

```bash
python eval_retrieval.py --retriever=bm25     # Hit@1 22/27, Hit@5(근거 전부) 26/27
python eval_retrieval.py --retriever=hybrid   # Hit@1 25/27, Hit@5(근거 전부) 27/27
python eval_answer.py                         # 답변까지: 25~26/30 (실행마다 1~2문항 흔들림)
```

프롬프트 실험 기록: `experiments/prompt_v2.md`

## 알려진 한계

- 날짜가 들어간 개정 규정 질문(Q08, Q09)에서 답을 거부하는 경향
- 검색이 좋아져도(하이브리드) 답변 정확도는 25~26/30으로 비슷함: 남은 오답은 대부분 생성(3b 모델) 쪽 문제
- 이전 대화를 기억하지 않음 (질문마다 독립 처리)
