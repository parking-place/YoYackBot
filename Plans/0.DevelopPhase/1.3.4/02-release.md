# 1.3.4-P2 — 통합·배포·출시

- 상태: **PLANNED** · 검사: `T134-P2-A/B` · 환경: 개발 LXC, 시험 Discord, GitHub CI

## 작업

패키지·`VERSION`을 `1.3.4`로 올리고 저장소 검증기·버전 대응표·README·CHANGELOG·`docs/channel-settings.md`·`docs/upgrade-rollback-1.3.4.md`를 갱신한다. 배포 뒤 사용자가 시험 채널에서 `/말하자면`을 써서 명령이 다른 사람에게 보이지 않고 답만 올라오는지 확인한다.

## 검증·완료 기준

- `T134-P2-A`: 같은 SHA의 전체 회귀·버전·문서·2단계/4검사 집계, 복귀 대상 호환.
- `T134-P2-B`: 배포·서비스 SHA 대조, 명령 동기화, 사용자 Discord 확인과 비식별 로그, `main` PR·리뷰·병합·main CI, 태그 `v1.3.4`·Release.

[버전 개요](README.md) · [상태](STATUS.md)
