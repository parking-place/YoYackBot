# 1.3.3-P6 — 통합·배포·출시

- 상태: **DONE** · 검사: `T133-P6-A/B` **PASS** ([증거](../evidence/1.3.3-P6.md)) · 환경: 개발 LXC, 시험 Discord, GitHub CI

## 작업

[P1~P5](STATUS.md)의 원격 완료를 확인한다. 패키지·`VERSION`을 `1.3.3`으로 올리고 저장소 검증기에 6단계·13검사를 넣는다. 결정 D11의 확정 단계, README·CHANGELOG·`docs/observability.md`·`docs/upgrade-rollback-1.3.3.md`·`.env.example`을 갱신한다. 운영 서비스 환경의 입력 상한 값을 확인하고 필요하면 맞춘다(사용자 확인 뒤). 배포 뒤 사용자가 시험 채널에서 긴 범위 요약·`!!말하자면`·빠른 모드를 확인한다.

## 검증·완료 기준

- `T133-P6-A`: 같은 SHA의 전체 회귀·버전·문서 링크·6단계/13검사 집계, 복귀 대상 wheel이 새 버전 DB를 읽음(DB 변경 없음 확인).
- `T133-P6-B`: 후보·서비스 SHA 대조, 운영 `request_timing`에서 도구 턴 0·요약/후보 겹침·호출별 강도 확인(내용 없음), 사용자 확인, `main` PR·리뷰·병합·main CI, 태그 `v1.3.3`·Release.

출시 순서는 [1.3.1-P4](../1.3.1/04-release.md)와 같다.

[버전 개요](README.md) · [검증 목록](TEST_MATRIX.md) · [1.3.3 상태](STATUS.md)
