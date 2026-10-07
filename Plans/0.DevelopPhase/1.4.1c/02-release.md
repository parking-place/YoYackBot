# 1.4.1c-P2 — 통합·배포·출시

- 상태: **PLANNED** · 검사: `T141c-P2-A/B` · 환경: 개발 LXC, 시험 Discord, GitHub CI

## 작업

패키지를 `1.4.1.2`(`VERSION`), 계획·태그를 `1.4.1c`로 올리고 저장소 검증기·README·CHANGELOG·`docs/channel-settings.md`·`docs/upgrade-rollback-1.4.1c.md`를 갱신한다. 배포 뒤 사용자가 시험 서버에서 “☠️”·“🕊️” 표시를 확인한다.

## 검증·완료 기준

- `T141c-P2-A`: 같은 SHA의 전체 회귀·버전·문서·2단계/4검사 집계, 복귀 대상 호환.
- `T141c-P2-B`: 배포·서비스 SHA 대조, 명령 동기화(10개), 사용자 Discord 확인과 비식별 로그, `main` PR·리뷰·병합·main CI, 태그 `v1.4.1c`·Release.

[버전 개요](README.md) · [상태](STATUS.md)
