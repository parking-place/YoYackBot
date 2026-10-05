# 1.3.3 검증 목록

총 **6단계·13검사**, 계획 게시 시점의 **모든 결과는 NOT_RUN**이다. 기준은 `v1.3.2`(`6604a61`)이다.

| 검사 ID | 단계 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T133-P1-A` | [P1](01-call-effort.md) | LXC 합성 | 호출별 강도(`judge`·`idiom_select`만 low, 설정보다 높이지 않음), 빠른 등급·동시 요청과 분리 | PASS |
| `T133-P1-B` | [P1](01-call-effort.md) | LXC 합성 | `effort`·`execs`·`tokens` 기록(숫자·허용 목록, 되찍힌 프롬프트 무시), 표 스크립트, 회귀 | PASS |
| `T133-P2-A` | [P2](02-idiom-inline.md) | LXC 합성 | 사자성어 두 호출의 자료 블록·nonce·위조 방지, 대화 파일 마운트 제거, 최악 입력 상한 | PASS |
| `T133-P2-B` | [P2](02-idiom-inline.md) | LXC 합성 | 실패 분류가 대화 글에 속지 않음, 기존 사자성어 시험 유지, 내용 없는 로그, 회귀 | PASS |
| `T133-P3-A` | [P3](03-summary-inline.md) | LXC 합성 | 요약 경로 호출별 자료 블록(심사는 대화 없음), 기존 입력 요소 전달, 입력 상한 경계 | NOT_RUN |
| `T133-P3-B` | [P3](03-summary-inline.md) | LXC 합성 + CLI 확인 | 출력 검사·후보 거르기·심사 파싱 유지, 주입 사례, 프롬프트 버전, 상한 확정 근거, 회귀 | NOT_RUN |
| `T133-P4-A` | [P4](04-parallel-candidates.md) | LXC 합성 | 요약·후보 동시 시작, 심사 따로, 본문+평가 한 번에 게시, 결과 범주·상한 5회 | NOT_RUN |
| `T133-P4-B` | [P4](04-parallel-candidates.md) | LXC 합성 | 실패·권한 회수·종료 시 취소와 정리, 자리 없으면 순서 실행, 다른 채널 비간섭, 회귀 | NOT_RUN |
| `T133-P5-A` | [P5](05-evaluation.md) | LXC 실제 모델 | 앞·가운데·뒤 주제 모두 반영(8~2,000개·상한 근처), 1.3.2 대비 | NOT_RUN |
| `T133-P5-B` | [P5](05-evaluation.md) | LXC 실제 모델 | 요청·호출별 시간(보통·빠른), 도구 턴 0, 겹침, 토큰, 주간 사용량 변화 | NOT_RUN |
| `T133-P5-C` | [P5](05-evaluation.md) | LXC 실제 모델 | 평가 세트·주입 사례 품질 기준, low 심사·선택·대화 없는 심사·요약 없는 후보 비교, 사용자 예시 확인 | NOT_RUN |
| `T133-P6-A` | [P6](06-release.md) | LXC/CI | 전체 회귀·버전·문서·6/13 집계, 복귀 대상 호환 | NOT_RUN |
| `T133-P6-B` | [P6](06-release.md) | LXC/시험 Discord | 배포·SHA 대조, 운영 `request_timing` 확인, 사용자 확인, main CI, 태그·Release | NOT_RUN |

각 단계의 지정 검사와 구현 C 검증, 증거 E의 GitHub 반영·CI 성공 후 [상태 문서](STATUS.md)에 DONE을 기록하는 종료 D를 만든다.
