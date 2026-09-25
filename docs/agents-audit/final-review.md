# AGENTS.md 최종 검수

**검수 기준일**: 2026-09-25
**기준 커밋**: `6bf48c7` (`origin/main`, PR #5 merge)
**검수 범위**: PR #5의 AGENTS 정합성 remediation. 현재 열려 있는 PR #4의 Codex handoff 기능 변경은 별도 범위다.

## 최종 판정

**통과**

`AGENTS.md`는 현재 레포의 핵심 실행 경로, 세션 lifecycle, Claude/Codex 주입 차이, role 표시, stale session 복구, topic migration, secret 규칙, 플랫폼 검증 범위를 반영한다. P0/P1 finding은 남아 있지 않다.

## 기준별 확인

| 기준 | 판정 | 근거 |
|---|---|---|
| 주요 실행 경로 설명 | 통과 | `pyproject.toml`, `cli.py`, `broker.py`, hooks, service 경로와 대조 |
| broker/Telegram 단일 소유자 | 통과 | `AGENTS.md` architecture 2절, `broker.py`, `telegram.py` |
| hook non-blocking·stdlib 경계 | 통과 | architecture 1절, `hooks/_bridge_common.py`, subprocess hook tests |
| Claude/Codex injection 계약 | 통과 | architecture 3절, `claude_inject.py`, `codex_inject.py` |
| runtime file queue 계약 | 통과 | architecture 4절, `paths.py`, broker 처리 순서 |
| prompt role/emoji 규칙 | 통과 | architecture 6~7절, `_ROLE_PREFIX`, Claude/Codex hook tests |
| stale Codex session 복구 | 통과 | architecture 8절, `CodexSessionGoneError`, stale cleanup tests |
| topic 제목 migration 보호 | 통과 | architecture 9절, `titled` guard와 migration tests |
| SessionEnd·topic cleanup | 통과 | `end/` 계약, `_process_end`, Codex cleanup tests |
| secret 취급 | 통과 | generic scan 원칙, runtime config/session token 경계, CI regex scan |
| CI·플랫폼 검증 | 통과 | CI 3 OS matrix, ruff/pytest/secret scan 및 Windows decision 문서 |
| 운영 복구 지식 | 통과 | `docs/operations/README.md` stale broker/session 절차 |
| historical knowledge 분리 | 통과 | `docs/decisions/windows-compatibility.md`와 AGENTS 요약 링크 |
| CLAUDE 공유 규칙 단일화 | 통과 | `CLAUDE.md`는 `@AGENTS.md`만 포함 |

## 실행 검증

- `git diff --check`: 통과
- `uv run ruff check .`: 통과
- `uv run pytest -q`: 통과
- token-derived marker 검색: 결과 없음
- merged `origin/main`에서 위 문서·경로·코드 근거 확인

## 남은 비차단 관찰 사항

- `AGENTS.md`는 여전히 항상 읽는 문서로는 긴 편이다. 향후 반복되는 장애 회고가 추가되면 `docs/decisions/` 또는 `docs/operations/`로 먼저 분리한다.
- 사용자 설치·CLI 사용법의 원본은 `README.md`다. AGENTS에 설치 설명을 중복해서 추가하지 않는다.
- PR #4의 Codex handoff 변경은 이 audit의 통과 근거에 포함하지 않고 별도 기능 review 대상으로 유지한다.

## 다음 단계

이 audit remediation은 종료한다. 이후 새 기능이나 규칙 변경은 다음 순서를 따른다.

1. spec/요구사항과 영향 범위를 먼저 기록한다.
2. 관련 코드·테스트·AGENTS 계약을 함께 갱신한다.
3. 검증 결과와 실패 학습을 남긴다.
4. 별도 PR에서 사용자 확인을 받은 뒤 merge한다.
