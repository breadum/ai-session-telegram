# AGENTS.md 검수 — 레포 사실 목록

**검수 기준일**: 2026-09-25

## 레포 개요

`ai-session-telegram`은 Claude Code와 Codex CLI 세션을 Telegram forum topic에 연결하는 Python 3.12 프로젝트다. broker만 Telegram Bot API를 호출하고, hook은 런타임 디렉터리에 파일을 남긴 뒤 종료한다.

근거:

- `pyproject.toml`: `bridge` CLI, Python `>=3.12`, `httpx`, pytest/ruff
- `src/ai_session_telegram/broker.py`: 단일 broker loop, registration/update/outbox/end 처리
- `src/ai_session_telegram/telegram.py`: Telegram API client
- `README.md`: 사용자 설치·운영·권한 모델

## 실행 경로와 계약

| 영역 | 실제 원본 | AGENTS 반영 | 검수 메모 |
|---|---|---|---|
| CLI 진입점 | `pyproject.toml`, `src/ai_session_telegram/cli.py` | 부분 반영 | `bridge setup/start/status/prune/install-hooks`의 상세는 README에만 있음 |
| broker lifecycle | `src/ai_session_telegram/broker.py` | 반영 | registration, outbox, inbox, end, update 순서가 설명됨 |
| Telegram API 단일 소유자 | `broker.py`, `telegram.py` | 반영 | 핵심 불변식으로 기록됨 |
| Claude hook | `hooks/session_start.py`, `user_prompt_submit.py`, `stop.py`, `session_end.py`, `notification.py` | 부분 반영 | socket, pending, peer echo는 반영. AI handoff role heuristic은 누락 |
| Codex hook | `hooks/codex_*.py` | 부분 반영 | queue, pending, SessionEnd는 반영. stale-thread 정리와 handoff heuristic은 누락 |
| hook 공통 계약 | `hooks/_bridge_common.py` | 반영 | stdlib-only, 파일 queue, busy/pending, transcript settle이 설명됨 |
| Claude injection | `claude_inject.py` | 반영 | UDS auth/frame/pending 계약이 설명됨 |
| Codex injection | `codex_inject.py` | 부분 반영 | `codex queue`와 pending은 반영. `CodexSessionGoneError`의 stale cleanup은 누락 |
| runtime state | `src/ai_session_telegram/paths.py`, broker | 반영 | register/session/outbox/inbox/busy/end/pending가 설명됨 |
| role rendering | `broker._ROLE_PREFIX`, `render.py` | 부분 반영 | user/assistant/event 개념은 있으나 실제 emoji와 AI handoff 분류 규칙은 불완전 |
| topic naming | `broker.ICON_COLOR`, registration/migration | 반영 | icon color와 legacy prefix migration은 최신 코드 확인 필요 |
| session end | `codex_session_end.py`, `broker._process_end` | 반영 | Codex 자동 삭제, Claude 설정 기반 동작이 기록됨 |
| stale Codex session | `CodexSessionGoneError`, broker cleanup | 누락 | 최근 장애 대응이 AGENTS에 없음 |
| rendering/retry | `render.py`, `telegram.py` | 반영 | HTML fallback, table/Markdown 변환이 설명됨 |
| service installation | `service/*`, `serviceinstall.py` | 반영 | Linux/macOS/Windows 경로와 제한이 설명됨 |
| hook installation | `hookinstall.py` | 부분 반영 | 설정 파일과 trust는 설명되나 현재 hook map 전체를 한눈에 보여주지 않음 |
| CI/검증 | `.github/workflows/ci.yml`, `pyproject.toml` | 부분 반영 | local lint/test는 있음. 3 OS matrix와 secret scan은 명시되지 않음 |
| secrets | `config.py`, runtime state, CI | 반영 | token/messaging token 취급이 설명됨. 특정 실제 token fragment를 문서에 넣은 방식은 재검토 필요 |

## 현재 검증 근거

- `uv run ruff check .`: 통과
- `uv run pytest -q`: 통과
- 테스트 범위: broker, hooks subprocess, Codex/Claude injection, rendering, Telegram client, CLI, serviceinstall, Windows process branches
- CI: Ubuntu/macOS/Windows Python 3.12 matrix, ruff, pytest, Telegram token regex scan

## 문서 역할 분리 판단

- `AGENTS.md`: 반드시 지켜야 하는 불변식·실패 시 행동·검증 명령을 둔다.
- `README.md`: 설치·사용자 운영·권한 설정을 둔다.
- 코드 docstring/주석: 구현 세부와 직접적인 계약을 둔다.
- 별도 `docs/decisions/` 또는 `docs/operations/`: 해결된 장애의 원인·대안·운영 회고를 둔다.

현재 AGENTS의 Windows 장애 서술은 유용한 근거지만, 항상 읽는 규칙 문서에 비해 역사적 상세가 많다. 규칙과 learning/incident 기록을 분리할 후보로 분류한다.
