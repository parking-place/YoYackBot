# 1.4.2a 검증 목록

총 **3단계·6검사**, 계획 게시 시점의 **모든 결과는 NOT_RUN**이다. 기준은 `v1.4.2`(`109ce8b`)이다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T142a-P1-A` | [P1](01-more-presets.md) | LXC 합성 | 새 프리셋 6개 데이터 완전·검사 통과, 단락 검사, 기존 데이터 그대로 | PASS |
| `T142a-P1-B` | [P1](01-more-presets.md) | LXC 합성 | 메뉴 12항목·순서, 선택 시 GPT 0회·이름 표시, 회귀 | PASS |
| `T142a-P2-A` | [P2](02-evaluation.md) | LXC 실제 모델 | 새 프리셋 요약 금지선 0·본문 어미, 셀프디스 통과·비하어 0 | PASS |
| `T142a-P2-B` | [P2](02-evaluation.md) | LXC 실제 모델 | 사용자 예시 확인 | PASS |
| `T142a-P3-A` | [P3](03-release.md) | LXC/CI | 전체 회귀·버전·문서·3/6 집계, 복귀 호환, wheel 데이터 | PASS |
| `T142a-P3-B` | [P3](03-release.md) | LXC/시험 Discord | 배포·명령 동기화, 사용자 확인, main CI, 태그·Release | PASS |
