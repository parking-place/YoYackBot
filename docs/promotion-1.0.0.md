# 1.0.0 제자리 승격 점검표

대상은 [사용자가 선택한 기존 개발 LXC·봇 계정](../Plans/0.DevelopPhase/1.0.0/TARGET_DECISION.md)이다. 0.9.0 후보와 1.0.0은 schema 5이므로 DB 구조 변경은 예상하지 않는다. 실제 토큰·인증·원문은 저장소 밖에 둔다.

1. 실행 중인 서비스 상태, Git SHA, 설치된 패키지 버전, `health.ready`, DB `quick_check`·schema, 설정/대기 건수와 요청 로그의 실패 건수를 기록한다. `backup-settings`로 설정 전용 백업을 만들고 0600과 허용 키만 확인한다. 이전 정상 SHA와 [복귀 절차](upgrade-rollback-1.0.0.md)를 확보한다.
2. 승격할 **정확한 SHA**의 소스 tar·wheel을 LXC에서 만들고 SHA-256과 구성 파일을 확인한다. 전용 가상환경에 잠금 의존성을 설치해 wheel 1.0.0의 `check-ready`를 운영 DB 대신 격리 DB에서 먼저 확인한다.
3. 기존 서비스를 멈춰 Gateway 연결과 봇 프로세스가 종료됐음을 확인한 뒤, 대상 SHA와 검증한 wheel을 서비스 가상환경에 설치한다. 운영 DB의 `quick_check`·schema가 그대로인지 확인하고 전용 계정의 `check-ready`를 통과시킨 다음 서비스 한 개만 시작한다. 서비스의 `health.ready`, Gateway 준비, 실제 실행 모듈·패키지 버전·코드 SHA가 대상과 일치해야 한다.
4. 허용한 합성 대화 채널에서 관리자 설정 보존, 도움말, 기본 시간·개수·오늘 옵션, 요약 게시, 중복 차단과 **성공한 게시 후에만** 시작되는 대기 시간을 확인한다. 주시하지 않는 채널에서는 요약을 게시하지 않는다. 실제 개인 대화는 시험에 사용하지 않는다.
5. 배포 직후 서비스 실패 건수·자원(RSS/CPU/작업 수)·DB 무결성·7일 초과 메시지/coverage·임시 요청 파일·원문 백업 여부를 점검한다. `health.ready=false`, 무결성 오류, 잘못된 채널 게시, 원문 누출, 반복 모델·History·게시 실패가 있으면 새 요청 수락을 중단하고 [검증된 복귀 절차](upgrade-rollback-1.0.0.md)를 적용한다.

8시간·24시간 지속 시간 시험은 [사용자 요청](../Plans/0.DevelopPhase/DURATION_WAIVER.md)으로 생략한다. 즉시 점검 결과는 [1.0.0-P4 증거](../Plans/0.DevelopPhase/evidence/1.0.0-P4.md)에 SHA와 시각을 함께 기록한다. 장시간 가용성은 PASS로 표시하지 않는다.
