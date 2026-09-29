# 설정 백업과 빈 캐시 복구

개발 봇의 장기 백업 대상은 주시 채널 설정, 설정 revision, 성공 대기 시간뿐이다. 인증 파일과 환경 변수는 이 백업에 넣지 않고 별도의 비밀 관리 체계에서 공급한다. 메시지·작성자·요약문·coverage는 백업하지 않는다. 앱은 원문 DB의 자동 백업을 만들지 않는다.

## 평시 설정 백업

전용 계정의 환경을 불러온 뒤 `/opt/yoyackbot-dev/.venv/bin/python -m yoyackbot backup-settings`를 실행한다. 출력은 비공개 데이터 디렉터리의 `backups/settings-*.json`에 0600 권한으로 기록된다. 파일에는 Guild/채널 ID와 시간 정보가 있으므로 외부 저장소나 Git에 올리지 않는다. 한 달을 넘은 설정 백업은 새 백업을 검증한 뒤 제거한다. 이 파일에 `messages`, `coverage`, 원문, 토큰이 없음을 JSON 키와 비밀 검사를 통해 확인한다.

## 격리 복구와 교체

1. 서비스의 정확한 Git SHA, schema, 설정 백업 파일을 기록한다. `python -m yoyackbot restore-settings BACKUP NEW_DB`로 **새 경로**에 복원한다. 명령은 기존 파일과 현재 운영 DB 경로를 거부한다.
2. 복원된 DB에서 주시 채널·revision·cooldown 수를 비교한다. 메시지와 coverage는 비어 있어야 한다. 복원 직후 생성 시각 기준 7일 TTL 정리도 실행된다.
3. 새 DB를 지정한 격리 시험 인스턴스에서 Discord History로 허용 기간의 합성 대화를 다시 수집하고 결과를 확인한다. 원본 DB는 읽기 이외에 건드리지 않는다.
4. 운영 DB 교체가 정말 필요하면 서비스 중지, 별도 승인된 변경 절차, 원본 보존 범위 확인 후 새 DB를 연결한다. 봇의 접근 권한이 없거나 History가 불완전하면 채널 요약을 실패로 처리한다.

임시 전체 DB 사본이 불가피한 schema 전환에서는 전용 계정만 읽도록 0600으로 두고 24시간 안에 삭제한다. 사본도 원본 `created_at_us`로 7일 초과 메시지를 제거하고 `secure_delete=ON`·`VACUUM`·WAL checkpoint/truncate를 거쳐야 한다. 오래된 원문 DB 사본을 일상 백업으로 사용하지 않는다. live DB는 `journal_mode=DELETE`, `secure_delete=ON`을 기준으로 하며, cleanup은 `created_at` 기준으로 메시지와 coverage를 정리한다. 이전 전환에서 만든 원문 사본은 설정 전용 백업과 격리 복구를 검증한 뒤 없앤다.

설정 백업 삭제와 임시 사본 정리는 원본 DB 파일을 대상으로 하지 않는다. 복구 시험에서 실제 사용자 대화를 재게시하지 않고 합성 대화만 사용한다.
