# 1.4.3-P5 — 통합·배포·출시

- 상태: **PUSH_PENDING** · 검사: `T143-P5-A/B` **PASS** ([증거](../evidence/1.4.3-P5.md)) · 환경: 개발 LXC, 시험 Discord, GitHub CI

## 작업

패키지·`VERSION`을 `1.4.3`으로 올리고 저장소 검증기·README·CHANGELOG·`docs/channel-settings.md`·`docs/upgrade-rollback-1.4.3.md`를 갱신한다. 배포 전에 사용자가 Discord 개발자 포털에서 Server Members Intent를 켰는지 확인한다. 배포 뒤 사용자가 시험 서버에서 21:00·22:00·22:30 흐름을 확인한다.

## 검증·완료 기준

- `T143-P5-A`: 같은 SHA의 전체 회귀·버전·문서·5단계/10검사 집계, 복귀 대상 호환.
- `T143-P5-B`: 포털 intent 확인 뒤 배포·서비스 SHA 대조·Gateway 연결, 명령 동기화(14개), 사용자 Discord 확인과 비식별 로그, `main` PR·리뷰·병합·main CI, 태그 `v1.4.3`·Release.

[버전 개요](README.md) · [상태](STATUS.md)
