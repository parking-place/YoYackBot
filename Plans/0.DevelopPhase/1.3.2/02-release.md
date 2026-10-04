# 1.3.2-P2 — 실제 모델 확인·배포·출시

- 상태: **PUSH_PENDING** · 검사: `T132-P2-A` **PASS**, `T132-P2-B` 사용자 확인 대기 ([증거](../evidence/1.3.2-P2.md)) · 환경: 개발 LXC, 실제 모델(합성 대화), 시험 Discord, GitHub CI

## 작업

패키지·`VERSION`을 `1.3.2`로 올리고 저장소 검증기·버전 대응표·README·CHANGELOG·`docs/observability.md`·`docs/upgrade-rollback-1.3.2.md`를 갱신한다. 실제 모델로 합성 요약·`!!말하자면`을 명령 수신 경로부터 실행해 `request_timing` 줄을 확인하고, 운영에 배포한 뒤 실제 명령의 로그를 사용자에게 보여 준다. 복귀 대상은 `v1.3.1`(`cf50c6b`)이며 DB 변경은 없다.

## 검증·완료 기준

- `T132-P2-A`: 실제 모델 실행에서 모든 Codex 호출에 시작·첫 출력·끝이 있고 단계 합이 총 시간과 맞는다. 같은 SHA에서 전체 회귀·버전·문서·2단계/4검사 집계.
- `T132-P2-B`: 운영 배포·서비스 SHA 대조, 실제 명령의 `request_timing` 로그(내용 없음) 확인, 사용자 확인, `main` PR·리뷰·병합·main CI, 태그 `v1.3.2`·Release.

[버전 개요](README.md) · [상태](STATUS.md)
