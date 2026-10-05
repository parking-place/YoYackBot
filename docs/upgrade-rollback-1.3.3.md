# 1.3.3 승격과 복귀

1. **사전 확인**
   - [1.3.3 상태](../Plans/0.DevelopPhase/1.3.3/STATUS.md)에서 P1~P5 원격 완료를 확인한다.
   - `VERSION`, wheel, 설치 모듈이 `1.3.3`이고 checkout이 후보의 정확한 코드 SHA인지 확인한다.
2. **중지 전 백업**: 진행 중 요약·`!!말하자면`이 없는지 서비스 로그로 확인한다(접수 줄 수 = 결과 줄 수). SQLite 온라인 백업과 설정 전용 백업을 만든 뒤 중지한다.
3. **설치와 점검**
   - 후보 wheel을 설치하고 checkout을 같은 SHA로 맞춘다.
   - `check-ready`, 설치 모듈 버전, 프롬프트 `1.3.3-p4-v1`, Gateway·`health`·DB `quick_check`를 확인한다.
   - DB·슬래시 명령은 바뀌지 않는다. 서비스 환경에 `YOYACK_MAX_INPUT_BYTES`가 없으면 새 기본값 500,000바이트가 적용된다. 값을 따로 넣어 두었다면 500,000 이하로 맞춘다(모델 문맥 안).
4. **확인**: 시험 채널에서 `!!요약좀`(긴 범위 포함)과 `!!말하자면`을 쓴 뒤 다음을 실행한다.
   - `journalctl --namespace yoyackbot-dev -u yoyackbot-dev -o cat | python scripts/show_timings.py 5`
   - 모든 호출이 `도구 0회`인지, 요약·후보 호출이 같은 시점에 시작하는지, 심사·선택이 `low`인지 본다.
   - 실제 확인을 하지 못한 항목은 **NOT_RUN**으로 남긴다.

**복귀**가 필요하면 서비스를 정상 중지한 다음 [`v1.3.2`](https://github.com/parking-place/YoYackBot/releases/tag/v1.3.2)의 wheel `1.3.2`와 checkout `6604a61`을 함께 복원한다. DB·서비스 환경은 그대로 쓴다. 복귀하면 대화를 다시 파일로 넘기므로 긴 범위의 가운데 누락(D10)이 되돌아오고, 요청 시간도 1.3.2 수준으로 돌아간다.
