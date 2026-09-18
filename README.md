# ai-session-telegram

텔레그램에서 Claude Code / Codex CLI 세션을 돌린다. 세션마다 그룹 안에 방(토픽)이
하나 생기고, 프롬프트와 응답이 거기로 오간다. 자리에 없어도 폰으로 이어서 작업할
수 있다.

## 특징

텔레그램의 포럼(Topics) 기능을 그대로 활용한다. 세션마다 토픽이 하나씩 생기니
여러 작업을 한 그룹 안에서 따로 들여다볼 수 있고, 자리를 비운 사이에도 폰으로
이어서 진행한다.

- **세션 하나에 토픽 하나.** 세션을 여러 개, 심지어 Claude Code와 Codex를 섞어서
  동시에 돌려도 대화가 뒤섞이지 않는다. Claude 세션은 토픽 이름도 대화 맥락을 보고
  스스로 붙인다. 토픽 아이콘 색도 Claude(코랄)/Codex(연노랑)로 갈라서, 이름이
  나중에 바뀌어도 목록에서 한눈에 구분된다.
- **어디서든 이어서 작업한다.** 데스크탑에서 띄운 세션을 이동 중에 폰으로 확인하고
  지시한다. 마이그레이션이나 대규모 리팩터처럼 시간이 걸리는 작업을 놓치지 않고
  따라갈 수 있다.
- **터미널에 매여 있지 않다.** 터미널이든 Orca든 Claude Desktop이든, 어디서 시작한
  세션이든 붙는다. tmux나 PTY 우회가 필요 없다. Claude Code 2.x가 세션마다 여는
  소켓, Codex CLI의 `codex queue`를 그대로 쓴다.
- **설정이 간단하다.** `bridge setup`, `bridge install-hooks`, `./service/install.sh`
  세 번이면 끝난다. 웹 서버도 데이터베이스도 없이, 데몬 하나와 몇 개의 훅이
  파일을 주고받는다.
- **텔레그램에서 읽기 좋다.** 마크다운은 텔레그램 서식으로 옮겨지고 표는 정렬을
  맞춘다. 세션이 작업 중인지, 입력을 기다리는지도 함께 표시된다.
- **가볍고 조용하다.** 봇 토큰은 로컬 설정 파일에만 두고, 훅은 표준 라이브러리만
  쓴다. 바깥으로 나가는 것은 텔레그램 API 호출뿐이다.

토픽 하나는 대체로 이런 모습이다.

```
🧑  로그인하면 홈이 아니라 login 페이지로 리다이렉트돼. 봐줘
🤖  auth 미들웨어가 세션 없을 때 /login으로 보내는데, 토큰 갱신 중인
    요청도 "세션 없음"으로 걸립니다. 갱신 핸들러를 먼저 태우면 됩니다.
🧑  그렇게 고쳐줘
🔧  작업 중 (14s)
🤖  middleware/auth.ts:23 에 갱신 토큰 예외를 넣었습니다. 로컬에서
    로그인하니 홈 그대로 유지됩니다.
```

## 요구 사항

- Claude Code 2.x (`[uds-messaging]` 소켓이 있는 버전) 그리고/또는 Codex CLI
  (`codex queue` 서브커맨드가 있는 버전)
- [uv](https://docs.astral.sh/uv/)
- Topics를 켠 텔레그램 슈퍼그룹과 봇 하나

## 설치

### 1. 텔레그램 봇과 그룹 (처음 한 번)

1. [@BotFather](https://t.me/BotFather)에서 `/newbot`으로 봇을 만들고 토큰을 받는다.
2. 그룹을 만들고 Topics를 켠다.
   - 텔레그램 앱에서 새 그룹을 만든다. 최소 한 명 이상 같이 초대해야 생성되니
     (나 혼자 있는 채팅으로는 그룹 자체가 안 만들어진다), 이때 1번에서 만든 봇을
     바로 초대해 넣는다.
   - 그룹 정보 화면 → 편집(연필 아이콘) → 아래쪽 "Topics" 토글을 켠다. 이 토글을
     켜는 순간 일반 그룹이 **자동으로 슈퍼그룹으로 전환**된다 — 따로
     "슈퍼그룹 만들기" 메뉴는 없다.
3. 봇을 관리자로 올린다. 관리자 권한 화면에서 "주제 관리(Manage Topics)"를
   직접 켜야 한다. 관리자여도 기본은 꺼져 있다.
4. 봇이 관리자가 된 다음 그룹에 아무 메시지나 하나 보낸다. 그 전 메시지는 봇이
   못 본다.

### 2. 브리지 설치

저장소를 받아 의존성을 깐다.

```bash
git clone <이 저장소>
cd ai-session-telegram
uv sync
```

그다음 세 가지를 등록한다.

```bash
uv run bridge setup           # 봇 토큰을 물어보고 ~/.ai-session-telegram/config.json에 저장한다
uv run bridge install-hooks   # Claude Code 훅을 ~/.claude/settings.json에 추가한다 (원본은 자동 백업)
```

세 번째(브로커를 상시 실행 서비스로 올리기)는 OS마다 다르다.

```bash
./service/install.sh          # Linux: systemd --user 서비스로 등록
uv run bridge install-service # macOS: launchd 유저 에이전트로 등록 (~/Library/LaunchAgents)
uv run bridge install-service # Windows: 작업 스케줄러에 로그온 트리거로 등록
```

> Windows는 이 저장소에서 실제 Windows 머신으로 검증된 적은 없다 (개발·테스트가 전부
> Linux에서 이뤄짐). `install-service`는 등록과 동시에 한 번 바로 실행도 시키지만, 문제가
> 있으면 [CLAUDE.md](CLAUDE.md)의 "Running as a service"를 참고하거나 이슈로 알려달라.

Codex CLI 세션도 같은 그룹에 붙이려면 훅을 하나 더 등록한다 (`--agent all`이면 둘 다).

```bash
uv run bridge install-hooks --agent codex   # ~/.codex/hooks.json에 추가
```

Codex는 새로 추가된 훅을 처음 한 번은 신뢰해야 실행한다. `codex --dangerously-bypass-hook-trust`로
띄우거나, 인터랙티브 신뢰 프롬프트에서 승인한다.

마지막으로 `~/.claude/settings.json`에 한 줄을 더한다. 이 설정이 없으면 브로커가
넣은 메시지를 Claude Code가 보류하고 세션까지 전달하지 않는다. 배경은
[권한](#권한)에 있다.

```json
"crossSessionInbound": "accept"
```

> 서비스로 올리지 않고 잠깐만 써 볼 때는 `uv run bridge start` / `stop`을 쓴다 (macOS에서도 됨).
> 저장소를 다른 경로로 옮겼다면 옛 위치에서 `bridge uninstall-hooks`를 한 뒤 (macOS는
> 서비스도 `bridge uninstall-service`로 먼저 내린다), 새 위치에서 `uv sync && uv run
> bridge install-hooks && ./service/install.sh`(macOS는 `bridge install-service`)를
> 다시 실행한다 (Codex 훅도 등록해뒀다면 `install-hooks`/`uninstall-hooks`에
> `--agent codex`나 `--agent all`을 붙여야 한다 — 기본값은 `claude`뿐이다).

### 3. 첫 세션

```bash
claude --dangerously-skip-permissions
```

그룹에 `<디렉터리>-<세션ID>` 토픽이 생긴다. 이 플래그가 필요한 이유는
[권한](#권한)에 있다.

Codex는 `codex --dangerously-bypass-approvals-and-sandbox`(또는 `-a never`처럼
덜 극단적인 조합)로 띄운다. 인터랙티브 세션이 **첫 프롬프트를 보낼 때** 토픽이
생긴다 — Claude Code와 달리 세션 시작 시점이 아니라 조금 늦게 뜨는 게 정상이다.

## 사용

프롬프트(`🧑`)와 응답(`🤖`)이 토픽에 그대로 올라온다. 마크다운은 텔레그램 서식으로
바뀌고 표는 폭을 맞춘 고정폭 블록이 된다.

토픽에 메시지를 쓰면 몇 초 안에 세션에 들어간다. 세션이 작업 중이면 현재 턴이
끝난 뒤에 처리된다고 알려준다.

세션이 입력을 기다리면(`AskUserQuestion` 같은 경우) `🔔`로 표시된다. 답은 토픽에
그냥 쓰면 된다.

### 토픽 명령

| 명령 | 하는 일 |
|---|---|
| `/status` | 세션 상태, 작업 중 여부, 연결 방식(소켓/`codex queue`), 작업 디렉터리 |
| `/title <text>` | 토픽 이름 바꾸기. Claude 세션은 대화 제목으로 자동으로도 바뀐다 (Codex는 아직 자동 미지원 — 디렉터리 이름이 기본값) |
| `/sessions` | 전체 세션 목록 |
| `/exit` | 이 토픽 삭제. 로컬 세션 기록은 남는다 |
| `/help` | 명령 목록 |

`/exit`는 토픽만 지운다. 끝난 세션 기록까지 정리하려면 `uv run bridge prune`을
쓴다. `--all`은 전부, `-y`는 확인 생략.

## 설정

`bridge setup`이 만드는 `~/.ai-session-telegram/config.json`:

| 키 | 기본값 | 뜻 |
|---|---|---|
| `bot_token` | – | 텔레그램 봇 토큰 |
| `chat_id` | – | 슈퍼그룹 ID |
| `delete_topic_on_end` | `false` | 터미널에서 세션이 끝날 때 토픽도 지울지 |

환경 변수 `AI_TG_BOT_TOKEN`, `AI_TG_CHAT_ID`,
`AI_TG_DELETE_TOPIC_ON_END`로 덮어쓸 수 있다.

## 브로커 관리

```bash
uv run bridge status      # 브로커와 세션 상태
uv run bridge logs -f     # 로그
uv run bridge prune       # 끝난 세션 정리
```

서비스로 돌리는 중이면 `start` / `stop` 대신 systemd(Linux) / launchd(macOS) /
작업 스케줄러(Windows)를 쓴다.

```bash
systemctl --user restart ai-session-telegram.service   # Linux: 브로커 코드를 고친 뒤
journalctl --user -u ai-session-telegram.service -f
./service/uninstall.sh                                 # Linux: 서비스만 제거

launchctl kickstart -k gui/$(id -u)/ai-session-telegram # macOS: 브로커 코드를 고친 뒤
uv run bridge logs -f                                   # macOS/Windows: 로그는 이걸로
uv run bridge uninstall-service                         # macOS/Windows: 서비스만 제거

schtasks /End /TN ai-session-telegram                   # Windows: 브로커 코드를 고친 뒤
schtasks /Run /TN ai-session-telegram
```

훅은 매번 새로 읽히니 훅만 고쳤을 때는 재시작하지 않아도 된다.

## 권한

### Claude Code

브로커가 넣는 메시지는 세션에 peer 메시지로 도착한다. 사람이 친 프롬프트가 아니라
다른 Claude 세션이 보낸 것으로 취급된다. 그래서 무인으로 돌리려면 두 가지가
필요하다.

**`crossSessionInbound: accept`** 를 `~/.claude/settings.json`에 넣는다. 기본값이면
프롬프트를 건너뛰는 세션에 낯선 발신자가 메시지를 넣지 못한다. Claude Code가 그
메시지를 보류한다. `accept`면 바로 전달된다.

**`--dangerously-skip-permissions`** 로 세션을 시작한다. 신뢰 폴더에 `acceptEdits`
를 걸어도 된다. peer 메시지는 도구 권한 창을 대신 눌러 주지 못하므로, 그 창이
아예 안 뜨게 해야 한다.

작업 지시는 정상으로 처리되지만 권한이나 설정을 바꾸는 요청은 신뢰도가 낮아
세션이 거절할 수 있다.

### Codex CLI

**훅 신뢰.** `bridge install-hooks --agent codex`로 막 추가한 훅은 Codex가 한 번
승인해야 실행된다. `codex --dangerously-bypass-hook-trust`로 띄우거나 인터랙티브
신뢰 프롬프트에서 승인한다.

**승인 우회.** Claude Code의 peer 메시지처럼, `codex queue`로 넣은 메시지도 도구
권한 창을 대신 눌러 주지 못한다. `codex --dangerously-bypass-approvals-and-sandbox`
로 띄우거나, 덜 극단적으로는 `-a never`(승인은 안 묻되 샌드박스는 유지)로 띄운다.

## 작동 방식

훅은 세션 이벤트마다 `~/.ai-session-telegram/` 아래에 파일 하나를 쓰고 바로 끝난다.
표준 라이브러리만 쓰고 블로킹하지 않는다.

브로커는 텔레그램과 이야기하는 유일한 프로세스다. 토픽을 만들고 응답을
내보내고 세션에 메시지를 넣는다 — 에이전트 종류에 따라 방법이 다르다.

Claude Code 2.x는 세션마다 유닉스 소켓을 연다(`$CLAUDE_CODE_MESSAGING_SOCKET`,
`$CLAUDE_CODE_MESSAGING_TOKEN`). `SessionStart` 훅이 이 값을 적어 두면 브로커가
거기 붙어 프롬프트 큐에 메시지를 넣는다.

Codex CLI는 세션마다 소켓을 안 준다 — 모든 세션이 로컬 데몬 하나를 공유해서,
브로커는 그냥 `codex queue --thread <세션ID> --message <텍스트>`를 부른다. 대신
Claude와 달리 Codex는 주입된 메시지를 타이핑한 것과 구분할 방법이 없어서, 브로커가
방금 넣은 텍스트를 따로 기록해뒀다가 훅이 그걸 보고 다시 mirror하지 않도록 한다.

더 자세한 구조와 기여 규칙은 [`CLAUDE.md`](CLAUDE.md)에 있다.

## 문제 해결

**`is_forum: None` 또는 `the chat is not a forum`**
그룹에 Topics가 안 켜져 있다. 그룹 편집에서 켠다.

**`not enough rights to create a topic`**
봇에게 "주제 관리" 권한이 없다. 그룹 관리자 설정에서 봇에게 켜 준다.

**`setup` 중에 `0 update(s)`**
봇이 아직 관리자가 아니거나, 관리자가 되기 전 메시지만 있다. 관리자로 만든 뒤
새 메시지를 보낸다.

**토픽에 써도 세션에 안 들어간다 (Claude)**
`bridge status`로 브로커가 떠 있는지 본다. `/status`의 소켓 값이 `missing`이면
세션이 재시작돼 pid가 바뀐 것이니, 세션에 프롬프트를 한 번 주면 다시 잡힌다.
`unknown`이면 그 세션에 `[uds-messaging]` 소켓이 없어 미러 전용이다. 세션
트랜스크립트에 `Held peer message`가 보이면 `crossSessionInbound: accept`가
빠진 것이다.

**토픽에 써도 세션에 안 들어간다 (Codex)**
`/status`가 `kind: claude`로 나오면 (없어야 할) 소켓/토큰 로직을 타고 있다는
뜻이니, `bridge`를 최신 코드로 재시작한 뒤 그 세션에 프롬프트를 한 번 더 줘서
등록을 새로 태운다 (SessionStart가 재등록 때 `kind`를 채워 넣는다). 그래도
안 되면 브로커를 도는 유저/셸의 `PATH`에 `codex` 바이너리가 있는지, 훅이
신뢰됐는지(`--dangerously-bypass-hook-trust`) 확인한다.

**응답이 그룹의 General 토픽에 뜬다**
그 세션이 `bridge install-hooks` 전에 시작됐다. 세션을 새로 연다.

**`broker already running`인데 진짜 죽어있다**
죽은 pidfile이 남은 것이다. `~/.ai-session-telegram/state/broker.pid`를 확인하고
실제로 안 돌고 있으면 지운다.

**이 저장소를 여러 위치에 체크아웃해뒀다**
`~/.ai-session-telegram`는 체크아웃 경로와 무관하게 공유되는 전역 상태 디렉터리라,
브로커는 **어느 체크아웃에서 먼저 떴든 딱 하나만** 살아있어야 한다 (아니면
`getUpdates` offset을 두 프로세스가 다투게 된다). `ps aux | grep ai_session_telegram.broker`로
여러 개 떠 있는지 확인하고, systemd가 관리하지 않는 쪽은 정지시킨다.

## 개발

```bash
uv sync && uv run ruff check . && uv run pytest
```

규칙은 [`CLAUDE.md`](CLAUDE.md).
