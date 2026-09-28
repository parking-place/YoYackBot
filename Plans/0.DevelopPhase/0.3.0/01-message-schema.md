# 0.3.0-P1 — 메시지·범위 schema와 migration

- 상태: **IN_PROGRESS**
- 명세 근거: §13-3, §13-6, §13-11–13-12
- 검증 ID: `T030-P1-A`, `T030-P1-B`
- 검증 환경: **LXC** — 제공 LXC의 격리된 개발 경로/DB에서 실행한다. 실제 서비스 사용 여부는 각 검사에 따로 기록한다.

## 선행 조건

[0.2.0-P5](../0.2.0/05-parser-acceptance.md)가 검증과 GitHub push 확인까지 끝나 DONE이어야 한다.

## 수행 작업

1. 설정 schema에 메시지·coverage 테이블을 확장하고 message_id 유일성, guild/channel/time 인덱스를 만든다.
2. 표시명·author_id·본문·생성/수정/캐시 시각을 구분하고 Snowflake ID 정밀도를 보존한다.
3. 순방향 migration과 설정 보존·실패 복구 절차를 정의하고 영속 DB 경로 권한을 제한한다.

## 산출물

SQLite migration, 메시지/coverage repository, 인덱스.

산출물은 앞으로 구현할 대상이다. 이 계획 파일을 작성한 것만으로 산출물이 구현되었다고 판단하지 않는다.

## 검증과 통과 기준

- [ ] `T030-P1-A`: 신규 DB와 0.1.0 설정 DB 모두에서 migration 후 주시 목록이 보존되고 중복 message_id가 생기지 않는다.
- [ ] `T030-P1-B`: 같은 timestamp의 다른 ID와 큰 ID를 정확히 저장·정렬하고 조회 계획이 의도한 인덱스를 사용한다.
- [ ] 영향받는 선행 기능의 회귀 검사가 통과하고 실패·미실행·실환경 미확인 항목을 구분했다.

## 단계 완료 — GitHub 업로드 필수

- [ ] 위 작업·검증을 완료하고 [증거 양식](../EVIDENCE_TEMPLATE.md)에 대상 SHA·환경·결과·제한을 기록했다.
- [ ] 실제 비밀값·`.private`·DB·Discord 원문·임시 파일이 커밋에 없음을 확인했다.
- [ ] 구현과 증거를 단계별로 commit하고 대상 브랜치에 **GitHub push**했다.
- [ ] 원격에서 증거 커밋 존재와 구현 SHA 포함, 필요한 CI 결과를 확인했다.
- [ ] [STATUS](../STATUS.md)를 DONE으로 갱신한 종료 커밋도 push하고 마지막 원격 반영을 확인했다.

**push 실패 또는 원격 확인 미완료는 PUSH_PENDING이며 단계 완료가 아니다.** 상세 절차와 SHA 기록 방식은 [GIT_WORKFLOW](../GIT_WORKFLOW.md)를 따른다.

## 실패 및 다음 단계

검사 실패 시 실패 사례·환경·복구 방법을 증거에 남기고 IN_PROGRESS/BLOCKED로 유지한다. 수정 후 영향 검사를 다시 수행하며 완료 전에 의존 단계로 넘어가지 않는다.

이 단계의 마지막 원격 반영까지 확인한 뒤 다음으로 진행한다: [0.3.0-P2](../0.3.0/02-realtime-ingest.md).

[버전 개요](README.md) · [전체 계획](../README.md) · [검증 목록](../TEST_MATRIX.md)
