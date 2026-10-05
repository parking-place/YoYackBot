# 1.3.2 — 요청 단계별 소요 시간 로그

- 상태: **DONE** · 2단계·4검사 완료, `v1.3.2` 출시(2026-10-05, 선행 `v1.3.1`)
- 선행 버전: [1.3.1](../1.3.1/README.md) — 태그 `v1.3.1`, 코드 `cf50c6bcf5b16cff25cde505641705f62a024e92`, `main` 병합 `6924a09`(2026-10-03). 개발 브랜치 `develop/1.3.2`는 `main` `6924a09`에서 시작한다.
- 계획 근거: 2026-10-04 사용자 요청 “명령 입력 → 메시지 조회 → Codex 시작 → 첫 출력 → (재시도) → 완료 각각 ms 단위로 로그”

## 목표

`!!요약좀`·`!!말하자면` 요청마다 서비스 로그에 **한 줄**(`request_timing`)로 단계별 경과 시간(ms)을 남긴다. 기준(0ms)은 봇이 명령 메시지를 받은 시각이다.

| 단계 | 의미 |
|---|---|
| `discord_delay_ms` | Discord 메시지 시각 → 봇 수신(참고값, 시계 차이 포함) |
| `admitted` | 채널 작업 슬롯·쿨타임 통과 |
| `start_notice` | 요약 시작 안내 전송 완료(`!!요약좀`만) |
| `collected` | 메시지 조회(캐시 수집·재검증) 완료 |
| `queued` | 모델 대기열 자리 확보 |
| Codex 호출마다 `start`·`first_output`·`end`·`result` | 호출 이름: `summary`, `summary_retry`, `candidates`, `judge`, `candidates_retry`, `idiom_candidates`, `idiom_candidates_retry`, `idiom_select` |
| `posted` | 채널 게시 완료 |
| `total_ms` | 수신 → 작업 종료 |

- **첫 출력**은 Codex CLI가 시작 머리말 뒤에 처음 내보내는 모델 출력 줄(`codex`·`thinking`·`exec`)의 도착 시각이다. 서버 CLI 0.158.0의 격리 실행에서 머리말은 약 0.6초에, 첫 모델 출력은 약 4초에 나왔다(2026-10-04 합성 확인). CLI는 답을 조각조각 흘려보내지 않으므로 첫 출력은 “모델이 처음 반응한 시각”이지 “답이 나오기 시작한 시각”이 아니다.
- 로그에는 고정된 단계·호출 이름과 숫자, 요청 ID·결과 범주만 남긴다. 메시지·프롬프트·모델 답·CLI 출력 내용은 남기지 않는다.
- 운영자가 읽기 쉽도록 `scripts/show_timings.py`로 서비스 로그의 `request_timing` 줄을 표로 보여 준다.

## 단계

| 순서 | 단계 | 검증 ID | 상태 |
|---|---|---|---|
| 1 | [P1 — 단계별 시간 기록](01-request-timing.md) | `T132-P1-A/B` | DONE |
| 2 | [P2 — 실제 모델 확인·배포·출시](02-release.md) | `T132-P2-A/B` | DONE |

[검증 목록](TEST_MATRIX.md) · [상태](STATUS.md) · [Git 규칙](../GIT_WORKFLOW.md). 버전 표기는 계획·태그 `1.3.2` / `v1.3.2`, Python 패키지 `1.3.2`이다.
