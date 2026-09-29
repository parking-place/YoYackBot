# 1.0.0a-P1 — 설정·보존 계약

상태: **PLANNED**. 검사: `A1/A2`. 선행 1.0.0의 원격 완료를 확인한 뒤 개발 LXC에서 수행한다.

## 작업

`config.py`의 `YOYACK_CACHE_RETENTION_DAYS` 기본·허용 범위와 `YOYACK_MAX_DAYS`를 30일로 맞춘다. `LongRangeCollector`, `CountCollector`, `CollectionCoordinator`에 실효 설정이 전달되게 하고 7일/28일 고정 상한을 찾는다. 주 단위·오늘·개수 옵션이 기간 상한을 우회하지 않도록 계약을 정한다.

## 통과 기준

- `A1`: 기본/운영 설정에서 30일 허용·31일 거부와 4주 허용·5주 거부를 개발 LXC 합성 설정으로 확인한다.
- `A2`: 세 수집기의 보존·조회 상한이 설정과 일치하고 주시 채널 밖 자료가 들어오지 않는지 격리 DB로 확인한다.

결과와 동일 구현 SHA를 [검증 목록](TEST_MATRIX.md)에 남긴다. **이 단계만의 구현 C → 증거 E → 종료 D를 각각 commit·GitHub push하고 원격 포함 관계 및 필요한 CI를 확인해야 DONE**이다. 실패·미실행은 PASS로 세지 않는다. [공통 Git 규칙](../GIT_WORKFLOW.md)을 따른다.

[버전 개요](README.md) · [상태](STATUS.md)
