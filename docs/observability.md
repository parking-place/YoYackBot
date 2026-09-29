# 개발 봇 운영 상태와 로그

## 상태 확인

전용 계정 환경에서 `python -m yoyackbot health`는 다섯 개의 불리언만 JSON으로 출력한다. `process_alive`는 30초 이내에 갱신된 전용 heartbeat의 PID가 살아 있는지, `gateway_ready`는 그 프로세스가 Discord 연결을 준비했는지, `local_ready`는 고정 CLI/인증·SQLite·비공개 입력 경로의 준비 상태를 뜻한다. `ready`는 셋 모두 참일 때만 참이다. `model_auth_attention`은 모델 준비 검사 실패 시 인증 또는 CLI 상태 점검이 필요함을 알리며 값이나 인증 파일 내용은 출력하지 않는다. 실제 모델 호출 성공을 보장하는 상태는 아니다.

서비스가 멈추거나 heartbeat가 30초 넘게 갱신되지 않으면 `process_alive=false`와 `ready=false`로 보고한다. Discord 연결만 끊기면 프로세스는 살아 있어도 `gateway_ready=false`가 된다. DB 잠금/권한·모델 인증 문제가 생기면 `local_ready=false`로 분리한다. `health` 종료 코드는 준비되면 0, 그렇지 않으면 2다. heartbeat 파일은 요청 입력 경로의 `gateway-health.json`이며 0600 권한으로 원자적으로 교체한다.

## 요청 로그

`summary_request`는 한 요청의 마지막에 구조화 JSON 한 줄로 기록한다. 필드는 무작위 `request_id`, `kind`, `selected_count`, `cache_count`, `history_count`, `history_pages`, `cache_fallback`, `duration_ms`, `model_result`, `post_result`, `outcome`, `error_kind`다. 1.0.0b-1부터 정상 요약은 DB만 읽으므로 `cache_count`는 최종 선택 건수이고 `history_count`·`history_pages`는 0, `cache_fallback`은 거짓이다. 첫 수집·연결 복구의 History 조회는 요약 요청과 별도로 진행한다. `not_ready`·`queue_timeout`·모델·게시 실패 등을 구분한다. 필드는 고정된 분류 또는 숫자만 허용하며 Guild/채널/사용자 ID, 원문, 요약문, 모델 출력, 토큰, 환경 전체, 예외 문자열은 기록하지 않는다.

기존 개별 `message_cached`, `cache_cleanup`, `gateway_ready` 등은 이벤트명과 개수만 남긴다. Discord 라이브러리의 일반 로그는 오류 수준으로 낮추고, 애플리케이션 실패 로그에서 예외 스택과 메시지를 제거했다. 오류 분류는 요청 JSON과 상태 검사로 판단한다.

1.0.0c의 기본 모델 작업 정책은 실행 1건·대기 8건·대기 최대 600초다. `collection_ms`, `queue_ms`, `model_ms`, `duration_ms`와 `queue_full`·`queue_timeout`을 함께 보면 수집·모델·게시 중 병목을 구분할 수 있다. 첫 수집은 한 번에 전체 3페이지·서버당 2페이지로 제한하고 서버별 순번으로 진행한다. 병렬 수집에서도 권한 거부·429·DB 잠금은 채널별로 분리 기록한다. 실제 운영값이 환경 변수에 명시돼 있으면 이 기본값과 다를 수 있다.

## 보존 및 알림

개발 서비스는 `LogNamespace=yoyackbot-dev`로 분리한다. 설치 시 `deploy/journald-yoyackbot-dev.conf`를 `/etc/systemd/journald@yoyackbot-dev.conf`에 놓고 `systemctl restart systemd-journald@yoyackbot-dev.service`, `systemctl daemon-reload`, `systemctl restart yoyackbot-dev.service` 순으로 반영한다. 전용 journal은 최대 50 MiB, 파일당 5 MiB, 최대 7일 보존이며, 단위 로그는 분당 120건을 넘으면 억제한다. `journalctl --namespace=yoyackbot-dev -u yoyackbot-dev.service`로 확인한다. 이 분리는 다른 서비스의 로그 정책을 바꾸지 않는다.

운영 점검은 1분마다 `health`를 호출하고 연속 2회 `ready=false`면 알린다. 5분 동안 `model_error` 또는 `history_error`가 3건 이상, `queue_full` 또는 `queue_timeout`이 1건 이상, `duration_ms`가 120000을 넘는 요청이 1건 이상이면 조사한다. 50 MiB 한도에 근접하거나 journal 억제 메시지가 나오면 알림을 올린다. 인위적으로 원문을 포함해 진단하지 않는다.

`systemd`의 서비스 재시작 횟수와 journal 크기는 [부분 관측](../Plans/0.DevelopPhase/0.8.0/SOAK_RUN.md)에서 확인했다. 8시간·24시간 연속 운영과 실제 경고 전달 체계는 [사용자 결정](../Plans/0.DevelopPhase/DURATION_WAIVER.md)에 따라 이번 릴리스의 완료 증거에 포함하지 않는다. 현재 기준은 운영 점검 기준이며 자동 외부 알림 전송은 아직 없다.
