# 1.4.4a-P2 — 통합·배포·출시

- 상태: **DONE** · 검사: `T144a-P2-A/B` **PASS** ([증거](../evidence/1.4.4a-P2.md)) · 환경: 개발 LXC, 시험 Discord, GitHub CI

## 작업

패키지를 `1.4.4.1`(`VERSION`), 계획·태그를 `1.4.4a`로 올리고 저장소 검증기·README·CHANGELOG·`docs/upgrade-rollback-1.4.4a.md`를 갱신한다. 배포 때 0.158.0 두 파일을 버전을 붙여 남기고 0.164.0으로 바꾼다. 배포 뒤 사용자가 요약과 식단 평가를 확인한다.

## 검증·완료 기준

- `T144a-P2-A`: 같은 SHA의 전체 회귀·버전·문서·2단계/4검사 집계, 복귀 대상 호환.
- `T144a-P2-B`: CLI 파일 sha256·버전 대조, 배포·서비스 SHA 대조, 사용자 Discord 확인과 비식별 로그, `main` PR·리뷰·병합·main CI, 태그 `v1.4.4a`·Release.

[버전 개요](README.md) · [상태](STATUS.md)
