# 개발 진행 상태

기준일: 2026-09-29. 개발 완료 **51 / 55**. 완료한 단계는 원격 증거를 확인했다. 나머지 4개 단계는 PLANNED 또는 진행 중이다. 계획 문서 작성·GitHub 게시 자체는 제품 단계의 완료 수에 포함하지 않는다.

## 상태 규칙

| 상태 | 의미 |
|---|---|
| PLANNED | 계획만 작성, 구현·검증 미착수 |
| IN_PROGRESS | 해당 단계 작업 또는 수정 중 |
| VERIFIED | 해당 단계 검사 통과, 원격 게시 절차 전 |
| PUSH_PENDING | commit 또는 push/원격 확인/필수 CI 미완료 |
| DONE | 구현·검증·증거와 종료 문서의 원격 반영 확인까지 완료 |
| BLOCKED | 환경·의존성·결함 등으로 진행 불가, 원인과 해소 조건 기록 |

DONE 표시만으로 완료를 인정하지 않는다. [Git 절차](GIT_WORKFLOW.md)에 따라 종료 문서 commit까지 원격에 존재해야 한다. 상태를 바꿀 때 이 파일의 완료 개수와 해당 단계 파일·버전 개요도 함께 갱신한다.

원격 증거 E는 이미 push를 확인한 증거 commit의 URL을 기록한다. 자기 자신 commit의 SHA를 문서 안에 넣는 방식은 사용하지 않는다.

## 단계 목록

| 단계 | 작업 | 상태 | 구현 C SHA | 원격 증거 E | 제약/차단 사유 |
|---|---|---|---|---|---|
| 0.0.0-P1 | [요구사항·범위·완료 규칙 확정](0.0.0/01-requirements.md) | DONE | `e6322e1e4c4c1bd2a471ed3aef5da52cec5024aa` | [evidence E](https://github.com/parking-place/YoYackBot/commit/e7598b208d0260e40569fc6791849cb926d69a64) | 문서 검사 PASS; 제품 검사 NOT_RUN |
| 0.0.0-P2 | [프로젝트 구조·런타임·의존성 고정](0.0.0/02-project-baseline.md) | DONE | `afaa0e0251ef7a947baee4f0c515cdccb796abb7` | [evidence E](https://github.com/parking-place/YoYackBot/commit/6197806221314345792f89ec90fc63db5d660864) | OpenJevLXC Debian 13 x86_64, Python 3.13.5, 격리 venv; 실제 Discord/Codex 호출 없음 검증; 세부 결과는 증거 파일 |
| 0.0.0-P3 | [LXC·Discord·Codex 선행 조건 확인](0.0.0/03-environment-preflight.md) | DONE | `1fcd9952460ea515228d898a313577c79d73040a` | [evidence E](https://github.com/parking-place/YoYackBot/commit/ddd0a36d7cfdab231e362def5d70f9a9f9685781) | OpenJevLXC와 실제 Discord REST 읽기 점검; 공개 문서 비밀정보 검사 검증; 세부 결과는 증거 파일 |
| 0.0.0-P4 | [설정·인터페이스·오류 계약 정의](0.0.0/04-interfaces-config.md) | DONE | `82d66ba8ba21098abfbb8da8c64c995c76b7f7c2` | [evidence E](https://github.com/parking-place/YoYackBot/commit/85015483ebd7958b01c3ea050d0710826dbdd421) | OpenJevLXC 격리 Python 3.13.5/discord.py 2.7.1; 합성 계약·설정 검사 검증; 세부 결과는 증거 파일 |
| 0.0.0-P5 | [검증 실행 기반·초기 버전 게이트](0.0.0/05-verification-baseline.md) | DONE | `366050bf2a6698577a286b35c635ca40c05f4510` | [evidence E](https://github.com/parking-place/YoYackBot/commit/7d99013bd027cfeede5a95ed7a007d9ff6d20895) | OpenJevLXC 독립 체크아웃의 pinned runner + GitHub Actions Source checks 검증; 세부 결과는 증거 파일 |
| 0.1.0-P1 | [Discord 연결·이벤트 경계 구현](0.1.0/01-gateway.md) | DONE | `5c8ba1716605a626166e48099936cb81649d822e` | [evidence E](https://github.com/parking-place/YoYackBot/commit/b21f194b6ed8a0e89916d72520845e5af63c4c8b) | OpenJevLXC 개발 Discord Guild·Gateway, Python 3.13.5 검증; 세부 결과는 증거 파일 |
| 0.1.0-P2 | [채널 설정 명령·관리 권한 구현](0.1.0/02-channel-selector.md) | DONE | `eaa8b54faaf7632449412d07ce3f8c9ce80accc1` | [evidence E](https://github.com/parking-place/YoYackBot/commit/bc992203f91a9016d8cbc58e70f64eaeff79ebac) | OpenJevLXC 개발 Discord Guild; 관리자 실제 선택·저장, Python 3.13.5 검증; 세부 결과는 증거 파일 |
| 0.1.0-P3 | [주시 설정 영속화·서버 격리](0.1.0/03-settings-store.md) | DONE | `3135a352b1358ee4e7d86e10c4a17c1cf0b38bca` | [evidence E](https://github.com/parking-place/YoYackBot/commit/d9f6de656841d309245a349a221aaa9165c0c876) | OpenJevLXC Python 3.13.5, 실제 개발 Guild의 SQLite 설정 및 재시작 검증; 세부 결과는 증거 파일 |
| 0.1.0-P4 | [주시 추가·해제·미주시 차단](0.1.0/04-watch-enforcement.md) | DONE | `93911253e629692326cbcf9999076f8f6e7b827f` | [evidence E](https://github.com/parking-place/YoYackBot/commit/2703e30277b9aa746a9870674a16caee08ab11f6) | OpenJevLXC Python 3.13.5 합성 어댑터 검사; 실제 Gateway Guild 2개 접속 확인 검증; 세부 결과는 증거 파일 |
| 0.1.0-P5 | [채널 설정 실환경 검증·버전 종료](0.1.0/05-channel-acceptance.md) | DONE | `16f5af9391d8fd539b23f5ee89aab24d36f67991` | [evidence E](https://github.com/parking-place/YoYackBot/commit/7dc6b4edd9f8473da643aca4d22456a20b6dc3d5) | OpenJevLXC Python 3.13.5, 개발 Discord Guild 2개 실제 관리자 설정·재시작 검증; 세부 결과는 증거 파일 |
| 0.2.0-P1 | [포함형 트리거·도움말 우선 처리](0.2.0/01-trigger-help.md) | DONE | `071dde3b14361f8cd152eae8a71d677adc4ff94c` | [evidence E](https://github.com/parking-place/YoYackBot/commit/b69ddd3279ef9826ead67ce39bedf5d708f0e4c1) | OpenJevLXC Python 3.13.5 합성 메시지·Discord 채널 대역 검증; 세부 결과는 증거 파일 |
| 0.2.0-P2 | [옵션 우선순위·문법 구현](0.2.0/02-option-parser.md) | DONE | `398c12b312ef931737e9dc0a5e6552e1374ef0c7` | [evidence E](https://github.com/parking-place/YoYackBot/commit/92419906880f1ff77ad8d516d9560aadf21fa294) | OpenJevLXC Python 3.13.5 합성 명령 문자열 검증; 세부 결과는 증거 파일 |
| 0.2.0-P3 | [숫자·설정 상한 검증](0.2.0/03-limits.md) | DONE | `eb51916e79ba510ac58bfb048c6f4be48f596379` | [evidence E](https://github.com/parking-place/YoYackBot/commit/e72afae06da2c874b6e385139558d0658b951b20) | OpenJevLXC Python 3.13.5 합성 옵션·설정 검증; 세부 결과는 증거 파일 |
| 0.2.0-P4 | [KST 오늘·수락 시각·정렬 경계](0.2.0/04-time-window.md) | DONE | `d1bf0a7c57c30a5a8ed98bea17ad306554c4acd5` | [evidence E](https://github.com/parking-place/YoYackBot/commit/d1f37aa8f06e49e2cf72eb5110bf2e3bbb544913) | OpenJevLXC Python 3.13.5 합성 UTC/KST 시각·메시지 검증; 세부 결과는 증거 파일 |
| 0.2.0-P5 | [명령 전체 회귀·Discord 안내 검증](0.2.0/05-parser-acceptance.md) | DONE | `2747eed67029ba0a6ca92592f6a95f61f1fd2bd1` | [evidence E](https://github.com/parking-place/YoYackBot/commit/435539d68aa5f437b486b4333412fcf147a0553d) | OpenJevLXC Python 3.13.5 합성 회귀 + 개발 Discord 실제 사용자 입력·출력 확인 검증; 세부 결과는 증거 파일 |
| 0.3.0-P1 | [메시지·범위 schema와 migration](0.3.0/01-message-schema.md) | DONE | `8933210ecee55156c6382ae19eb121624f3e9042` | [evidence E](https://github.com/parking-place/YoYackBot/commit/c8d1f2f9116861b98b474730751b5a51e6f670ca) | OpenJevLXC Python 3.13.5 실제 설정 DB 격리 복사본 + 합성 SQLite 검증; 세부 결과는 증거 파일 |
| 0.3.0-P2 | [주시 채널 실시간 upsert·필터](0.3.0/02-realtime-ingest.md) | DONE | `7471afd4ef7b120e4db247e2ee9fc58180c0afbe` | [evidence E](https://github.com/parking-place/YoYackBot/commit/171cc545dbd7ee98f8f2992386470798c14baf90) | OpenJevLXC Python 3.13.5 합성 필터·원자 트랜잭션 + 개발 Discord 실제 사용자 메시지 검증; 세부 결과는 증거 파일 |
| 0.3.0-P3 | [수정·삭제·7일 자동 정리](0.3.0/03-edits-retention.md) | DONE | `40787acd7f063c29b0a3baaf6ff6cc5ab1f78c8a` | [evidence E](https://github.com/parking-place/YoYackBot/commit/ea037a767c2a3f23654adf5bee94eb666ed1d272) | OpenJevLXC Python 3.13.5 격리 SQLite + 개발 Gateway 재시작 검증; 세부 결과는 증거 파일 |
| 0.3.0-P4 | [완료 구간·빈 구간·연결 공백](0.3.0/04-coverage.md) | DONE | `26baaaa2b1110c6ebb9de7b4633f92023820f472` | [evidence E](https://github.com/parking-place/YoYackBot/commit/1e37657de74f580c71732a15edbb0625c23e53fc) | OpenJevLXC Python 3.13.5 합성 coverage + 실제 설정·캐시 DB 격리 복사본 검증; 세부 결과는 증거 파일 |
| 0.3.0-P5 | [캐시 동시성·장애·버전 검증](0.3.0/05-cache-acceptance.md) | DONE | `25a702434b84a42e33774ed405dc1888be941c75` | [evidence E](https://github.com/parking-place/YoYackBot/commit/a640cb2cb2248ca2f6e1aab705415a7148315b79) | OpenJevLXC Python 3.13.5 격리 장애·동시성 DB + 실제 개발 DB migration·Gateway 검증; 세부 결과는 증거 파일 |
| 0.4.0-P1 | [History 페이지 조회·현재 채널 제한](0.4.0/01-history-pages.md) | DONE | `175c4131aef2de9ad46ebb1f9e2cc774c0e34bf7` | [evidence E](https://github.com/parking-place/YoYackBot/commit/3ec5875b55546f8a0a4ad37f03d0ffc538b74ca1) | OpenJevLXC Python 3.13.5, 개발 Discord 주시 채널 실제 History 검증; 세부 결과는 증거 파일 |
| 0.4.0-P2 | [시간 범위 차집합 조회·완료 확정](0.4.0/02-cache-gaps.md) | DONE | `8a28f56ba69dab7509fd8acdbbe1810a572f0260` | [evidence E](https://github.com/parking-place/YoYackBot/commit/4f0315554f3724ca062629adb5e9f5deafa8e95d) | OpenJevLXC Python 3.13.5, 격리 SQLite 및 합성 History 검증; 세부 결과는 증거 파일 |
| 0.4.0-P3 | [7일 초과·최대 4주 요청 처리](0.4.0/03-older-than-retention.md) | DONE | `795a0e2384fde2c73b864f79d1cb0448f59f96cb` | [evidence E](https://github.com/parking-place/YoYackBot/commit/2a4ba995c107d05e4967c6424fc0aef5a8d85dd7) | OpenJevLXC Python 3.13.5, 격리 SQLite·합성 History 검증; 세부 결과는 증거 파일 |
| 0.4.0-P4 | [최신 일반 사용자 X개 보충](0.4.0/04-recent-count.md) | DONE | `32d12ecdca2f3aa788f01cf9032caa283c77eece` | [evidence E](https://github.com/parking-place/YoYackBot/commit/4d25167eb104b1738b78de9f91d00761f21c1d20) | OpenJevLXC Python 3.13.5, 격리 SQLite·합성 Discord History 검증; 세부 결과는 증거 파일 |
| 0.4.0-P5 | [캐시 fallback·빈 대화·수집 통합 게이트](0.4.0/05-collection-acceptance.md) | DONE | `23fe1875e5a2d1d7ba40a85a6d7aefc0b47d0e81` | [evidence E](https://github.com/parking-place/YoYackBot/commit/851e5509b2809e506b37a3a12362c1c0894f423a) | OpenJevLXC Python 3.13.5, 격리 SQLite + 개발 Discord 실제 History 검증; 세부 결과는 증거 파일 |
| 0.5.0-P1 | [CLI·인증·GPT-6 Luna Light 확인](0.5.0/01-cli-model-contract.md) | DONE | `512a13164467d919f8dd13365dcd24d3fcf6e1f9` | [evidence E](https://github.com/parking-place/YoYackBot/commit/da7b0722e453e65a71a1e3804133ce116d4295e6) | OpenJevLXC Python 3.13.5; bot account codex-cli 0.158.0 검증; 세부 결과는 증거 파일 |
| 0.5.0-P2 | [요청 입력 파일·표시명 정규화](0.5.0/02-input-files.md) | DONE | `59be11f57d0a7538b309cbf3bf3086db6e5f9c8a` | [evidence E](https://github.com/parking-place/YoYackBot/commit/276186ec7cba3daa19aa9925b9dce40dcbf77cc1) | OpenJevLXC Python 3.13.5; isolated copy of live SQLite cache 검증; 세부 결과는 증거 파일 |
| 0.5.0-P3 | [비대화형 subprocess·파일/도구 격리](0.5.0/03-subprocess-isolation.md) | DONE | `abb7d700acdc1ebe1bc7e29432b2eed20cf11ffb` | [evidence E](https://github.com/parking-place/YoYackBot/commit/778f545d02e72325493e0940ed80d52271c07460) | OpenJevLXC dedicated bot account; pinned Codex CLI and code-mode host 0.158.0; bubblewrap namespace 검증; 세부 결과는 증거 파일 |
| 0.5.0-P4 | [시간·입력 제한·취소·잔여 파일 정리](0.5.0/04-timeouts-cleanup.md) | DONE | `c4f9fbacb90b702de695805c126b7d60424584c3` | [evidence E](https://github.com/parking-place/YoYackBot/commit/31fc4b054098e2c06ef9353d3357cf5a1c396ea0) | OpenJevLXC Python 3.13.5; dedicated bot account and isolated synthetic Codex runs 검증; 세부 결과는 증거 파일 |
| 0.5.0-P5 | [실제 모델 연동·실패 회귀 게이트](0.5.0/05-engine-acceptance.md) | DONE | `6053f209b3d8ee4dd72df99d7b5c5a1fb8017cd2` | [evidence E](https://github.com/parking-place/YoYackBot/commit/b49a9dc0ee24286d090f8e659270aa65769c0ac5) | OpenJevLXC dedicated bot account; isolated real gpt-6-luna low calls; synthetic Discord records 검증; 세부 결과는 증거 파일 |
| 0.6.0-P1 | [화자·결정·미해결 중심 프롬프트](0.6.0/01-summary-prompt.md) | DONE | `838e3195c3815e16a304e8adae1ce3c2529b7d2a` | [evidence E](https://github.com/parking-place/YoYackBot/commit/73b1e9a593b612f53e235115e7bbc77c3e821c1c) | OpenJevLXC Python 3.13.5; synthetic fixture and prompt checks 검증; 세부 결과는 증거 파일 |
| 0.6.0-P2 | [사실성·화자 귀속·하오체 평가](0.6.0/02-quality-evaluation.md) | DONE | `b989a4738455a3f7d8144c654c43b19a458da206` | [evidence E](https://github.com/parking-place/YoYackBot/commit/fc007e6205a2f500e9cdcac52dac0902fecb9b8b) | OpenJevLXC dedicated bot account; 20 synthetic real gpt-6-luna calls 검증; 세부 결과는 증거 파일 |
| 0.6.0-P3 | [머리말·실제 범위·긴 메시지 분할](0.6.0/03-format-split.md) | DONE | `fa9584434c0a00116acfa7fa634bbbe4862c361a` | [evidence E](https://github.com/parking-place/YoYackBot/commit/55705f7522ec1220e2d0a01d67e1f46e04c6b534) | OpenJevLXC Python 3.13.5; synthetic formatter tests 검증; 세부 결과는 증거 파일 |
| 0.6.0-P4 | [같은 채널 전송·부분 실패 처리](0.6.0/04-delivery.md) | DONE | `8bb3ea0c48d11f7b64a7b9d83044be67acebd086` | [evidence E](https://github.com/parking-place/YoYackBot/commit/c8025acda69e2d175f28d611b5676fb708bdb03b) | OpenJevLXC Python 3.13.5 and live development Discord text channel; synthetic publication only 검증; 세부 결과는 증거 파일 |
| 0.6.0-P5 | [수집부터 게시까지 출력 통합 게이트](0.6.0/05-output-acceptance.md) | DONE | `2b914eae1e0dcd030b503c28519a9b4f2ced9b7a` | [evidence E](https://github.com/parking-place/YoYackBot/commit/9e2ef7399a24cf3655d902a5af1ebef7c65b1795) | OpenJevLXC dedicated bot account and live development Discord watched channel; real model and synthetic user messages 검증; 세부 결과는 증거 파일 |
| 0.7.0-P1 | [채널별 원자적 상태·명령 연결](0.7.0/01-channel-state.md) | DONE | `4cc3bfc424fde7e00ab02451ae0079a85185d6af` | [evidence E](https://github.com/parking-place/YoYackBot/commit/16d7c5b03e479ae44ab6fd9bff3a218390d055ce) | OpenJevLXC Python 3.13.5; synthetic workflow and SQLite contention regression 검증; 세부 결과는 증거 파일 |
| 0.7.0-P2 | [게시 성공 기준 300초·남은 시간](0.7.0/02-success-cooldown.md) | DONE | `0a7b7fc7c9a52e8c26fad869bad5a99bab8b5edc` | [evidence E](https://github.com/parking-place/YoYackBot/commit/adbdfb6092b2a45e349325d30994ca22e2c63a01) | DiscordBotLXC, 0a7b7fc, MOCK; 운영 DB의 격리 복사본 검증; 세부 결과는 증거 파일 |
| 0.7.0-P3 | [실패·주시 해제·취소 시 상태 복구](0.7.0/03-failure-recovery.md) | DONE | `6d085f95182ed9650db49eb62dcddd2cb12932f7` | [evidence E](https://github.com/parking-place/YoYackBot/commit/88049558c60d4d3feaaac1ec2f43c4e16a650795) | DiscordBotLXC Python 3.13, 합성 장애 주입; 실제 Discord 권한 변경 미실행 검증; 세부 결과는 증거 파일 |
| 0.7.0-P4 | [전역 실행 제한·대기열·재시작](0.7.0/04-global-queue.md) | DONE | `e22f972989d92af105153fe3127ecb7cc2fbd25a` | [evidence E](https://github.com/parking-place/YoYackBot/commit/3edd27275ac13c3ebb3270d7a8b39be6f39bbf16) | DiscordBotLXC Python 3.13, 합성 동시 요청·재시작 모의 검증; 세부 결과는 증거 파일 |
| 0.7.0-P5 | [전체 명령·상태 실환경 회귀 게이트](0.7.0/05-workflow-acceptance.md) | DONE | `46c7d10a37fbbc9a4449acfadea7e6b9b4dca1df` | [evidence E](https://github.com/parking-place/YoYackBot/commit/3beab75bd4f7d81aba5a11a768d489153b01bd2e) | DiscordBotLXC 전용 계정 + 개발 Discord 2개 주시 채널 + 실제 gpt-6-luna; 46c7d10 검증; 세부 결과는 증거 파일 |
| 0.8.0-P1 | [전용 계정 서비스·자동 재시작](0.8.0/01-service.md) | DONE | `501bc47f23300a00bafdf20cc5143b1ba836a594` | [evidence E](https://github.com/parking-place/YoYackBot/commit/5fcab7f5bca5b61a1cbb82473e0be9e36dfd4c13) | 개발 LXC 전용 systemd 서비스, C 501bc47, Ruff·214 pytest·verify_repo·systemd-analyze·CI 검증; 세부 결과는 증거 파일 |
| 0.8.0-P2 | [원문 없는 로그·지표·상태 확인](0.8.0/02-observability.md) | DONE | `31064e4346e045dd071e703f4d6d4330f4baf89d` | [evidence E](https://github.com/parking-place/YoYackBot/commit/681298d74af31e8de70d38e05b51b73862d59964) | 개발 LXC 정확 SHA 31064e4, Ruff·216 pytest·계획 검증·systemd 검증·GitHub CI, 전용 journal 운영 시험 검증; 세부 결과는 증거 파일 |
| 0.8.0-P3 | [설정 백업·캐시 재생성·복구](0.8.0/03-restore.md) | DONE | `4fd9bdb37018c79e2a40d62de3dd12884a0ab249` | [evidence E](https://github.com/parking-place/YoYackBot/commit/964d6eabd9e5323fe7a6687f5acdf1334b2727eb) | 개발 LXC 정확 SHA 4fd9bdb, Ruff·218 pytest·계획 검증·GitHub CI, 전용 계정 실제 설정 백업/격리 복원 검증; 세부 결과는 증거 파일 |
| 0.8.0-P4 | [비밀·파일·프롬프트 입력 보안 점검](0.8.0/04-security-review.md) | DONE | `bf00432bbf342547a94bdcaf6be6d99fd230f07e` | [evidence E](https://github.com/parking-place/YoYackBot/commit/d6317e38391babd8aeccefa1861c76867b14258d) | 개발 LXC 정확 SHA bf00432(실행 코드 1438d81), Ruff·221 pytest·전체 Git 이력 스캔·CI·실제 인증 모델 공격성 합성 입력 검증; 세부 결과는 증거 파일 |
| 0.8.0-P5 | [자원 한도·장시간 실행·운영 게이트](0.8.0/05-resource-soak.md) | DONE | `790c047715f7e1a3c93d8f2f007bc2b3094e01bd` | [evidence E](https://github.com/parking-place/YoYackBot/commit/d0bbe3ea1b40bfc7661578c994521e667bd90eaf) | 개발 LXC 고정 SHA 790c047, 실제 봇 서비스와 격리 합성 부하; GitHub CI 검증; 세부 결과는 증거 파일 |
| 0.9.0-P1 | [요구사항 전체 회귀·누락 확인](0.9.0/01-full-regression.md) | DONE | `797de3578c9583135d69b6ed014a3bbb5643d018` | [evidence E](https://github.com/parking-place/YoYackBot/commit/6ce31dd17d12f4d671b81bb1b57b059c701dcf26) | 개발 LXC 고정 SHA 797de35, GitHub CI; 로컬 원격 이력 대조는 문서 검증 검증; 세부 결과는 증거 파일 |
| 0.9.0-P2 | [개발 Discord 사용자 흐름·품질 베타](0.9.0/02-beta-usage.md) | DONE | `b0e8946975417cba0e251e18ee3739faf3696ef3` | [evidence E](https://github.com/parking-place/YoYackBot/commit/a4fd40263be24eee6b9f0e8cfb1df0caa85ea5dd) | 개발 LXC 정확 SHA b0e8946, 실제 Discord 시험 채널·일반 사용자 이벤트와 실제 GPT-6 Luna 합성 fixture; GitHub CI 검증; 세부 결과는 증거 파일 |
| 0.9.0-P3 | [장애 복구·권한 회수·재시작 훈련](0.9.0/03-fault-drills.md) | DONE | `24e0d1a1039d9fb222c5a94a810eece7144a0f26` | [evidence E](https://github.com/parking-place/YoYackBot/commit/caeed531d604d65a9afc6ceeb5381c15f40dac2b) | 개발 LXC 정확 SHA 24e0d1a; 격리 pytest fault fixtures와 실제 전용 봇 서비스 SIGKILL/자동 복구; GitHub CI 검증; 세부 결과는 증거 파일 |
| 0.9.0-P4 | [베타 부하·보존 경계 검증](0.9.0/04-beta-soak.md) | DONE | `ee042c809ab4006ad66018eb872714e003e11306` | [evidence E](https://github.com/parking-place/YoYackBot/commit/c049fd3a78132813b9f0f0c6f1a518678d5e4f92) | 개발 LXC 정확 SHA ee042c8, 실제 서비스 관측+격리 합성 120초/120회, SQLite 보존 fixture, 실제 인증 모델 비게시 probe; GitHub CI 검증; 세부 결과는 증거 파일 |
| 0.9.0-P5 | [출시 후보 고정·차단 결함 종료](0.9.0/05-rc-freeze.md) | DONE | `3930c409136cf9630e2cadfddd228fcb86ce50be` | [evidence E](https://github.com/parking-place/YoYackBot/commit/d54b9199c892ec453cc3d7cb8f449525739b376b) | 개발 LXC 정확 SHA 3930c40, 공개 원격 이력 및 GitHub CI 검토 검증; 세부 결과는 증거 파일 |
| 1.0.0-P1 | [정식 출시 범위·증거 최종 검토](1.0.0/01-release-review.md) | DONE | `343aa7c19409f595686b22ac2dc758c008ea7446` | [evidence E](https://github.com/parking-place/YoYackBot/commit/31c46c94c90f08b60714ab4313b9bf0a790d8a81) | 원격 main 선행 50단계 이력, 개발 LXC 정확 SHA 343aa7c, GitHub CI 검증; 세부 결과는 증거 파일 |
| 1.0.0-P2 | [버전·배포 산출물·설정 재현성](1.0.0/02-release-package.md) | PLANNED | — | — | 미착수 |
| 1.0.0-P3 | [업데이트·migration·롤백 리허설](1.0.0/03-rollback-rehearsal.md) | PLANNED | — | — | 미착수 |
| 1.0.0-P4 | [운영 배포·동일 SHA smoke·초기 관측](1.0.0/04-production-validation.md) | PLANNED | — | — | 미착수 |
| 1.0.0-P5 | [GitHub 정식 릴리스·최종 인수](1.0.0/05-release-publish.md) | PLANNED | — | — | 미착수 |

## 버전/배포 기록

0.0.0 개발 기준선을 [PR #1](https://github.com/parking-place/YoYackBot/pull/1)로 `main`에 통합했다(merge `577bb0f654e436b44f48a68a98608714a2cf6c22`). 이 기준선 단계에서는 Discord Gateway·모델 요약·제품 태그·운영 배포를 완료로 판정하지 않았다.

0.1.0의 다섯 단계는 [PR #2](https://github.com/parking-place/YoYackBot/pull/2)로 `main`에 통합했다(검증 브랜치 D `d15e6af48d1fd2dec073bed144b7898386ce4402`, merge `e9bb6c13249ddbc18648ddcc7cdc73325c2a0e9f`). 실제 두 Guild 설정 분리·재시작 복원을 확인했고, 권한을 실제로 바꿔 보는 시험은 미실행으로 남겼다. 메시지 캐시·History·Codex 요약·운영 배포는 후속 단계다.

0.2.0의 다섯 단계는 [PR #3](https://github.com/parking-place/YoYackBot/pull/3)로 `main`에 통합했다(검증 브랜치 D `aec621310cbe47c4565dfc5f2956cdc324ed1f78`, merge `330ea2b16a28936b932a80ac08cffcd65af3658f`). 실제 Discord 안내는 사용자가 확인했다. 당시 직접 REST 조회의 403은 기본 `Python-urllib` User-Agent 때문이었으며, 2026-09-28 올바른 봇 User-Agent로 재검사한 두 주시 채널은 HTTP 200이었다. 실제 요약 엔진과 메시지 캐시는 후속 단계다.

0.3.0의 다섯 단계는 [PR #4](https://github.com/parking-place/YoYackBot/pull/4)로 `main`에 통합했다(검증 브랜치 D `d570260ee9af0721fb55c6b843fa195367b8831d`, merge `83f5fd7b5a03d942adf27698dcc1f31d6485ef4a`). 실제 사용자 메시지 1건의 주시 채널 저장과 미주시 차단을 확인했다. 개발 DB를 백업한 뒤 schema 3으로 이전해 설정·메시지를 보존했다. History 조회·모델 요약은 후속 단계다.

0.4.0의 다섯 단계는 [PR #5](https://github.com/parking-place/YoYackBot/pull/5)로 `main`에 통합했다(검증 브랜치 D `cea5832f0d752fb1027073ea744f020b9e248729`, merge `f3a2c51c1ae368cbefdd860344a2992e8d063261`). 개발 Discord 주시 채널 실제 History와 격리 DB 사본에서 시간형 3건 수집·개수형 캐시 무조회 2건을 확인했다. 실제 권한 회수와 Codex 모델 호출은 후속 검증이다.

0.5.0의 다섯 단계는 [PR #6](https://github.com/parking-place/YoYackBot/pull/6)으로 `main`에 통합했다(검증 브랜치 D `92aeb8a39881dae2f8c343d2e23681dd70907c67`, merge `a2a05e63fb518637d228e533e927f6b6f095a90e`). 봇 전용 계정에서 고정된 GPT-6 Luna low 모델로 합성 대화를 실제 요약했고 인증 실패·timeout·비정상 종료 뒤 재시도를 확인했다. 입력·인증 상태는 요청별 격리 폴더에서 정리한다. 요약 품질 평가는 0.6.0, 실제 Discord 명령·게시 연결은 0.7.0의 검증 대상이다.

0.6.0의 다섯 단계는 [PR #7](https://github.com/parking-place/YoYackBot/pull/7)로 `main`에 통합했다(검증 브랜치 D `32ab664ab4c4b6b334bc425865690a904d44bb83`, merge `69ebecba0a86017693e70abf79ff146ff02fc927`). 실제 모델의 21개 합성 사례를 재평가하고, 개발 Discord에서 3개 합성 사용자 메시지를 수집→모델→동일 채널에 게시했다. 별도 합성 장문 2조각 게시도 확인했다. 초기 간접 인용 표현 결함은 보강 후 재검증했고, 사용자 명령 자동 연결·동시성·쿨타임은 0.7.0 대상이다.

0.7.0의 다섯 단계는 [PR #8](https://github.com/parking-place/YoYackBot/pull/8)로 `main`에 통합했다(검증 브랜치 D `79e341f63345c66f7ceb23bb2cf0ee154ed24e24`, merge `2f9a6755fe0ba53e7d5bc3b61093d3ccea8193e4`). 개발 Discord 두 주시 채널의 실제 사용자 명령에서 모델 요약 게시·중복 안내·300초 대기·도움말을 확인했고, 재시작 후 설정과 대기 기록이 보존됐다. 실제 장애 주입과 장시간 운영 검증은 후속 단계에 남겨 두었다.

0.8.0의 다섯 단계는 [PR #9](https://github.com/parking-place/YoYackBot/pull/9)로 `main`에 통합했다(검증 브랜치 D `ab95047b15cd76b6bb611924d130ed2b402cb6c7`, merge `54855985efd41731e01c4140b9421dca8e3b06a4`). 전용 서비스·상태/로그·설정 복원·비밀정보 검사를 검증했다. 8시간 시험은 [사용자 결정](DURATION_WAIVER.md)에 따라 7시간 38분/459표본에서 중단했고 `SKIPPED_BY_USER`로 기록했다. 0.9.0·1.0.0의 24시간 지속 시간 요건도 생략하지만 각 단계의 기능·보안·복구 검사는 계속 필요하다.

0.9.0의 다섯 단계는 [PR #10](https://github.com/parking-place/YoYackBot/pull/10)으로 `main`에 통합했다(검증 브랜치 D `ec9ecaa655df153f9fdbf084cba398b155464a51`, merge `4039777aa32550d443874e97f26f57e86317ad0b`). 명세 §53 46개 항목의 회귀, 실제 Discord 베타 명령·요약, 실제 모델 합성 품질, 격리 장애와 서비스 재시작 복구, 120초/120회 짧은 부하를 검증했다. 24시간 베타 관측은 사용자 요청에 따라 생략했고 실제 권한 거부 조작·장시간 신뢰성은 미검증으로 남겼다. 1.0.0 패키지 버전·롤백·운영 전환은 다음 버전의 대상이다.

## 실행 증거

실행을 시작한 뒤에만 `evidence/<version>-P<n>.md`를 작성한다. raw Discord 대화, 실제 서버 주소, 앱/사용자 식별값, 인증정보와 DB는 증거 파일에 넣지 않는다.
