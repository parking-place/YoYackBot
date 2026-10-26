# 1.4.3a-P2 — 통합·배포·출시

- 상태: **PLANNED** · 검사: `T143a-P2-A/B` · 환경: 개발 LXC, 시험 Discord, GitHub CI

## 작업

패키지를 `1.4.3.1`(`VERSION`), 계획·태그를 `1.4.3a`로 올리고 저장소 검증기·README·CHANGELOG·`docs/channel-settings.md`·`docs/upgrade-rollback-1.4.3a.md`를 갱신한다. 배포 뒤 사용자가 21:00 알림과 22:30 평가 대상을 확인한다.

## 검증·완료 기준

- `T143a-P2-A`: 같은 SHA의 전체 회귀·버전·문서·2단계/4검사 집계, 복귀 대상 호환.
- `T143a-P2-B`: 배포·서비스 SHA 대조, 사용자 Discord 확인과 비식별 로그, `main` PR·리뷰·병합·main CI, 태그 `v1.4.3a`·Release.

[버전 개요](README.md) · [상태](STATUS.md)
