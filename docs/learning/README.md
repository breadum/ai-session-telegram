# Learning ledger

AI 작업의 실패·반려·오판·재작업을 다음 세션이 재사용할 수 있는 지식으로
기록한다. Telegram 대화나 모델 memory는 원본이 아니다.

각 기록에는 다음을 포함한다.

- 증상과 실패한 시도
- 근본 원인과 놓친 신호
- 틀린 가정
- 수정한 코드·문서·테스트
- 재발 방지 규칙 또는 승격한 acceptance criterion
- 남은 불확실성과 다음 검증 방법

반복 가능성이 확인되면 기록만 남기지 말고 regression test, AGENTS 불변식,
decision, operation runbook, spec 중 하나로 승격한다.

권장 파일명은 `YYYY-MM-DD-짧은-주제.md`다.
