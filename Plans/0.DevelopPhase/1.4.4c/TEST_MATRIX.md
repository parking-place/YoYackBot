# 1.4.4c 검증 목록

총 **2단계·4검사**, 계획 게시 시점의 **모든 결과는 NOT_RUN**이다. 기준은 `v1.4.4b`(`419764b`)이다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T144c-P1-A` | [P1](01-diet-effort.md) | LXC 합성 | 서비스 설정 low·medium 모두 식단 두 호출은 medium(대체 포함), 나머지 강도 규칙 그대로, 회귀 | PASS |
| `T144c-P1-B` | [P1](01-diet-effort.md) | LXC 실제 모델 | 서비스 설정을 low로 둔 실행에서 식단 두 호출이 Terra·medium으로 나가고 통과 | PASS |
| `T144c-P2-A` | [P2](02-release.md) | LXC/CI | 전체 회귀·버전·문서·2/4 집계, 복귀 호환 | PASS |
| `T144c-P2-B` | [P2](02-release.md) | LXC/CI | 배포, 사용자 출시 지시, main CI, 태그·Release | PASS |
