# 1.1.2a 승격과 복귀

1. [1.1.2a 상태](../Plans/0.DevelopPhase/1.1.2a/STATUS.md)의 P1~P4 원격 완료와 P5 후보의 개발 LXC 검사·CI를 확인한다. `VERSION`, wheel, 설치 모듈이 `1.1.2.1`이고 checkout이 후보의 정확한 코드 SHA인지 확인한다. Gateway는 전용 계정에서 한 개만 실행한다.
2. **진행 중 요약이 없는지** 서비스 로그로 확인한 뒤(서비스 시작 이후 `summary_request_parsed` 수와 결과 줄 수가 같은지) 중지한다. 중지 전에 Gateway·주시 채널·DB 무결성을 확인하고, 전용 계정만 읽는 경로에 SQLite 온라인 백업과 설정 전용 백업을 만든다.
3. 서비스를 정상 중지하고 후보 wheel을 전용 가상환경에 설치한 뒤 서비스 checkout을 같은 코드 SHA로 맞춘다. `check-ready`, 설치 모듈 경로·버전, Gateway 재연결, 주시 채널 준비 상태, DB `quick_check`를 확인한다. **이 버전은 DB schema와 설정 항목을 바꾸지 않는다.**
4. 시작 후 명령어 동기화로 `/채널`의 기본 권한이 `애플리케이션 명령어 사용`으로 바뀐다. 서버 관리자가 연동 화면에 해 둔 개별 설정은 Discord가 그대로 우선한다. 지표 로그에 `topic_critique`·`name_underline`·`ongoing_jab`·`rating`이, 주시 채널 저장 시 `watched_channels_saved at=… count=…`가 남고 원문·사용자 ID는 남지 않는다.
5. 시험 서버에서 관리자·채널 관리 권한이 없는 계정으로 `/채널 설정`을 열어 저장하고, `!!요약좀`·`!!요약좀 [범위] 길게`의 `###` 제목·닉네임 밑줄·인용 비평 줄과 `!!요약좀 도움`의 새 문안을 확인한다. 실제 확인을 하지 못하면 **NOT_RUN**으로 남긴다.

복귀가 필요하면 서비스를 정상 중지한 다음 [이전 검증 릴리스](https://github.com/parking-place/YoYackBot/releases/tag/v1.1.2)의 wheel `1.1.2`와 checkout SHA `41c8e31`을 함께 복원한다. schema가 같으므로 DB는 그대로 쓴다. **복귀하면 명령어 동기화로 `/채널`의 기본 권한이 다시 채널 관리로 돌아가고, 요약은 굵은 소제목·`↳ *…*` 비평·밑줄 없는 이름으로, 도움말은 긴 문안으로 돌아간다.** `check-ready`·Gateway·DB 무결성을 다시 검사한다. 실제 복귀를 하지 않았다면 격리 호환성 검사와 절차만 증거로 기록한다.
