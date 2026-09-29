# 1.0.0 설치·업데이트·제거

이 문서는 Linux LXC의 전용 봇 계정·전용 데이터 경로를 대상으로 한다. 실제 Discord 토큰, Codex 인증, SQLite DB, 메시지 원문은 소스·wheel·GitHub Release 밖에 둔다. 사용자 선택에 따라 현재 개발 LXC와 봇 계정을 [제자리 승격](../Plans/0.DevelopPhase/1.0.0/TARGET_DECISION.md)하며, 동일 계정의 Gateway를 두 개 동시에 실행하지 않는다.

## 배포 묶음과 식별

검증된 **정확한 Git SHA**에서만 소스 tar와 Python wheel을 만든다. 소스 tar는 `VERSION`, `pyproject.toml`, `requirements.lock`, `src/yoyackbot`의 schema migration·프롬프트, `deploy` 서비스 파일, 설치·복구 문서를 포함한다. wheel에는 실행 Python 패키지가 들어간다. 산출물 파일명·SHA-256·원본 Git SHA를 함께 기록하고, `tar -tf`/wheel 목록으로 비밀·DB·원문 포함 여부를 검사한다. 브랜치 이름만으로 검증 대상을 식별하지 않는다.

```bash
git archive --format=tar --prefix=yoyackbot-1.0.0/ <검증_SHA> | gzip -n > yoyackbot-1.0.0-source.tar.gz
sha256sum yoyackbot-1.0.0-source.tar.gz
```

## 깨끗한 경로에서 설치

1. 소스 tar를 별도 빈 작업 경로에 풀고 Python 3.13 가상환경을 만든다. `pip install -r requirements.lock` 뒤 `pip wheel --no-deps .`로 wheel을 만들거나, 제공된 wheel을 `pip install --no-deps <wheel>`로 설치한다. 잠금 의존성 버전과 wheel 메타데이터 버전 1.0.0을 확인한다.
2. [설정 예시](../.env.example)를 참고해 저장소 밖에 전용 계정 소유 0600 환경 파일을 마련한다. 토큰은 보호된 파일과 systemd `LoadCredential`, 모델 인증은 전용 계정의 보호된 경로를 사용한다. 인증값을 쉘 기록·진단 출력·배포 묶음에 넣지 않는다.
3. `python -m yoyackbot version`에서 `1.0.0`을 확인한다. 설정 복원은 기존 DB 경로가 환경에 지정된 상태에서 `restore-settings BACKUP NEW_DB`를 실행한다. 복원 명령은 환경의 DB 경로와 대상 경로가 같으면 거부한다. 그다음 격리된 `NEW_DB`와 별도 입력 경로를 지정해 `check-ready`로 CLI 인증·DB 쓰기·입력 경로를 확인한다. 운영 DB는 이 과정에서 쓰지 않는다.
4. [서비스 파일](../deploy/yoyackbot-dev.service)과 [전용 journal 설정](../deploy/journald-yoyackbot-dev.conf)을 대상 경로·계정에 맞춰 검토한다. 이전 프로세스를 멈춘 뒤 서비스를 시작하고 `health.ready`, Gateway, 주시 설정과 성공 대기 기록을 확인한다.

## 업데이트와 복귀

업데이트 전 코드 SHA, schema 버전, 설정 전용 백업과 이전 동작 버전을 기록한다. 정지→새 SHA 설치→`check-ready`→단일 서비스 시작→허용된 시험 채널 smoke 순서로 진행한다. 실패하면 [복구 절차](restore.md)와 [서비스 절차](service-operations.md)에 따라 격리 DB에서 schema 호환성을 먼저 확인한다. 운영 DB를 롤백 리허설에 복사하거나 무작정 이전 코드에 연결하지 않는다.

## 제거

서비스를 정상 중지하고 Gateway 종료·요청 임시 디렉터리 정리를 확인한다. 전용 systemd unit과 설치된 패키지는 운영자가 확인한 범위에서만 제거한다. DB·설정 백업·인증 파일은 보존·삭제 정책의 별도 운영 결정에 따르며 패키지 제거 과정에서 자동 삭제하지 않는다.

검증된 설치 명령과 실제 결과는 [1.0.0-P2 증거](../Plans/0.DevelopPhase/evidence/1.0.0-P2.md)에 기록한다.
