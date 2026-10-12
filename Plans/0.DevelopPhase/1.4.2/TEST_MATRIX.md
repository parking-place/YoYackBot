# 1.4.2 검증 목록

총 **5단계·10검사**, 계획 게시 시점의 **모든 결과는 NOT_RUN**이다. 기준은 `v1.4.1c`(`fbd2f49`)이다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T142-P1-A` | [P1](01-execution-ranking.md) | LXC 합성 | 처형 기록·실행자·사유 없음·시체 시간·정리·백업 제외 | NOT_RUN |
| `T142-P1-B` | [P1](01-execution-ranking.md) | LXC 합성 | 기간 경계(KST)·상위 5·동점·없음 안내, 공개 답·멘션 없음, 문구 목록, 회귀 | NOT_RUN |
| `T142-P2-A` | [P2](02-tone-presets.md) | LXC 합성 | 프리셋 데이터 완전·검사 통과, 선택 시 GPT 0회 적용, 기본 = 되돌리기, 목록 증가 시 데이터로 채움 | NOT_RUN |
| `T142-P2-B` | [P2](02-tone-presets.md) | LXC 합성 | 사용자정의만 수정, 현재 프리셋 표시, 권한·동시 변경, 패키지 데이터, 회귀 | NOT_RUN |
| `T142-P3-A` | [P3](03-self-roast.md) | LXC 합성 | 등록·주시·본인 발언만·3개 미만 안내, 채널 일반 메시지·멘션 없음, 서버 말투 | NOT_RUN |
| `T142-P3-B` | [P3](03-self-roast.md) | LXC 합성 | 재생성·실패, 쿨타임, 안내는 본인만, 로그에 내용 없음, 문구 목록, 회귀 | NOT_RUN |
| `T142-P4-A` | [P4](04-evaluation.md) | LXC 실제 모델 | 셀프디스 통과율·다른 사람·비하어·없는 사실 0·말투 반영 | NOT_RUN |
| `T142-P4-B` | [P4](04-evaluation.md) | LXC 실제 모델 | 프리셋 4종 요약 말투·고정 규칙, 사용자 예시 확인 | NOT_RUN |
| `T142-P5-A` | [P5](05-release.md) | LXC/CI | 전체 회귀·버전·문서·5/10 집계, 복귀 호환, wheel 데이터 | NOT_RUN |
| `T142-P5-B` | [P5](05-release.md) | LXC/시험 Discord | 배포·명령 동기화, 사용자 확인, main CI, 태그·Release | NOT_RUN |
