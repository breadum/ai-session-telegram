# AI handoff 출처 식별 spec

## 문제

`UserPromptSubmit` hook은 사람이 쓴 프롬프트와 AI가 agent에게 전달한 지시를 같은 모양으로 받는다. 본문 문구로 작성자를 추정하면 false positive와 false negative가 생긴다.

## 목표와 범위

Claude/Codex의 agent dispatch hook에서 tool call이라는 출처를 확인해 agent 지시를 `assistant`로 기록한다. 본문 내용에 따른 작성자 추정은 제거한다. 범위는 Claude `Agent`/`Task`, Codex `Agent` 도구 호출이다. 외부 프로그램이 직접 시작하는 CLI prompt는 이 dispatch hook을 거치지 않으므로 자동 분류 대상이 아니다.

## 동작 계약

- `PreToolUse`에서 세션이 등록되어 있고 `tool_input.prompt` 또는 `tool_input.message`가 있을 때, prompt를 `assistant`로 outbox에 기록하고 pending marker를 남긴다.
- 같은 세션에서 뒤따르는 `UserPromptSubmit` echo는 marker와 대응하면 한 번 소비한다. marker 없는 일반 입력은 내용과 관계없이 `user`다.
- Agent dispatch marker와 Codex broker injection은 exact match를 쓴다. Claude broker injection은 Claude가 원문을 감싸므로 substring match를 쓴다.
- 기존 pending marker TTL 60초와 파일 잠금을 재사용한다. hook은 non-blocking 동작을 유지한다.

## 실패와 제약

- dispatch event 또는 prompt가 없거나 세션이 미등록이면 기록을 생략한다. 사용자 prompt hook은 이를 `user`로 처리한다.
- hook 계약에 dispatch ID가 없으므로 dispatch echo는 세션 ID와 exact prompt로 연결한다. 동일 세션에서 동일한 전체 prompt가 pending TTL 안에 새 사용자 입력으로 다시 들어오면 echo로 소비될 수 있다.
- peer/system echo를 막는 Claude backstop은 기존과 같이 유지한다.

## Acceptance criteria

- Agent/Task tool dispatch prompt는 `assistant`로 한 번만 기록된다.
- dispatch 기록 없는 프롬프트는 어떤 문구여도 `user`로 기록된다.
- 같은 내용의 확장된 사용자 문장이 dispatch marker와 일치하지 않는다.
- Claude와 Codex hook 및 installer matcher 설정을 검증한다.

## 구현 및 검수 흐름

Codex가 구현·검증하고 Claude가 diff를 독립 검수한다. finding을 수정한 뒤 PR을 준비한다. merge 여부는 사용자가 판단한다.

## 승인

- 상태: 사용자 승인
- 승인자/일자: 사용자 / 2026-09-25
