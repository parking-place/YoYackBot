# 1.0.0d-P1 — 닉네임 출처·표시 계약

상태: **IN_PROGRESS**. 검사: `D1/D2`. 1.0.0c의 원격 완료 후 개발 LXC에서 수행한다.

## 작업

현재 `serialize_conversation`의 내부 `speaker(P1)`와 `display_name`, `summary_prompt.py`, 출력 후처리를 조사한다. 요청 시 선택된 메시지에서 쓸 이름의 기준을 정한다(예: 범위 안에서 가장 최근의 유효한 Discord 표시 이름). 빈 이름, 개명, 같은 이름의 서로 다른 계정, 퇴장 사용자의 결정적 대체 표기를 정의한다. 실제 author ID와 멘션을 출력하지 않는다.

## 통과 기준

- `D1`: 합성 화자·동명이인·개명·빈 이름에서 표시 이름의 선택과 구분이 결정적인지 확인한다.
- `D2`: Unicode·줄바꿈·Markdown·`@everyone`·사용자 멘션·긴 이름을 안전하게 다루는 계약을 확인한다.

결과·동일 구현 SHA를 [검증 목록](TEST_MATRIX.md)에 남긴다. **이 단계만의 C(구현) → E(증거) → D(종료)를 각각 commit·GitHub push하고 원격 포함 관계·필요 CI를 확인해야 DONE**이다. 실패·미실행은 PASS로 세지 않는다. [공통 Git 규칙](../GIT_WORKFLOW.md)을 따른다.

[버전 개요](README.md) · [상태](STATUS.md)
