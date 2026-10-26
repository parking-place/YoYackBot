# 1.4.3a 승격과 복귀

1. **사전 확인**: [1.4.3a 상태](../Plans/0.DevelopPhase/1.4.3a/STATUS.md)에서 P1 원격 완료를 확인한다. `VERSION`, wheel, 설치 모듈이 `1.4.3.1`이고 checkout이 후보의 정확한 코드 SHA인지 확인한다. 개발자 포털의 Server Members Intent는 1.4.3처럼 켜져 있어야 한다.
2. **중지 전 백업**: 진행 중 요약·`!!말하자면`이 없는지 서비스 로그로 확인한다(접수 줄 수 = 결과 줄 수). SQLite 온라인 백업과 설정 전용 백업을 만든 뒤 중지한다.
3. **설치와 점검**: 후보 wheel을 설치하고 checkout을 같은 SHA로 맞춘다. `check-ready`, 설치 모듈 버전, Gateway·`health`·DB `quick_check`(schema 5)를 확인한다. 슬래시 명령은 1.4.3과 같은 14개다. DB·서비스 환경은 그대로다.
4. **확인**: 시험 서버에서 21:00 호출에 역할 인원이 개별로 멘션돼 알림이 오는지, 22:30 평가에 역할이 없는 게시자도 들어가는지 본다. 실제 확인을 하지 못한 항목은 **NOT_RUN**으로 남긴다.

**복귀**가 필요하면 서비스를 정상 중지한 다음 [`v1.4.3`](https://github.com/parking-place/YoYackBot/releases/tag/v1.4.3)의 wheel `1.4.3`과 checkout `b267c00`을 함께 복원한다. DB·서비스 환경은 그대로 쓴다. 복귀하면 21:00 호출은 역할 멘션만 하고, 평가는 역할 인원만 본다.
