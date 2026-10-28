# 1.4.4b-P2 — 통합·배포·출시

- 상태: **PLANNED** · 검사: `T144b-P2-A/B` · 환경: 개발 LXC, GitHub CI

## 작업

패키지를 `1.4.4.2`(`VERSION`), 계획·태그를 `1.4.4b`로 올리고 저장소 검증기·README·CHANGELOG·`docs/channel-settings.md`·`docs/upgrade-rollback-1.4.4b.md`를 갱신한다. 사용자 지시대로 개발이 끝나면 배포하고 바로 출시한다.

## 검증·완료 기준

- `T144b-P2-A`: 같은 SHA의 전체 회귀·버전·문서·2단계/4검사 집계, 복귀 대상 호환.
- `T144b-P2-B`: 배포·서비스 SHA 대조, 사용자 출시 지시, `main` PR·리뷰·병합·main CI, 태그 `v1.4.4b`·Release.

[버전 개요](README.md) · [상태](STATUS.md)
