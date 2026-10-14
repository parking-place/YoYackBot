# 1.4.2a 승격과 복귀

1. **사전 확인**: [1.4.2a 상태](../Plans/0.DevelopPhase/1.4.2a/STATUS.md)에서 P1~P2 원격 완료를 확인한다. `VERSION`, wheel, 설치 모듈이 `1.4.2.1`이고 checkout이 후보의 정확한 코드 SHA인지 확인한다. wheel에 `yoyackbot/tone_presets.json`이 있어야 한다.
2. **중지 전 백업**: 진행 중 요약·`!!말하자면`이 없는지 서비스 로그로 확인한다(접수 줄 수 = 결과 줄 수). SQLite 온라인 백업과 설정 전용 백업을 만든 뒤 중지한다.
3. **설치와 점검**: 후보 wheel을 설치하고 checkout을 같은 SHA로 맞춘다. `check-ready`, 설치 모듈 버전, 프롬프트 `1.4.0-p6-v1`(변경 없음), Gateway·`health`·DB `quick_check`(schema 5)를 확인한다. 슬래시 명령은 1.4.2와 같은 12개다. DB·서비스 환경·봇 권한은 그대로다.
4. **확인**: 시험 서버의 `/말투` 메뉴에 새 프리셋 6종이 보이고, 하나를 고르면 안내 문구가 바로 그 말투로 바뀌는지 본다. 실제 확인을 하지 못한 항목은 **NOT_RUN**으로 남긴다.

**복귀**가 필요하면 서비스를 정상 중지한 다음 [`v1.4.2`](https://github.com/parking-place/YoYackBot/releases/tag/v1.4.2)의 wheel `1.4.2`와 checkout `109ce8b`를 함께 복원한다. DB·서비스 환경은 그대로 쓴다. 복귀하면 새 프리셋 6종이 메뉴에서 사라지고, 그 프리셋을 고른 서버의 말투·문구는 사용자정의 말투·문구로 그대로 쓰인다.
