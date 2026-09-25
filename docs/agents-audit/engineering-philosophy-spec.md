# AGENTS.md 개발 철학 반영 spec

> **상태**: 초안 — 사용자 인터뷰와 검수 후 `AGENTS.md`에 반영한다.
> **목적**: `ai-session-telegram`의 코드 특성과 운영 위험에 맞는 AI 협업 원칙을 공용 agent 지침으로 승격한다.

## 1. 문제 정의

현재 `AGENTS.md`는 broker·hook·Telegram·runtime state의 기술 불변식은 설명하지만, 이 레포에서 AI가 어떤 방식으로 판단하고 작업해야 하는지에 대한 운영 철학은 충분히 명시하지 않는다.

그 결과 다음 실패가 재발할 수 있다.

- 구현부터 시작해 요구사항과 완료 기준이 뒤늦게 바뀜
- AI가 제품·운영 trade-off를 사용자 대신 결정함
- 세션 안에서만 결정과 장애 원인이 소비되고 다음 agent로 전달되지 않음
- 실패가 단순 재작업으로 끝나고 재발 방지 규칙이나 테스트로 승격되지 않음
- 다음 세션이 이전 세션의 실수를 다시 조사함

## 2. 핵심 원칙

### 2.1 Spec first, code second

동작·계약·운영 결과가 바뀌는 작업은 먼저 spec을 작성하고 승인받는다. spec은 다음을 포함한다.

- 문제와 사용자/운영자
- 현재 동작과 원하는 동작
- 포함 범위와 비목표
- 입력·출력·상태·외부 시스템 계약
- 정상·빈 값·실패·retry·stale 상태
- 보안·비용·성능·가용성 제약
- 검증 가능한 acceptance criteria

코드에서 새 제약을 발견해 spec과 충돌하면 임의로 결정하지 않고 `spec gap`으로 기록한 뒤 판단을 요청한다.

### 2.2 사용자는 판단 책임자, AI는 구현자

사용자는 제품 목적, 위험 허용도, trade-off, 완료 승인에 책임진다. AI는 조사·질문·spec 정리·코드 작성·테스트·review 자료 작성을 담당한다.

AI가 단독으로 확정하면 안 되는 것:

- 사용자 경험이나 메시지 의미를 바꾸는 판단
- 데이터 삭제·topic 삭제·session 종료 같은 비가역적 운영 동작
- 보안·권한·secret 취급의 완화
- retry/drop/duplicate 중 어떤 실패를 허용할지에 대한 정책
- 기존 AGENTS/README/코드 계약을 뒤집는 변경

### 2.3 지식은 저장소에 외부화한다

대화·모델 memory·Telegram topic을 지식의 원본으로 삼지 않는다.

| 지식 | 기록 위치 |
|---|---|
| 현재 실행 계약 | 코드 docstring, 테스트, `AGENTS.md` |
| 기술·운영 결정 | `docs/decisions/` |
| 장애·복구 절차 | `docs/operations/` |
| 작업별 spec/acceptance | `docs/specs/` 또는 task 문서 |
| 실패와 학습 | `docs/learning/` 또는 작업별 learning 문서 |
| 세션 handoff | 작업 문서의 handoff와 PR 설명 |

같은 규칙을 여러 문서에 복사하지 않는다. 원본과 파생 문서를 구분한다.

### 2.4 구현 전 딥인터뷰

spec 작성 agent는 구현 전에 사용자에게 질문해 불확실성을 줄인다. 질문이 필요한데도 가정을 숨기고 코드를 시작하지 않는다.

최소 질문 영역:

- 누가 어떤 문제를 겪는가
- 성공/실패를 무엇으로 판단하는가
- 반드시 보존해야 하는 기존 동작은 무엇인가
- 메시지 유실·중복·지연 중 어떤 위험을 가장 크게 보는가
- session/topic이 종료되었을 때 사용자가 기대하는 동작은 무엇인가
- 사람 입력과 AI handoff를 어디까지 구분해야 하는가
- 자동 정리와 사용자 확인 중 어느 쪽을 선택할 것인가
- 검증 가능한 acceptance criteria는 무엇인가

이미 코드·문서로 확정된 사실은 질문하지 말고 근거를 제시한다. 인터뷰 결과는 `spec/input.md` 또는 작업 문서에 원문과 결정으로 남긴다.

### 2.5 모든 AI 실패는 투자다

실패·반려·오판·재작업은 삭제하지 않는다. 최소 다음을 기록한다.

- 실패한 시도와 관찰된 증상
- 근본 원인과 놓친 신호
- 어떤 가정이 틀렸는가
- 수정한 코드·문서·테스트
- 같은 실패를 다음 agent가 피할 수 있는 규칙
- 아직 남은 불확실성과 다음 검증 방법

반복될 수 있는 학습은 반드시 다음 중 하나로 승격한다.

- regression test
- `AGENTS.md`의 불변식
- `docs/decisions/`의 결정
- `docs/operations/`의 runbook
- spec acceptance criterion

## 3. 표준 작업 흐름

```text
문제 수집
→ 작업 분류
→ 사용자 딥인터뷰
→ spec 작성
→ 별도 spec review
→ 사용자 판단/승인
→ AI 구현
→ 테스트·코드 review
→ 운영/acceptance 검증
→ 실패·learning·handoff 기록
→ PR
→ 사용자 확인 후 merge
```

### 작업 분류

- **관찰/문서-only**: 코드 동작·계약이 바뀌지 않으면 간단한 기록으로 진행한다.
- **behavior change**: 메시지 role, session lifecycle, Telegram API, runtime state, hook contract, service 동작이 바뀌면 spec을 필수로 한다.
- **incident/hotfix**: 먼저 피해를 막되, 사후에 원인·영향·재발 방지를 spec/learning으로 기록한다.

### 세션 시작

AI는 작업 시작 전에 다음을 읽는다.

1. `AGENTS.md`
2. 관련 spec/decision/operation 문서
3. 최근 learning/handoff
4. 변경 대상 코드와 테스트

그리고 현재 이해한 문제·가정·검증 계획을 짧게 기록한다.

### 세션 종료

AI는 다음 agent가 바로 이어갈 수 있도록 handoff를 남긴다.

- 완료한 것
- 남은 것
- 실행한 검증과 결과
- 실패·반려·미해결 가정
- 다음 agent가 먼저 읽을 파일
- 사용자가 판단해야 할 질문

## 4. `AGENTS.md`에 반영할 규칙의 acceptance criteria

- [ ] behavior change는 spec 승인 전 구현하지 않는다는 규칙이 있다.
- [ ] 사용자와 AI의 책임 경계가 명시되어 있다.
- [ ] 결정·계약·장애·학습·handoff의 저장 위치가 명시되어 있다.
- [ ] broker/hook/runtime state 특성에 맞는 딥인터뷰 질문이 포함되어 있다.
- [ ] 실패를 regression test/decision/runbook/spec로 승격하는 기준이 있다.
- [ ] 세션 시작·종료 시 읽고 남길 산출물이 정의되어 있다.
- [ ] 문서 규칙이 현재 코드의 PR·테스트·secret 정책과 충돌하지 않는다.
- [ ] `CLAUDE.md`는 계속 `@AGENTS.md`만 참조한다.

## 5. 사용자 확인이 필요한 결정

다음 질문은 `AGENTS.md`에 최종 규칙을 쓰기 전에 사용자 판단이 필요하다.

1. 모든 behavior change에 spec을 강제할지, 아니면 message/session/Telegram/service contract 변경에만 강제할지?
2. spec 승인 주체를 사용자 본인으로만 둘지, 별도 PO/reviewer agent의 사전 검수도 필수로 둘지?
3. 공통 learning을 `docs/learning/`에 누적할지, 각 작업 문서 안에만 보관할지?
4. AI handoff와 실제 user prompt의 분류가 애매할 때, 자동 분류보다 user 확인 메시지를 우선할지?
5. stale session/topic 자동 삭제 같은 비가역 동작은 어떤 조건에서 자동 허용할지?
