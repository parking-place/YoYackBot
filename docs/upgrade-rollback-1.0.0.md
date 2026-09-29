# 1.0.0 업데이트·복귀 절차

0.9.0 출시 후보와 1.0.0은 모두 SQLite schema 5를 사용한다. 1.0.0 승격 시 schema 변환은 예상되지 않지만, 이전 schema에서의 변환 실패와 이전 코드 복귀는 **운영 DB가 아닌 격리 DB**에서 확인한다. Discord Gateway는 한 번에 한 프로세스만 연결한다.

1. 변경 전 서비스의 Git SHA, `VERSION`, DB `PRAGMA user_version`·`quick_check`, 주시 설정·성공 대기 시간의 개수를 기록한다. 전용 계정의 `backup-settings`로 설정 전용 0600 백업을 만들고, 키가 `format`, `schema`, `watch_meta`, `channels`, `cooldowns`뿐인지 확인한다. 백업이나 집계에 Guild/채널 ID, 메시지 원문, 토큰을 공개하지 않는다.
2. 격리된 빈 경로에 백업을 `restore-settings BACKUP NEW_DB`로 복원한다. 복원할 때 환경의 DB 경로는 실제 서비스 DB로 유지해야 한다. 이후 `YOYACK_DB_PATH=NEW_DB`, 별도 `YOYACK_INPUT_DIRECTORY`를 지정해 0.9.0 후보와 검증된 1.0.0 wheel의 `check-ready`를 순서대로 실행한다. schema, 주시 설정, revision, cooldown이 일치하고 메시지·coverage는 비어 있어야 한다. 0.9.0과 1.0.0은 schema 5에서 설정 복귀가 가능하다.
3. 실패 migration은 별도 합성 schema fixture로 시험한다. 의도적 충돌로 변환을 실패시킨 후 버전과 설정이 부분 변경되지 않았고 `check-ready`가 성공하지 않는지 검사한다. 별도 새 DB로 설정 전용 백업을 다시 복원해 `check-ready` 성공까지의 시간을 측정한다. 이 시험의 복구 시간은 실제 운영 장애의 보장 시간이 아니다.
4. 실제 승격 시 새 요청을 받지 않게 서비스를 멈추고 기존 SHA·설정 백업을 보존한다. 새 SHA 설치 후 `check-ready`를 먼저 통과시키고, 서비스 한 개만 시작해 Gateway·설정·요약 게시를 확인한다. `check-ready`, Gateway, 게시, DB 무결성, 보존 중 하나라도 실패하면 새 요청 수락을 중단한다. schema가 5인 한 이전 검증 SHA로 되돌리고 준비·Gateway를 다시 확인한다. schema가 다르면 운영 DB에 이전 코드를 직접 연결하지 않고, 설정 전용 백업에서 빈 캐시 DB를 복원해 격리 검증 후 전환한다. 원문 복원은 하지 않으며 허용 기간의 History만 다시 수집한다.

검증 결과·실측 복구 시간·미실행 항목은 [1.0.0-P3 증거](../Plans/0.DevelopPhase/evidence/1.0.0-P3.md)에 기록한다.
