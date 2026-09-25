# AGENTS.md 검수 — 발견 사항

**검수 기준일**: 2026-09-25

## 종합 판정

현재 `AGENTS.md`는 아키텍처 핵심과 과거 장애 대응을 상당히 잘 반영한다. 특히 hook/broker 경계, 파일 queue, pending marker, transcript race, Windows 대응은 코드와 근거가 연결되어 있다.

다만 최신 기능 변경이 즉시 반영되지 않은 부분과, 항상 읽는 규칙 문서에 역사적 상세가 과다한 문제가 있다. **현재 상태는 조건부 통과**로 평가한다. P0/P1 보안·데이터 손실 문제는 없지만, 다음 P1/P2 항목을 다음 문서 PR에서 해결해야 완전 통과로 승격할 수 있다.

## 발견 사항

### F-01 — 최근 stale Codex session 복구 규칙이 누락됨 — 해결

- **등급**: P1
- **상태**: 누락
- **근거**: `src/ai_session_telegram/codex_inject.py`의 `CodexSessionGoneError`, `broker._cleanup_gone_codex_session()`, `tests/test_broker.py`의 stale topic 테스트
- **문제**: AGENTS는 SessionEnd hook을 통한 Codex topic 삭제만 설명한다. SessionEnd가 누락되고 Telegram 메시지가 뒤늦게 들어온 경우, `no thread named` 오류를 stale session으로 판정해 topic·mapping·pending/inbox를 정리하는 현재 계약이 문서에 없다.
- **영향**: 다음 agent가 이 동작을 일반 retry로 되돌리거나, 종료된 topic에 메시지를 계속 쌓을 수 있다.
- **조치**: runtime state와 Codex failure classification 절에 stale-thread 정리 규칙·로그·테스트를 추가한다.

### F-02 — AI handoff prompt의 `assistant` role 분류가 문서에 없음 — 해결

- **등급**: P1
- **상태**: 누락
- **근거**: `hooks/user_prompt_submit.py`, `hooks/codex_user_prompt_submit.py`, `tests/test_hooks.py`, broker `_ROLE_PREFIX`
- **문제**: UserPromptSubmit은 사람 입력과 AI 위임 지시를 같은 event로 전달한다. 현재는 좁은 handoff heuristic을 통해 AI 지시를 `assistant`로 mirror하지만, AGENTS에는 이 예외와 false-positive를 피해야 하는 이유가 없다.
- **영향**: 후속 수정에서 모든 prompt를 `user`로 되돌려 `🐮` 오표시가 재발하거나, heuristic을 과도하게 넓혀 실제 사용자 메시지를 `🤖`로 표시할 수 있다.
- **조치**: role/emoji 계약에 “pending echo, peer injection, AI handoff, real user”의 우선순위와 테스트 경로를 명시한다.

### F-03 — token fragment를 문서에 직접 지정한 secret scan 규칙 — 해결

- **등급**: P1
- **상태**: 개선 필요
- **근거**: 기존 `AGENTS.md` Secrets 절의 token-derived marker, `.github/workflows/ci.yml`의 generic token regex
- **문제**: 실제 bot token의 앞부분을 문서에 넣어 scan하도록 지시한다. 전체 secret은 아니지만, secret-derived marker를 공용 문서에 남기는 방식이며 token이 바뀌면 규칙도 낡는다.
- **영향**: secret 관리 방식이 특정 운영값에 결합되고, 문서가 유출 방지 규칙처럼 오해될 수 있다.
- **조치**: AGENTS에서는 `git grep`에 실제 token fragment를 넣지 말고 CI의 generic regex와 `git diff --cached` secret scan을 원칙으로 설명한다. 실제 값은 환경 밖에서만 사용한다.

### F-04 — 역사적 Windows 장애 기록이 핵심 규칙을 가림 — 해결

- **등급**: P2
- **상태**: 구조 개선
- **근거**: `AGENTS.md` 후반의 Windows 변경·CI 발견 상세 약 70줄
- **문제**: 왜 현재 규칙이 필요한지는 잘 남아 있지만, 모든 session이 읽는 AGENTS에 해결된 장애의 긴 서술이 포함돼 있다.
- **영향**: 새 agent가 현재 반드시 지켜야 할 규칙을 놓치고, 문서 갱신 시 역사 설명과 현행 계약이 함께 충돌할 가능성이 커진다.
- **조치**: AGENTS에는 현재 규칙·지원 범위·검증 명령만 남기고, 장애 원인·대안·미검증 사항은 `docs/decisions/` 또는 `docs/operations/`로 이동한다.

### F-05 — CI와 플랫폼 검증 범위가 AGENTS에 명시되지 않음 — 해결

- **등급**: P2
- **상태**: 부분 반영
- **근거**: `.github/workflows/ci.yml`, `pyproject.toml`, AGENTS Dev workflow
- **문제**: local `ruff`/`pytest`는 적혀 있지만 CI가 Ubuntu/macOS/Windows matrix, `PYTHONUTF8`, secret scan을 수행한다는 계약은 빠져 있다.
- **영향**: agent가 Linux local pass만으로 완료 판단하고 Windows branch 또는 secret scan을 놓칠 수 있다.
- **조치**: 검증 절에 local 명령과 CI acceptance를 구분해 추가한다.

### F-06 — README와 실제 role emoji 용어 불일치 — 해결

- **등급**: P2
- **상태**: 코드-문서 불일치
- **근거**: `README.md`의 `🧑` 예시와 `broker._ROLE_PREFIX`의 실제 `🐮`
- **문제**: 사용자 문서 예시가 현재 표시 규칙과 다르다. AGENTS 검수 자체에서 발견되는 cross-document drift다.
- **영향**: 사용자와 agent가 user role의 기대 표시를 다르게 이해한다.
- **조치**: README의 예시를 현재 `🐮`로 고치거나, user emoji를 명시적 상수 계약으로 문서화한다.

### F-07 — topic migration의 보호 조건이 문서에 없음 — 해결

- **등급**: P2
- **상태**: 누락
- **근거**: `broker._migrate_codex_topic_names()`, registration resume migration, `titled` field
- **문제**: legacy `[codex]` prefix 제거는 자동 제목에만 적용하고 사용자가 지정한 `/title`·AI title은 보존한다. 이 보호 조건이 AGENTS에 없다.
- **영향**: 후속 agent가 migration을 단순 rename으로 바꿔 사용자의 topic 제목을 덮을 수 있다.
- **조치**: topic naming 절에 `titled` guard와 startup/resume migration의 범위를 기록한다.

## 통과한 영역

- broker만 Telegram API를 호출한다는 단일 소유자 규칙
- hook의 stdlib-only/non-blocking 경계
- Claude UDS와 Codex queue의 차이
- pending marker를 통한 echo 중복 방지
- transcript settle/debounce와 tool-only turn 처리
- runtime secret 위치와 fixture에 실제 token을 넣지 않는 원칙
- service 설치 및 Windows의 알려진 제한
