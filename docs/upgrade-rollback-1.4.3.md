# 1.4.3 승격과 복귀

1. **사전 확인**: [1.4.3 상태](../Plans/0.DevelopPhase/1.4.3/STATUS.md)에서 P1~P4 원격 완료를 확인한다. `VERSION`, wheel, 설치 모듈이 `1.4.3`이고 checkout이 후보의 정확한 코드 SHA인지 확인한다.
2. **포털 intent**: 1.4.3은 Gateway intent `members`(특권)를 요청한다. 개발자 포털에서 Server Members Intent가 켜져 있어야 한다. 애플리케이션 flags의 `GATEWAY_GUILD_MEMBERS` 또는 `GATEWAY_GUILD_MEMBERS_LIMITED`로 확인한다. 꺼져 있으면 Gateway 연결이 실패하므로 배포하지 않는다.
3. **중지 전 백업**: 진행 중 요약·`!!말하자면`이 없는지 서비스 로그로 확인한다(접수 줄 수 = 결과 줄 수). SQLite 온라인 백업과 설정 전용 백업을 만든 뒤 중지한다.
4. **설치와 점검**: 후보 wheel을 설치하고 checkout을 같은 SHA로 맞춘다. `check-ready`, 설치 모듈 버전, 프롬프트 `1.4.0-p6-v1`, Gateway 연결·`health`·DB `quick_check`(schema 5)를 확인한다. 선택 테이블 `diet_settings`·`diet_runs`가 생기고, 슬래시 명령이 14개(1.4.2a의 12개 + 돼지채널·돼지역할)로 동기화되는지 본다.
5. **확인**: 시험 서버에서 `/돼지채널 설정`·`/돼지역할 설정`을 정하고, 21:00 호출·22:00 개별 호출·22:30 평가(사진 포함)를 본다. 실제 확인을 하지 못한 항목은 **NOT_RUN**으로 남긴다.

**복귀**가 필요하면 서비스를 정상 중지한 다음 [`v1.4.2a`](https://github.com/parking-place/YoYackBot/releases/tag/v1.4.2a)의 wheel `1.4.2.1`과 checkout `54b3fbc`를 함께 복원한다. DB·서비스 환경은 그대로 쓴다. 복귀하면 재촉·평가가 멈추고 두 명령이 사라진다. 1.4.2a는 `members` intent를 요청하지 않으니 포털 설정은 그대로 둬도 된다.
