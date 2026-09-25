# Windows 호환성 결정 및 학습 기록

이 문서는 `AGENTS.md`에 항상 필요한 현재 규칙과 분리한 Windows 호환성의 결정 근거다.

## 결정

- POSIX 전용 `fcntl`과 `os.kill(pid, 0)`을 각 모듈에서 반복하지 않고 `src/ai_session_telegram/_procutil.py`의 `locked()`와 `is_alive()`를 사용한다.
- `hooks/_bridge_common.py`는 system Python으로 실행되는 독립 hook이므로 프로젝트 package를 import하지 않는다. 필요한 Windows lock 분기는 이 파일에 별도로 유지한다.
- 파일을 읽고 쓰는 운영 데이터와 메시지에는 명시적 UTF-8 encoding을 사용한다. 테스트는 Windows locale 차이를 피하려고 CI에서 `PYTHONUTF8=1`을 사용한다.
- Claude 주입은 `socket.AF_UNIX`가 없는 환경에서 명확한 `InjectError`를 반환한다. Codex 주입은 subprocess 기반이라 이 제약의 영향을 받지 않는다.
- 서비스 설치는 `serviceinstall.py`가 플랫폼별 adapter를 선택한다. Linux는 systemd template, macOS는 launchd, Windows는 Task Scheduler를 사용한다.

## 근거와 한계

GitHub Actions `windows-latest`가 encoding, `AF_UNIX`, process probe, service 명령의 문제를 발견했다. Windows 실제 장비에서의 end-to-end 검증은 아직 수행하지 않았으므로 CI matrix를 통과했다고 실제 운영 호환성이 완전히 증명되는 것은 아니다.

변경 시 `tests/test_procutil.py`, `tests/test_serviceinstall.py`, `tests/test_hookinstall.py`, `tests/test_cli.py`와 CI의 Windows job을 함께 확인한다.
