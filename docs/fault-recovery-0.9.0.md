# 0.9.0-P3 장애 주입 및 복구 절차

대상은 개발 LXC의 전용 봇 서비스다. Discord 권한이나 실제 서버 디스크를 바꾸는 대신, 파괴적 장애는 **격리 DB·가짜 Discord 어댑터·자식 프로세스**에서 주입한다. 실제 서비스에는 종료/자동 재시작만 적용하고 주시 설정·대기 시간·캐시를 보존한다. 각 실행의 정확 SHA, 실제/격리 여부, 복구 시간과 제한은 [단계 증거](../Plans/0.DevelopPhase/evidence/0.9.0-P3.md)에 기록한다.

| 장애 | 격리 검증 | 기대하는 복구/실패 경계 |
|---|---|---|
| Discord 일시 단절·429·History 중간 페이지 오류 | `tests/test_history.py`, `tests/test_coverage.py` | 유한 재시도, 미완료 범위는 완료로 기록하지 않음, 재연결 뒤 누락 범위 재조회 |
| Discord 403·권한 회수·주시 해제 | `tests/test_history.py`, `tests/test_watch_gate.py`, `tests/test_workflow.py`, `tests/test_publisher.py` | 추가 조회·모델·다음 게시 중단, 채널 상태 해제, 성공 대기 시간 미적용 |
| Codex 인증 불가·timeout·비정상 자식 종료 | `tests/test_readiness.py`, `tests/test_codex_lifecycle.py`, `tests/test_workflow.py` | 준비 상태 실패 또는 하오체 안내, 자식/임시 입력 정리, 다음 정상 요청 허용 |
| SQLite 잠금·손상·읽기 전용·용량 부족 | `tests/test_cache_acceptance.py`, `tests/test_collection.py`, `tests/test_readiness.py` | 설정 불확실 시 실패 닫힘, 신뢰 가능한 설정에서만 History fallback, 운영 DB 임의 삭제 금지 |
| 전역 대기열 포화·요청 취소·부분 게시 | `tests/test_job_queue.py`, `tests/test_workflow.py`, `tests/test_publisher.py` | 대기자/채널 잠금 해제, 중복 게시 금지, 마지막 조각 완료 전 성공 대기 시간 없음 |
| 실제 프로세스 비정상 종료 | 전용 `systemd` 서비스 SIGKILL 뒤 상태·DB 확인 | 단일 인스턴스 자동 재시작, 주시 설정·성공 대기 시간 보존, 요청 임시 디렉터리 0개 |

## 운영자가 따를 순서

1. `systemctl is-active yoyackbot-dev.service`와 전용 계정의 `python -m yoyackbot health`로 프로세스/Discord/DB·모델 준비 실패를 분리한다. 전용 journal의 고정 오류 분류와 재시작 횟수만 본다. 원문·토큰·전체 환경변수를 복사하지 않는다.
2. 준비 실패는 신규 요청을 받지 않는 상태에서 원인을 분류한다. Discord 오류에는 권한·연결을, 모델 오류에는 전용 계정 인증과 고정 CLI를, DB 오류에는 파일 권한·무결성·공간을 점검한다. 반복 실패를 서비스의 무한 재시작으로 숨기지 않는다.
3. DB 손상이라면 운영 DB를 시험 대상으로 복원하지 않는다. [설정 전용 백업·격리 복구](restore.md)로 주시 목록과 대기 시간을 검증하고 빈 캐시에서 허용된 History만 재수집한다. 이전 SHA 복귀가 필요한 schema 변경은 [서비스 절차](service-operations.md)에 따라 호환성을 먼저 확인한다.
4. 복구 후 서비스 프로세스 1개, `health.ready=true`, 주시 목록과 대기 시간 보존, DB 무결성, 만료 메시지·요청 디렉터리·원문 DB 백업 0개를 확인한다. 실제 Discord 명령은 허용한 합성 시험 채널에서만 수행한다.

실제 Discord 권한 회수·네트워크 차단, 실제 디스크 고갈, 요청 게시 중 실서비스 SIGKILL은 이번 단계에서 수행하지 않는다. 그 경계는 격리 시험 결과로만 보고하며 실환경 통과로 바꾸지 않는다. 자동 외부 경고 전달도 아직 설정되지 않았다.
