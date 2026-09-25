# AGENTS.md 개발 철학 반영 spec

> **상태**: 사용자 승인 반영 — 자동 삭제 코드 파일럿 검증 중.
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

기능 변경은 크기와 관계없이 먼저 간단한 spec을 작성하고 사용자의 승인을 받은
뒤 구현한다. 단순한 변경은 한 줄짜리 문제와 acceptance criterion으로 충분하지만,
동작·계약·운영 결과가 바뀌는 작업은 다음 항목을 포함한다.

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
| 실패와 학습 | `docs/learning/` |
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
→ AI 자체 spec review
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
- **기능 변경**: 코드 동작·계약이 바뀌면 크기와 관계없이 spec을 필수로 한다. 단순한
  변경도 문제와 acceptance criterion을 최소 한 줄씩 남긴다.
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

- [ ] 모든 기능 변경은 크기와 관계없이 spec 승인 전 구현하지 않는다는 규칙이 있다.
- [ ] 사용자와 AI의 책임 경계가 명시되어 있다.
- [ ] 결정·계약·장애·학습·handoff의 저장 위치가 명시되어 있다.
- [ ] broker/hook/runtime state 특성에 맞는 딥인터뷰 질문이 포함되어 있다.
- [ ] 실패를 regression test/decision/runbook/spec로 승격하는 기준이 있다.
- [ ] 세션 시작·종료 시 읽고 남길 산출물이 정의되어 있다.
- [ ] 문서 규칙이 현재 코드의 PR·테스트·secret 정책과 충돌하지 않는다.
- [ ] `CLAUDE.md`는 계속 `@AGENTS.md`만 참조한다.

## 5. 종료 세션 자동 삭제 정책 제안

세션과 Telegram topic 삭제는 비가역적이므로 다음 조건을 모두 만족할 때만 자동
허용한다.

1. **명시적 종료**: 해당 session id의 `SessionEnd`/`end` 기록이 확인되었거나,
   Codex queue가 해당 thread가 존재하지 않는다는 확정 오류를 반환한다.
2. **동일 세션 검증**: 삭제 대상 topic id와 session record의 id/thread mapping이
   일치한다. 다른 세션의 topic을 추정해 삭제하지 않는다.
3. **대기 데이터 처리**: `pending`, `inbox`, `outbox`는 정상 처리하거나,
   명시적 종료·확정적 stale 판정 뒤 재시도하지 않도록 정리한다. 삭제 전에
   조용히 유실하지 않으며, 정리 사실과 근거를 로그로 남긴다. 현재 정책에서는
   `busy/<sid>` 존재 여부를 자동 삭제 조건으로 사용하지 않는다.
4. **일시 장애 제외**: 네트워크 오류, timeout, rate limit, broker 재시작,
   일시적인 hook 누락만으로는 삭제하지 않는다. 재시도 가능한 상태로 남긴다.
5. **감사 가능성**: 삭제 전 session id, topic id, 근거, 시각을 운영 로그에 남기고
   삭제 연산은 idempotent하게 만든다.

권장 실행 규칙은 `SessionEnd`에서 agent별 설정을 따른다. Codex는 확정적인
unknown-thread 오류가 stale 상태의 증거이므로 자동 삭제하고, Claude는
`delete_topic_on_end`가 켜진 경우에만 명시적 종료 시 삭제한다. 조건이 애매하면
삭제하지 않고 운영 알림과 learning 기록을 남긴다. 이 정책은 비가역 동작이므로
사용자가 최종 승인한 뒤 코드 계약으로 승격한다.

## 6. 사용자 결정 반영

- 모든 기능 변경에 간단하더라도 spec을 요구한다.
- spec 최종 승인자는 사용자다. AI는 구현 전 자체 검토와 질문을 수행한다.
- 실패와 학습은 공통 `docs/learning/`에 누적한다.
- 메시지 분류가 애매한 상태는 정상 동작으로 취급하지 않는다. 분류 불변식 위반은
  버그로 기록하고 regression test로 승격한다.
