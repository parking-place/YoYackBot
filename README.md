# YoYackBot

**신창섭이 요약을 정상화하네** — 주시하도록 설정한 Discord 채널의 일반 사용자 대화를 Codex CLI로 요약하는 봇.

기능 명세, 개발 계획과 단계별 구현을 담고 있다. 현재 완료 단계와 실제 검증 범위는 진행 상태 문서를 따른다.

- [기능 명세 v1.5](Plans/shinchangseop_discord_summary_bot_spec_v1.5.md)
- [0.0.0 → 1.0.0 개발 계획](Plans/0.DevelopPhase/README.md)
- [1.0.0a 캐시·요약 기간 30일 계획](Plans/0.DevelopPhase/1.0.0a/README.md)
- [1.0.0b-1 대량 요약 복구·첫 30일 전체 수집 계획](Plans/0.DevelopPhase/1.0.0b-1/README.md) ([옛 1.0.0b 계획은 폐기](Plans/0.DevelopPhase/1.0.0b/README.md))
- [1.0.0c 여러 채널 동시 요청 최적화 계획](Plans/0.DevelopPhase/1.0.0c/README.md)
- [1.0.0d 실제 닉네임 표시 계획](Plans/0.DevelopPhase/1.0.0d/README.md)
- [1.0.1 사용량·요약 밀도·상태 명령](Plans/0.DevelopPhase/1.0.1/README.md)
- [1.0.2 수집 시작·중복 요청 안내 계획](Plans/0.DevelopPhase/1.0.2/README.md)
- [단계별 진행 상태](Plans/0.DevelopPhase/STATUS.md)
- [각 단계의 GitHub 업로드 완료 규칙](Plans/0.DevelopPhase/GIT_WORKFLOW.md)
- [개발 환경과 실행 방법](DEVELOPMENT.md)
- [주시 채널 설정 안내](docs/channel-settings.md)
- [1.0.0 설치·업데이트·제거](docs/install-release.md)
- [1.0.1 승격·복귀](docs/upgrade-rollback-1.0.1.md)
- [1.0.0 운영 인수·제한](docs/handoff-1.0.0.md)
- [변경 기록](CHANGELOG.md)

11개 버전, 버전별 5단계, 총 55단계로 개발한다. 각 단계는 작업과 검증을 마치고 **Git commit → GitHub push → 원격 반영 확인**까지 끝나야 완료된다.

1.0.0a, 1.0.0b-1, 1.0.0c, 1.0.0d, 1.0.1은 출시됐다. 1.0.0d에서 실제 닉네임 표시와 최대 4개 병렬 모델 호출을, 1.0.1에서 `사용량`·`[범위] 자세히`·`[범위] 짧게`·`상태` 명령을 제공한다. 단계별 실제 진행은 각 버전의 상태 문서를 따른다.

1.0.2의 수집 시작·진행 중 범위 안내도 별도 5단계 계획이며 아직 구현되지 않았다.

`.private`, 실제 인증값, Discord 대화 원문, SQLite DB와 임시 로그는 공개 저장소에 올리지 않는다.

현재 구현은 주시 채널의 일반 사용자 대화만 요약한다. `!!요약좀`의 기본 1시간, 숫자·분·시간·개수·오늘·일·주 옵션, 범위 뒤의 `자세히`/`짧게`, `!!요약좀 사용량`·`!!요약좀 상태`와 `!!요약좀 도움`을 지원한다. 사용량은 봇 계정이 보고하는 창(현재 주간 창)만 표시하고, 상태의 DB 크기는 모든 서버가 함께 쓰는 파일 크기다. 주시 채널은 서버 관리자가 `/채널 설정`으로 고르며, 결과는 요청한 채널에만 게시한다. 성공한 요약에는 5분 대기 시간이 적용된다.

검증과 제한은 [0.9.0 후보 검토](docs/release-candidate-0.9.0.md)와 [1.0.0 출시 검토](docs/release-review-1.0.0.md)에 기록한다. 사용자 요청으로 8시간·24시간 연속 시험과 [1.0.0 새 배포의 실제 게시 확인](Plans/0.DevelopPhase/1.0.0/POSTING_WAIVER.md)을 생략했다. 장시간 가용성과 새 배포의 게시 결과는 미검증이다. 실제 Discord 권한 회수, 일반 사용자 설정 거부 조작, 외부 자동 경고도 검증·구축되지 않았다. 중요한 날짜·결정은 원문과 대조해야 한다. 정식 `v1.0.0` 태그와 배포 결과는 [GitHub Release](https://github.com/parking-place/YoYackBot/releases/tag/v1.0.0)와 [단계 증거](Plans/0.DevelopPhase/STATUS.md)에서 확인한다.
