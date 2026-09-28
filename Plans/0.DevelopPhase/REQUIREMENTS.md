# 명세 → 개발 단계 추적표

기준: [기능 명세 v1.5](../shinchangseop_discord_summary_bot_spec_v1.5.md). 이 표의 단계는 해당 요구를 구현·검증할 책임 위치이며 현재 구현 완료를 뜻하지 않는다. 각 단계 파일의 `T<버전>-P<n>-A/B`와 [TEST_MATRIX](TEST_MATRIX.md)에 연결된다.

| ID | 원본 명세 | 요구사항과 선택 기준 | 주 담당 단계 | 통합 확인 |
|---|---|---|---|---|
| R01 | §1–3 | Linux LXC, Discord 요약 봇, Codex CLI, Asia/Seoul, 지정 모델 | [0.0.0-P2](0.0.0/02-project-baseline.md), [P3](0.0.0/03-environment-preflight.md), [0.5.0-P1](0.5.0/01-cli-model-contract.md) | 0.9.0-P1 |
| R02 | §4 | 수신→캐시→명령→범위→수집→입력→CLI→게시→정리 전체 흐름, D02 성공 순서 보정 | [0.7.0-P1](0.7.0/01-channel-state.md), [P5](0.7.0/05-workflow-acceptance.md) | 1.0.0-P4 |
| R03 | §4-1–4-3 | Guild별 주시 채널 선택, Channel Select, 복수 선택·취소·전체 해제 | [0.1.0-P2](0.1.0/02-channel-selector.md), [P3](0.1.0/03-settings-store.md) | 0.1.0-P5 |
| R04 | §4-4 | 관리자/Manage Channels 및 저장 callback 권한 재검증 | [0.1.0-P2](0.1.0/02-channel-selector.md) | 0.9.0-P2/P3 |
| R05 | §4-5 | 설정 영속화, guild+channel 중복 금지, 재시작 복원 | [0.1.0-P3](0.1.0/03-settings-store.md) | 1.0.0-P3 |
| R06 | §4-6 | 주시 추가 후 실시간 수집, 요청 시 과거 누락 보충 | [0.3.0-P2](0.3.0/02-realtime-ingest.md), [0.4.0-P2](0.4.0/02-cache-gaps.md) | 0.9.0-P1 |
| R07 | §4-7 | 주시 해제 후 신규 저장 즉시 중단, 기존 캐시 자연 만료 | [0.1.0-P4](0.1.0/04-watch-enforcement.md), [0.7.0-P3](0.7.0/03-failure-recovery.md) | 0.9.0-P3 |
| R08 | §4-8 | 미주시 채널에서는 History·CLI·신규 메시지 저장·성공 cooldown 모두 금지 | [0.1.0-P4](0.1.0/04-watch-enforcement.md) | 0.7.0-P5 |
| R09 | §5.1, §44 | 도움말의 모든 예제, 처리 중/쿨타임 중에도 허용, 요약 미실행 | [0.2.0-P1](0.2.0/01-trigger-help.md) | 0.7.0-P5 |
| R10 | §5.2–5.5, §5.8–5.9 | 기본 1시간, 숫자는 시간, 분/시간/일/주 | [0.2.0-P2](0.2.0/02-option-parser.md), [P4](0.2.0/04-time-window.md) | 0.9.0-P2 |
| R11 | §5.6, §13-8 | 필터 후 최신 일반 사용자 X개, 부족분만 보충, D04 연속성 보정 | [0.4.0-P4](0.4.0/04-recent-count.md) | 0.9.0-P1 |
| R12 | §5.7, §13-9 | KST 오늘 자정부터 수락 시각까지 | [0.2.0-P4](0.2.0/04-time-window.md), [0.4.0-P2](0.4.0/02-cache-gaps.md) | 1.0.0-P4 |
| R13 | §6–7 | 포함형 트리거, 이후 옵션, 우선순위, 모호한 입력 거부 | [0.2.0-P1](0.2.0/01-trigger-help.md), [P2](0.2.0/02-option-parser.md) | 0.2.0-P5 |
| R14 | §8 | 명령 채널 하나만 처리, 다른 Guild/채널/스레드 등 합치지 않음 | [0.1.0-P1](0.1.0/01-gateway.md), [0.4.0-P1](0.4.0/01-history-pages.md) | 0.9.0-P1 |
| R15 | §9, §13-4 | 자신/다른 봇·웹훅·자동화·시스템 제외, 현재 명령 입력 제외 | [0.3.0-P2](0.3.0/02-realtime-ingest.md), [0.4.0-P1](0.4.0/01-history-pages.md) | 0.4.0-P5 |
| R16 | §10–11 | 시간·화자·본문, 오래된 순, 같은 시각 ID 순서 | [0.2.0-P4](0.2.0/04-time-window.md), [0.5.0-P2](0.5.0/02-input-files.md) | 0.6.0-P5 |
| R17 | §12–13, §40 | 요청별 임시 파일, 제한 권한, 성공·실패·종료·재시작 정리 | [0.5.0-P2](0.5.0/02-input-files.md), [P4](0.5.0/04-timeouts-cleanup.md) | 0.9.0-P3 |
| R18 | §13-1–13-4, §13-12 | SQLite 7일 rolling cache, created_at 기준, ID 중복 금지, 영속 경로 | [0.3.0-P1](0.3.0/01-message-schema.md), [P2](0.3.0/02-realtime-ingest.md), [P3](0.3.0/03-edits-retention.md) | 0.9.0-P4 |
| R19 | §13-5–13-7 | 겹치는 기간 재사용, 완료 범위 병합·차집합, 빈 구간, 부분 실패 | [0.3.0-P4](0.3.0/04-coverage.md), [0.4.0-P2](0.4.0/02-cache-gaps.md) | 1.0.0-P4 |
| R20 | §13-10 | 수정·삭제 반영, 오프라인 누락 한계, 재조회 최신 내용 반영 | [0.3.0-P3](0.3.0/03-edits-retention.md), [P4](0.3.0/04-coverage.md), [0.4.0-P2](0.4.0/02-cache-gaps.md) | 0.9.0-P3 |
| R21 | §13-11 | channel/time·만료 정리 인덱스, ID 유일성 | [0.3.0-P1](0.3.0/01-message-schema.md), [P5](0.3.0/05-cache-acceptance.md) | 0.8.0-P5 |
| R22 | §13-13 | 캐시 장애 fallback 또는 안전한 실패, 설정 불명확 시 금지 | [0.4.0-P5](0.4.0/05-collection-acceptance.md) | 0.9.0-P3 |
| R23 | §14 | Codex CLI로 입력 파일 요약, GPT-6 Luna Light 식별자 검증 | [0.5.0-P1](0.5.0/01-cli-model-contract.md), [P3](0.5.0/03-subprocess-isolation.md) | 0.5.0-P5 |
| R24 | §15–19 | 한국어 하오체, 화자별 발언, 사실성, 주제·결정·미해결 중심 | [0.6.0-P1](0.6.0/01-summary-prompt.md), [P2](0.6.0/02-quality-evaluation.md) | 0.9.0-P2 |
| R25 | §20–21 | 같은 채널 게시, 실제 범위 머리말, 개수형은 최저 시각 | [0.6.0-P3](0.6.0/03-format-split.md), [P4](0.6.0/04-delivery.md) | 1.0.0-P4 |
| R26 | §22 | 길이 제한 내 순서 있는 분할, 첫 조각 머리말, Markdown 보존 | [0.6.0-P3](0.6.0/03-format-split.md), [P4](0.6.0/04-delivery.md) | 0.9.0-P2 |
| R27 | §23–24, §26–28, §42–43, §48 | 처리 중 채널별 중복 차단, 고정 1분 제한 없음, 전역 실행 제한 | [0.7.0-P1](0.7.0/01-channel-state.md), [P4](0.7.0/04-global-queue.md) | 0.7.0-P5 |
| R28 | §25, §29, §43, §49 | 전체 게시 성공 후 5분, 실패는 cooldown 없음, 재시작 보존 | [0.7.0-P2](0.7.0/02-success-cooldown.md), [P3](0.7.0/03-failure-recovery.md) | 1.0.0-P4 |
| R29 | §30–31 | 하오체 오류, 내부 정보 비공개, 빈 대화는 CLI/cooldown 없음 | [0.4.0-P5](0.4.0/05-collection-acceptance.md), [0.7.0-P3](0.7.0/03-failure-recovery.md) | 0.9.0-P1 |
| R30 | §32–34 | 숫자·단위·상한 검증, 7일 캐시/4주 요청 분리 | [0.2.0-P3](0.2.0/03-limits.md), [0.4.0-P3](0.4.0/03-older-than-retention.md) | 0.9.0-P1 |
| R31 | §35–38 | 첨부는 존재만, URL은 텍스트, 표시명·멘션 정규화 | [0.5.0-P2](0.5.0/02-input-files.md), [0.6.0-P3](0.6.0/03-format-split.md) | 0.6.0-P5 |
| R32 | §39–41 | 토큰·키·환경 비공개, 파일 제한, Codex 입력 외 접근 금지 | [0.5.0-P3](0.5.0/03-subprocess-isolation.md), [P4](0.5.0/04-timeouts-cleanup.md), [0.8.0-P4](0.8.0/04-security-review.md) | 0.9.0-P3 |
| R33 | §45–47 | 짧고 자연스러운 하오체, 시작 메시지 선택, 예시 일관성 | [0.6.0-P1](0.6.0/01-summary-prompt.md), [P2](0.6.0/02-quality-evaluation.md), [P5](0.6.0/05-output-acceptance.md) | 0.9.0-P2 |
| R34 | §50–51 | 모든 운영 설정 분리, 기본값·모델·보존·권한·한도 관리 | [0.0.0-P4](0.0.0/04-interfaces-config.md), [0.8.0-P5](0.8.0/05-resource-soak.md) | 1.0.0-P2 |
| R35 | §52 | 요청·캐시 효율·CLI·게시 결과 계측, 원문 장기 로그 금지 | [0.8.0-P2](0.8.0/02-observability.md) | 0.9.0-P4 |
| R36 | §53 | 채널·명령·필터·캐시·요약·출력·쿨타임 전체 정상 판정 | [0.9.0-P1](0.9.0/01-full-regression.md), [P5](0.9.0/05-rc-freeze.md) | 1.0.0-P1/P4/P5 |
| R37 | §54 | 음성·OCR·첨부 분석·URL 탐색·통합/장기/개인/정기 요약·웹·검색·외부 공개 제외 | [0.0.0-P1](0.0.0/01-requirements.md), [0.8.0-P4](0.8.0/04-security-review.md) | 0.9.0-P1 |
| R38 | §55 | 최종 통합 흐름과 단기 보존 계약, D01 예외 명시 | [0.7.0-P5](0.7.0/05-workflow-acceptance.md), [1.0.0-P5](1.0.0/05-release-publish.md) | 정식 인수 |
| R39 | 사용자 요청 | 0.0.0~1.0.0 버전별 최소 5단계, 각 단계 종료 시 GitHub push | [전체 계획](README.md), [Git 규칙](GIT_WORKFLOW.md), [STATUS](STATUS.md) | 각 단계 G-PUSH |

## 명세에서 선택한 기본 정책

- 봇·웹훅·시스템 메시지 제외를 필수 기준으로 삼는다.
- 빈 대화·실패에는 성공 쿨타임을 적용하지 않는다.
- 설정 권한은 관리자 또는 Manage Channels다. 임의 봇 관리자 역할 확장은 필수 범위에 넣지 않는다.
- 시작 안내는 기본 생략하고 처리 중 재호출 안내·결과·오류만 제공하는 기준안이다.
- 최초 설치는 주시 채널 0개다. 운영자가 명시적으로 고르기 전에는 수집하지 않는다.
- DB 장애 시 설정과 권한이 신뢰 가능한 경우에만 fallback한다.
- 선택 채널 해제 시 기존 캐시는 자연 만료하며 즉시 삭제 옵션은 후속 범위다.

위 정책과 명세 충돌 해소 근거는 [DECISIONS](DECISIONS.md)에서 관리한다. 이 표에 없는 새로운 기능은 범위 변경으로 기록한 뒤 단계·검사·완료 조건을 함께 갱신한다.
