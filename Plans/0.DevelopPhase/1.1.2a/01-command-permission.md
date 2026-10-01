# 1.1.2a-P1 — Discord 명령어 권한을 따르는 판정

- 상태: **PLANNED** · 검사: `T112a-P1-A/B` · 환경: 개발 LXC, 합성 상호작용(Discord 연결 없음)

## 선행 조건·작업

`v1.1.2` 출시와 `main` 통합을 확인한다. [계약](CONTRACT.md)대로 `channel_config`를 고친다: `/채널 설정` 실행 시 `can_manage` 검사를 없애고 서버 안 상호작용인지만 확인한다. 설정 화면의 `interaction_check`는 같은 서버·화면을 연 본인인지만 확인한다. 명령어 등록의 `guild_only`와 `default_permissions(manage_channels=True)`는 유지한다. 동시 수정 안내를 “다른 사람이”로 바꾸고, 저장 시 `watched_channels_saved` 지표(서버 ID·채널 수·변경 방식, 사용자 ID 없음)를 남긴다. `can_manage`가 더 쓰이지 않으면 지운다.

## 검증·완료 기준

- `T112a-P1-A`: 합성 상호작용에서 관리자·채널 관리 권한자·**권한 플래그가 없는 사용자(연동 설정으로 허용된 경우를 흉내)** 모두 설정 화면을 열고 추가·제거·전체 해제·저장할 수 있다. DM(서버 없음)은 거절된다. 등록된 명령어의 기본 권한이 `manage_channels`이고 `guild_only`다.
- `T112a-P1-B`: 화면을 연 사람이 아닌 사용자, 다른 서버의 상호작용은 버튼·선택에서 거절된다. 봇이 접근할 수 없는 채널·텍스트가 아닌 채널 저장 거절, 동시 수정 감지, 제한 시간 만료가 그대로 동작한다. 지표 로그에 사용자 ID·채널 이름이 없다. 전체 회귀 통과.

같은 SHA의 결과를 [증거 양식](../EVIDENCE_TEMPLATE.md)에 남기고 구현 C → 증거 E → (E CI 성공 확인) → 종료 D를 각각 commit·GitHub push·원격 확인한다. [공통 Git 규칙](../GIT_WORKFLOW.md)을 따른다.

[버전 개요](README.md) · [검증 목록](TEST_MATRIX.md) · [다음 단계](02-help-docs.md)
