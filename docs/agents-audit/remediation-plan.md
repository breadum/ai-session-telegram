# AGENTS.md 검수 — 수정 계획

## 1단계 — P1 계약 복구

대상: `AGENTS.md`

- stale Codex thread가 `CodexSessionGoneError`로 분류되면 topic·thread mapping·session runtime state를 정리한다는 규칙 추가
- `SessionEnd` 정상 경로와 stale-message 복구 경로를 구분
- Claude/Codex prompt role 판정 순서 추가:
  1. pending injection echo는 버림
  2. Claude peer/system echo는 버림
  3. 좁게 정의된 AI handoff는 `assistant`
  4. 나머지 실제 prompt는 `user`
- role과 실제 emoji(`🐮`, `🤖`, `🔔`, `⚠️`)의 원본 위치와 테스트 위치 기록

완료 기준:

- 관련 코드 경로가 모두 링크됨
- stale cleanup과 handoff 분류 테스트가 각각 명시됨
- false-positive를 피해야 한다는 제한이 기록됨

## 2단계 — 보안·검증 규칙 정리

- 실제 token-derived fragment를 AGENTS와 audit 문서에서 제거
- generic secret scan을 사용한다는 원칙으로 변경
- local 검증과 CI 검증을 분리해 기록:

```bash
uv run ruff check .
uv run pytest -q
```

CI acceptance:

- Ubuntu/macOS/Windows Python 3.12
- `PYTHONUTF8=1` on Windows
- ruff
- pytest
- Telegram token regex scan

## 3단계 — 역사 지식 분리

현재 AGENTS 후반의 Windows 장애 상세는 다음처럼 분리한다.

- AGENTS: 현재 지원 범위, 반드시 지킬 구현 규칙, 검증 명령
- `docs/decisions/`: 왜 `_procutil`, UTF-8 명시, `AF_UNIX` guard가 필요한지
- `docs/operations/`: 서비스 재시작, stale broker 확인, 운영 장애 대응

이동 후 AGENTS에는 원문 위치를 링크하고, 현재 동작과 직접 관련된 요약만 남긴다.

## 4단계 — cross-document drift 수정

- README의 `🧑` user 예시를 실제 `🐮`와 일치시킨다.
- topic icon color, legacy prefix migration, `titled` 보호 조건을 README 또는 AGENTS에 명확히 한다.
- 변경 후 `README.md`, `AGENTS.md`, 코드 상수를 대조한다.

## 적용 결과

이 remediation plan의 1~4단계는 이번 문서 변경에 반영했다. 후속 별도 review에서는 아래 최종 기준만 재확인한다.

- P1 finding 0건
- token-derived secret marker 0건
- README/AGENTS/코드의 role emoji와 topic naming 일치
- Windows historical detail은 별도 decision 문서로 분리

## 5단계 — 재검수와 PR

1. 수정 PR에서 `docs/agents-audit/`의 각 finding을 닫는다.
2. 각 finding에 코드·테스트·문서 근거를 링크한다.
3. `git diff --check`, ruff, pytest를 실행한다.
4. secret scan을 실행한다.
5. 별도 review에서 “새 agent가 AGENTS만 읽고 안전하게 첫 변경을 할 수 있는가”를 다시 판정한다.

## 최종 판정 기준

- P1 finding 0건
- AGENTS의 현행 규칙과 코드의 불일치 0건
- 핵심 lifecycle/role/security/operational rule마다 근거 경로 존재
- 역사적 상세가 핵심 지침을 압도하지 않음
- local test와 CI acceptance가 구분되어 있음
- README와 AGENTS의 사용자-facing 사실이 일치함
