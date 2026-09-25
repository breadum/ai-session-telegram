# 운영 지식

## broker가 오래된 코드를 실행하는 것처럼 보일 때

runtime 상태 디렉터리는 checkout 경로와 무관하게 `~/.ai-session-telegram` 하나를 공유한다. 두 checkout에서 broker를 동시에 시작하면 한쪽은 이미 실행 중인 broker 때문에 동작하지 않고, 다른 쪽은 이전 코드일 수 있다.

확인:

```bash
ps aux | grep ai_session_telegram.broker
uv run bridge status
uv run bridge logs -f
```

broker 코드를 변경한 뒤에는 플랫폼에 맞게 broker를 재시작한다. hook만 변경한 경우 hook은 다음 이벤트부터 다시 읽히므로 broker 재시작은 필요하지 않다.

## stale Codex session

Codex가 종료됐지만 `SessionEnd` hook이 기록되지 않은 경우, Telegram topic이 잠시 남을 수 있다. 해당 topic에 메시지가 들어와 `codex queue`가 `no thread named`/unknown-thread 오류를 반환하면 broker는 이를 transient retry가 아닌 stale session으로 판정하고 topic과 runtime routing state를 정리한다.

정리할 수 없는 일반 queue 실패(바이너리 없음, timeout 등)는 inbox에 보존되어 retry된다. 원인별 분류를 임의로 합치지 않는다.

## 변경 후 검증

```bash
uv run ruff check .
uv run pytest -q
```

Telegram token은 runtime config에만 존재해야 하며, 운영 로그·문서·fixture에 기록하지 않는다.
