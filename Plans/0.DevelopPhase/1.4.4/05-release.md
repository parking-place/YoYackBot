# 1.4.4-P5 — 통합·배포·출시

- 상태: **PLANNED** · 검사: `T144-P5-A/B` · 환경: 개발 LXC, 시험 Discord, GitHub CI

## 작업

패키지·`VERSION`을 `1.4.4`로 올리고 저장소 검증기·README·CHANGELOG·`docs/channel-settings.md`·`docs/upgrade-rollback-1.4.4.md`를 갱신한다. 배포 뒤 사용자가 시험 서버에서 22:30 정산과 일요일 훈수를 확인한다.

## 검증·완료 기준

- `T144-P5-A`: 같은 SHA의 전체 회귀·버전·문서·5단계/10검사 집계, 복귀 대상 호환.
- `T144-P5-B`: 배포·서비스 SHA 대조, 명령 동기화(16개), 사용자 Discord 확인과 비식별 로그, `main` PR·리뷰·병합·main CI, 태그 `v1.4.4`·Release.

[버전 개요](README.md) · [상태](STATUS.md)
