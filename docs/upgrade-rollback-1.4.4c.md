# 1.4.4c 승격과 복귀

1. **사전 확인**: [1.4.4c 상태](../Plans/0.DevelopPhase/1.4.4c/STATUS.md)에서 P1 원격 완료를 확인한다. `VERSION`, wheel, 설치 모듈이 `1.4.4.3`이고 checkout이 후보의 정확한 코드 SHA인지 확인한다. 운영 CLI는 1.4.4a의 `codex-cli 0.164.0`이다.
2. **중지 전 백업**: 진행 중 요약·`!!말하자면`이 없는지 서비스 로그로 확인한다(접수 줄 수 = 결과 줄 수). SQLite 온라인 백업과 설정 전용 백업을 만든 뒤 중지한다.
3. **설치와 점검**: 후보 wheel을 설치하고 checkout을 같은 SHA로 맞춘다. `check-ready`, 설치 모듈 버전, Gateway·`health`·DB `quick_check`(schema 5)를 확인한다. 슬래시 명령은 1.4.4와 같은 16개다. DB·서비스 환경·CLI는 그대로다.
4. **확인**: 22:30 식단 평가가 평소처럼 게시되는지 본다. 실제 확인을 하지 못한 항목은 **NOT_RUN**으로 남긴다.

**복귀**가 필요하면 서비스를 정상 중지한 다음 [`v1.4.4b`](https://github.com/parking-place/YoYackBot/releases/tag/v1.4.4b)의 wheel `1.4.4.2`와 checkout `419764b`를 함께 복원한다. CLI·DB·서비스 환경은 그대로 쓴다. 복귀하면 식단 두 호출은 서비스 강도 설정을 따른다(지금 설정은 medium이라 결과는 같다).
