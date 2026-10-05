# 개발 봇 운영 상태와 로그

## 상태 확인

전용 계정 환경에서 `python -m yoyackbot health`는 다섯 개의 불리언과 고정 분류 문자열 `collection_worker` 하나만 JSON으로 출력한다. `process_alive`는 30초 이내에 갱신된 전용 heartbeat의 PID가 살아 있는지, `gateway_ready`는 그 프로세스가 Discord 연결을 준비했는지, `local_ready`는 고정 CLI/인증·SQLite·비공개 입력 경로의 준비 상태를 뜻한다. `collection_worker`는 수집 worker 상태로 `running`·`waiting`(Gateway 대기)·`disabled`만 정상이고 `starting`·`backoff`(공용 수집 상태 DB 대기)·`restarting`·`stalled`(15분 넘게 진행 없음)·`failed`·`stopped`·`unknown`(이전 버전 heartbeat)은 비정상이다. `ready`는 프로세스·Gateway·수집 worker·로컬 준비가 모두 정상일 때만 참이다. Gateway 연결만 살아 있다고 수집이 정상이라고 보고하지 않는다. `model_auth_attention`은 모델 준비 검사 실패 시 인증 또는 CLI 상태 점검이 필요함을 알리며 값이나 인증 파일 내용은 출력하지 않는다. 실제 모델 호출 성공을 보장하는 상태는 아니다.

서비스가 멈추거나 heartbeat가 30초 넘게 갱신되지 않으면 `process_alive=false`와 `ready=false`로 보고한다. Discord 연결만 끊기면 프로세스는 살아 있어도 `gateway_ready=false`가 된다. DB 잠금/권한·모델 인증 문제가 생기면 `local_ready=false`로 분리한다. `health` 종료 코드는 준비되면 0, 그렇지 않으면 2다. heartbeat 파일은 요청 입력 경로의 `gateway-health.json`이며 0600 권한으로 원자적으로 교체한다.

## 요청 로그

`summary_request`는 한 요청의 마지막에 구조화 JSON 한 줄로 기록한다. 필드는 무작위 `request_id`, `kind`, `selected_count`, `cache_count`, `history_count`, `history_pages`, `cache_fallback`, `duration_ms`, `model_result`, `post_result`, `outcome`, `error_kind`다. 1.0.0b-1부터 정상 요약은 DB만 읽으므로 `cache_count`는 최종 선택 건수이고 `history_count`·`history_pages`는 0, `cache_fallback`은 거짓이다. 첫 수집·연결 복구의 History 조회는 요약 요청과 별도로 진행한다. `not_ready`·`queue_timeout`·모델·게시 실패 등을 구분한다. 필드는 고정된 분류 또는 숫자만 허용하며 Guild/채널/사용자 ID, 원문, 요약문, 모델 출력, 토큰, 환경 전체, 예외 문자열은 기록하지 않는다.

기존 개별 `message_cached`, `cache_cleanup`, `gateway_ready` 등은 이벤트명과 개수만 남긴다. Discord 라이브러리의 일반 로그는 오류 수준으로 낮추고, 애플리케이션 실패 로그에서 예외 스택과 메시지를 제거했다. 오류 분류는 요청 JSON과 상태 검사로 판단한다.

1.0.0c의 기본 모델 작업 정책은 실행 1건·대기 8건·대기 최대 600초다. `collection_ms`, `queue_ms`, `model_ms`, `duration_ms`와 `queue_full`·`queue_timeout`을 함께 보면 수집·모델·게시 중 병목을 구분할 수 있다. 첫 수집은 한 번에 전체 3페이지·서버당 2페이지로 제한하고 서버별 순번으로 진행한다. 병렬 수집에서도 권한 거부·429·DB 잠금은 채널별로 분리 기록한다. 1.2.0부터 재시도 시각 저장(`defer`)이나 영구 차단 기록(`block`)마저 실패하면 `initial_backfill_state_write_failed action=defer|block`을 남기고 그 채널만 메모리에서 5초부터 최대 300초까지 지수 backoff로 보류한다. 다른 채널은 계속 진행한다. 수집 loop가 예기치 않게 끝나면 `backfill_worker_restarting failures=N`과 함께 1초부터 최대 60초 간격으로 다시 시작한다. 예외 문자열은 기록하지 않는다. 실제 운영값이 환경 변수에 명시돼 있으면 이 기본값과 다를 수 있다.

`request_timing`(1.3.2부터, 로거 `yoyackbot.timing`)은 `summary_request`·`idiom_request` 바로 뒤에 같은 `request_id`로 남는 JSON 한 줄이다. 봇이 명령을 받은 시각을 0ms로 두고 다음을 기록한다.
- `steps`: `received`·`admitted`(슬롯·쿨타임 통과)·`start_notice`·`collected`(메시지 조회 완료)·`queued`(모델 대기열 확보)·`posted`의 누적 ms
- `codex`: 호출마다 `call` 이름, `start`·`first_output`·`end`(누적 ms), `result`(`ok`/`error`/`cancelled`). 재시도는 `summary_retry`·`candidates_retry`·`idiom_candidates_retry`로 따로 보인다. 1.3.3부터 호출마다 `effort`(그 호출의 추론 강도: `judge`·`idiom_select`는 `low`, 나머지는 설정값), `execs`(CLI가 실행한 도구 명령 수 — 대화를 파일로 읽던 때는 읽기 턴 수), `tokens`(CLI가 끝에 보고한 사용 토큰 수, 캐시 제외 입력+출력)도 남긴다. 실패·취소한 호출은 `execs`·`tokens`가 비어 있다. `first_output`은 Codex CLI가 시작 머리말 뒤 처음 내보낸 모델 출력 줄(`codex`·`thinking`·`exec`)의 도착 시각이며, 답이 흘러나오기 시작한 시각이 아니다.
- `discord_delay_ms`(Discord 메시지 시각 → 수신, 시계 차이 포함 참고값), `total_ms`, `outcome`

이름은 허용 목록뿐이고 나머지는 숫자다. 메시지·프롬프트·답·CLI 출력은 남기지 않는다. 명령 해석 전에 거절된 요청(비주시·사용법 오류·수집 미완료)은 줄이 없다. 표로 보려면 서비스 호스트에서 `journalctl --namespace yoyackbot-dev -u yoyackbot-dev -o cat | python scripts/show_timings.py 5`를 실행한다.

## 보존 및 알림

개발 서비스는 `LogNamespace=yoyackbot-dev`로 분리한다. 설치 시 `deploy/journald-yoyackbot-dev.conf`를 `/etc/systemd/journald@yoyackbot-dev.conf`에 놓고 `systemctl restart systemd-journald@yoyackbot-dev.service`, `systemctl daemon-reload`, `systemctl restart yoyackbot-dev.service` 순으로 반영한다. 전용 journal은 최대 50 MiB, 파일당 5 MiB, 최대 7일 보존이며, 단위 로그는 분당 120건을 넘으면 억제한다. `journalctl --namespace=yoyackbot-dev -u yoyackbot-dev.service`로 확인한다. 이 분리는 다른 서비스의 로그 정책을 바꾸지 않는다.

운영 점검은 1분마다 `health`를 호출하고 연속 2회 `ready=false`면 알린다. 5분 동안 `model_error` 또는 `history_error`가 3건 이상, `queue_full` 또는 `queue_timeout`이 1건 이상, `duration_ms`가 120000을 넘는 요청이 1건 이상이면 조사한다. 50 MiB 한도에 근접하거나 journal 억제 메시지가 나오면 알림을 올린다. 인위적으로 원문을 포함해 진단하지 않는다.

`systemd`의 서비스 재시작 횟수와 journal 크기는 [부분 관측](../Plans/0.DevelopPhase/0.8.0/SOAK_RUN.md)에서 확인했다. 8시간·24시간 연속 운영과 실제 경고 전달 체계는 [사용자 결정](../Plans/0.DevelopPhase/DURATION_WAIVER.md)에 따라 이번 릴리스의 완료 증거에 포함하지 않는다. 현재 기준은 운영 점검 기준이며 자동 외부 알림 전송은 아직 없다.
