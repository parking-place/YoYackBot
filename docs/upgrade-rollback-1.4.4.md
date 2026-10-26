# 1.4.4 승격과 복귀

1. **사전 확인**: [1.4.4 상태](../Plans/0.DevelopPhase/1.4.4/STATUS.md)에서 P1–P4 원격 완료를 확인한다. `VERSION`, wheel, 설치 모듈이 `1.4.4`이고 checkout이 후보의 정확한 코드 SHA인지 확인한다. 개발자 포털의 Server Members Intent는 1.4.3처럼 켜져 있어야 한다.
2. **중지 전 백업**: 진행 중 요약·`!!말하자면`이 없는지 서비스 로그로 확인한다(접수 줄 수 = 결과 줄 수). SQLite 온라인 백업과 설정 전용 백업을 만든 뒤 중지한다.
3. **설치와 점검**: 후보 wheel을 설치하고 checkout을 같은 SHA로 맞춘다. `check-ready`, 설치 모듈 버전, Gateway·`health`·DB `quick_check`(schema 5)와 새 선택 테이블 `exercise_settings`·`diet_daily`·`diet_week_runs`를 확인한다. 슬래시 명령은 `/운동채널`·`/운동역할`이 더해져 16개다. 서비스 환경은 그대로다.
4. **확인**: 시험 서버에서 `/운동채널 설정`·`/운동역할 설정` 화면, 22:30 평가의 정산 줄과 추정치 안내, 일요일 평가 뒤 주간 훈수를 본다. 실제 확인을 하지 못한 항목은 **NOT_RUN**으로 남긴다.

**복귀**가 필요하면 서비스를 정상 중지한 다음 [`v1.4.3a`](https://github.com/parking-place/YoYackBot/releases/tag/v1.4.3a)의 wheel `1.4.3.1`과 checkout `4e4933d`를 함께 복원한다. DB·서비스 환경은 그대로 쓴다. 복귀하면 정산 줄·주간 훈수·운동 명령이 사라지고, 새 테이블은 읽지 않는다(운동 설정은 설정 백업에 남는다).
