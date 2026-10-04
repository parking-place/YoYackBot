# 1.3.2 승격과 복귀

1. **사전 확인**
   - [1.3.2 상태](../Plans/0.DevelopPhase/1.3.2/STATUS.md)에서 P1 원격 완료를 확인한다. P2 후보는 개발 LXC 검사·CI를 통과해야 한다.
   - `VERSION`, wheel, 설치 모듈이 `1.3.2`이고 checkout이 후보의 정확한 코드 SHA인지 확인한다.
2. **중지 전 백업**: 진행 중 요약·`!!말하자면`이 없는지 서비스 로그로 확인한다(접수 줄 수 = 결과 줄 수). SQLite 온라인 백업과 설정 전용 백업을 만든 뒤 중지한다.
3. **설치와 점검**
   - 후보 wheel을 설치하고 checkout을 같은 SHA로 맞춘다.
   - `check-ready`, 설치 모듈 버전, 프롬프트 `1.3.0-p6-v3`(변경 없음), Gateway·`health`·DB `quick_check`를 확인한다.
   - DB·서비스 환경·슬래시 명령은 바뀌지 않는다.
4. **확인**: 시험 채널에서 `!!요약좀`과 `!!말하자면`을 한 번씩 쓴 뒤, 서비스 호스트에서 다음을 실행해 단계별 ms 표가 나오는지 본다. 실제 확인을 하지 못한 항목은 **NOT_RUN**으로 남긴다.

   ```bash
   journalctl --namespace yoyackbot-dev -u yoyackbot-dev -o cat | python scripts/show_timings.py 5
   ```

**복귀**가 필요하면 서비스를 정상 중지한 다음 [`v1.3.1`](https://github.com/parking-place/YoYackBot/releases/tag/v1.3.1)의 wheel `1.3.1`과 checkout `cf50c6b`를 함께 복원한다. DB·서비스 환경은 그대로 쓴다. 복귀하면 `request_timing` 줄만 사라지고 나머지 동작은 같다.
