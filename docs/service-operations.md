# 개발 봇 서비스 운영

이 절차는 개발 LXC의 `/opt/yoyackbot-dev` 작업 경로와 전용 `yoyackbot-dev` 계정을 대상으로 한다. 다른 서버에는 경로와 계정을 검토한 별도 서비스 파일을 사용한다. 실제 인증값과 메시지 DB는 저장소 밖에 둔다.

## 설치 및 준비 검사

1. 검증된 Git SHA로 `/opt/yoyackbot-dev`를 맞추고 전용 가상환경에 고정 의존성을 설치한다. 소스 경로의 Git checkout만 갱신하면 기존 `site-packages` 설치본은 바뀌지 않는다. 해당 SHA에서 wheel을 만들고, 서비스를 정지한 상태에서 `pip install --no-deps --force-reinstall <검증된 wheel>`로 설치한다. 시작 전에 가상환경 Python에서 `yoyackbot.parser.__file__`과 새 도움말의 `30일` 예시·상한을 확인한다.
2. Discord 토큰은 `/var/lib/yoyackbot-dev/discord-token`에 전용 계정 소유 0600으로 두고 systemd `LoadCredential`로 전달한다. 서비스는 `CREDENTIALS_DIRECTORY`의 격리된 사본을 우선 읽는다. `/var/lib/yoyackbot-dev/secrets.env`에는 실제 토큰 값 대신 수동 명령용 `DISCORD_BOT_TOKEN_FILE` 경로만 둔다. 모델 인증 디렉터리와 환경 파일의 소유자·권한도 확인한다. 환경 파일은 `KEY=value` 형식, 전용 계정 소유, 접근 권한 `0600`이다.
3. 전용 계정에서 `python -m yoyackbot check-ready`를 실행한다. 고정 CLI/인증, SQLite 무결성·쓰기 잠금, 요청별 비공개 파일 생성을 확인한다. 이 검사는 Discord 연결까지 성공했다는 뜻이 아니다. `YOYACK_CODEX_EXECUTABLE`이 `codex` 같은 PATH 이름이면 시작할 때 한 번 절대 경로로 고정하며 준비 검사·요약·사용량 조회가 같은 파일을 쓴다. 모델 준비 실패는 `config`·`executable_missing`·`executable_not_runnable`·`version_mismatch`·`auth_file` 중 하나로 표시한다. `auth_file`은 인증 파일의 형태 검사이며 실제 로그인 성공을 뜻하지 않는다.
4. `deploy/yoyackbot-dev.service`를 `/etc/systemd/system/yoyackbot-dev.service`에 설치하고 `systemctl daemon-reload`, `systemctl enable --now yoyackbot-dev.service`를 실행한다. 이미 수동으로 실행 중인 봇이 있으면 종료를 확인한 뒤 시작한다.
5. `systemctl is-active yoyackbot-dev.service`, 전용 계정의 `python -m yoyackbot health`, 서비스 전용 journal의 `gateway_ready`를 확인한다. 전용 계정의 봇 프로세스는 한 개여야 한다. 로그 분리·보존 설정은 [운영 상태와 로그](observability.md)를 따른다.

## 중지·변경·복구

- `systemctl stop yoyackbot-dev.service`는 SIGTERM을 보내며, 봇은 새 요청을 막고 대기/실행 작업을 취소한 뒤 Discord 연결을 닫는다. systemd는 최대 30초 후 서비스 프로세스 그룹을 정리한다.
- 변경 전에는 정확한 Git SHA와 schema 버전을 기록하고, 설정·인증 상태와 진행 중인 요약 작업을 확인한다. 요청 실행 중 서비스 정지는 작업을 취소한다. 변경 후에는 checkout뿐 아니라 **설치된 패키지**의 코드·버전도 검사하고 `check-ready`와 Gateway 준비를 다시 확인한다. 실패하면 새 요청을 받지 않은 상태에서 이전 검증 SHA의 wheel로 복귀한다. schema가 달라진 경우 운영 DB에 무작정 이전 코드를 연결하지 말고 격리 사본으로 복귀 절차를 검증한다.
- 비정상 종료는 5초 후 재시작하며 5분에 세 번으로 제한한다. 준비 검사 실패·DB 권한 오류가 반복되면 `systemctl status`와 분류된 진단을 보고 원인을 고친 뒤 `systemctl reset-failed`와 `systemctl start`를 실행한다. 인증값이나 메시지 원문을 진단에 복사하지 않는다.
- 시작 시 전용 입력 디렉터리의 단일 인스턴스 잠금을 획득한다. 이전 프로세스가 남긴 요청별 입력은 잠금 획득 후 제거한다. 성공 쿨타임과 주시 설정은 SQLite에 남고, 대기·실행 작업은 자동 재게시하지 않는다.

1.0.0 승격·복귀 판단과 격리 리허설은 [업데이트·복귀 절차](upgrade-rollback-1.0.0.md)를 따른다.

설정 전용 백업과 빈 캐시 복구는 [복구 절차](restore.md)를 따른다.
