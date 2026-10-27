# 1.4.4a 승격과 복귀

1. **사전 확인**: [1.4.4a 상태](../Plans/0.DevelopPhase/1.4.4a/STATUS.md)에서 P1 원격 완료를 확인한다. `VERSION`, wheel, 설치 모듈이 `1.4.4.1`이고 checkout이 후보의 정확한 코드 SHA인지 확인한다. 공식 릴리스 `rust-v0.164.0`의 `codex-x86_64-unknown-linux-musl`(sha256 `b93f6811…`)과 `codex-code-mode-host-x86_64-unknown-linux-musl`(sha256 `8ee4f472…`)을 받아 `--version`이 `codex-cli 0.164.0`인지 본다.
2. **중지 전 백업**: 진행 중 요약·`!!말하자면`이 없는지 서비스 로그로 확인한다(접수 줄 수 = 결과 줄 수). SQLite 온라인 백업과 설정 전용 백업을 만든다. 지금 CLI 두 파일을 `/usr/local/bin/yoyack-codex-0.158.0`·`/usr/local/bin/yoyack-codex-code-mode-host-0.158.0`으로 복사해 둔 뒤 중지한다.
3. **설치와 점검**: 새 CLI 두 파일을 같은 운영 경로에 `root:root`, 755로 설치하고 sha256·버전을 대조한다. 후보 wheel을 설치하고 checkout을 같은 SHA로 맞춘다. `check-ready`, 설치 모듈 버전, Gateway·`health`·DB `quick_check`(schema 5)를 확인한다. 슬래시 명령은 1.4.4와 같은 16개다. DB·서비스 환경은 그대로다.
4. **확인**: 시험 서버에서 `!!요약좀`, `사용량`, 22:30 식단 평가가 평소처럼 되는지 본다. 실제 확인을 하지 못한 항목은 **NOT_RUN**으로 남긴다.

**복귀**가 필요하면 서비스를 정상 중지한 다음 `-0.158.0` 두 파일을 운영 경로로 되돌리고, [`v1.4.4`](https://github.com/parking-place/YoYackBot/releases/tag/v1.4.4)의 wheel `1.4.4`와 checkout `1034a3a`를 함께 복원한다. DB·서비스 환경은 그대로 쓴다. CLI만 되돌리고 패키지를 두면 버전 검사에서 요약이 멈추므로, 둘은 항상 함께 바꾼다.
