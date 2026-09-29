# 1.0.0a-P3 — 기간·개수 수집

상태: **PLANNED**. 검사: `A5/A6`. P2의 원격 완료를 확인한 뒤 개발 LXC에서 수행한다.

## 작업

`long_range.py`, `count_collection.py`, `collection.py`의 7일 캐시/History 분할과 28일 기본 조회 상한을 새 30일 정책에 맞춘다. 캐시 공백만 History로 보충하고 ID 중복, 페이지 상한, 수집 중 주시·권한 변경을 처리한다. 30일 이전 메시지는 개수 요청에서도 제외한다.

## 통과 기준

- `A5`: 6/7/8/29/30/31일 경계, 자정, 캐시 공백과 중복 ID를 합성 History로 검증한다.
- `A6`: 30일 요청 및 100개 요청에서 누락·중복, 페이지 제한, 권한 거부·주시 변경 종료를 확인한다.

결과와 동일 구현 SHA를 [검증 목록](TEST_MATRIX.md)에 남긴다. **이 단계만의 구현 C → 증거 E → 종료 D를 각각 commit·GitHub push하고 원격 포함 관계 및 필요한 CI를 확인해야 DONE**이다. 실패·미실행은 PASS로 세지 않는다. [공통 Git 규칙](../GIT_WORKFLOW.md)을 따른다.

[버전 개요](README.md) · [상태](STATUS.md)
