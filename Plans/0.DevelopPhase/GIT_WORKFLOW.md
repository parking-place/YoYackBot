# 단계 완료와 GitHub 업로드 규칙

**모든 단계는 작업 + 검증 + 증거 기록 + commit + GitHub push + 원격 반영 확인까지 끝나야 완료다.** 로컬 저장, 로컬 commit, PR 초안, push 명령 시도만으로 완료 처리하지 않는다.

대상 저장소: [parking-place/YoYackBot](https://github.com/parking-place/YoYackBot). 계획 최초 게시 대상은 비어 있던 저장소의 `main`이다. 이 게시 작업은 55개 개발 단계를 수행한 것이 아니다.

## 개발 브랜치와 커밋

- 후속 개발은 최신 원격 기준을 확인하고 버전별 `develop/0.1.0` 형태의 브랜치를 사용한다. 각 단계의 실제 대상 브랜치를 증거에 적는다.
- 각 단계마다 독립된 작업 커밋을 만들고 즉시 원격에 올린다. 5단계를 전부 마친 뒤 한 번에 올리는 방식은 사용하지 않는다.
- 커밋 예: `feat(0.1.0-p2): add watched channel selector`, `test(0.4.0-p2): verify cache gap recovery`, `docs(0.1.0-p2): record verification evidence`.
- 버전의 마지막 단계에서 버전 회귀 검증·검토·필요 CI를 완료하고 기본 브랜치 통합 여부를 기록한다. 브랜치 업로드와 기본 브랜치 병합은 서로 다른 항목이다.
- 보호 규칙이 있으면 PR로 통합한다. 필요한 검사·검토를 우회하지 않는다. 단계 commit을 찾을 수 있도록 보존하고, squash를 사용하면 원래 SHA와 통합 SHA의 대응표를 남긴다.
- 제품 태그는 해당 버전 게이트를 통과한 코드에만 붙인다. 계획 게시에 `v1.0.0` 등의 제품 태그를 붙이지 않는다.

## 단계마다 수행할 절차

1. [STATUS](STATUS.md)에서 선행 단계의 DONE과 원격 증거를 확인하고 현재 단계를 IN_PROGRESS로 변경한다.
2. 계획의 산출물을 구현하고 관련 테스트를 수행한다. 실패·미실행은 PASS로 바꾸지 않는다. 문서 전용 단계는 문서 검사 범위를 명시한다.
3. `.private`, 실제 `.env`, 인증 파일, DB, 메시지 원문, 임시 파일이 포함되지 않았는지 확인하고 대상 파일만 명시적으로 stage한다.
4. 단계 구현 커밋 **C**를 만든다. 같은 C를 검증 환경에서 실행해 결과를 확보한다. 수정했다면 새 C를 만들고 영향받는 검증을 다시 한다.
5. [증거 양식](EVIDENCE_TEMPLATE.md)을 사용해 `evidence/<version>-P<n>.md`에 C의 전체 SHA, 환경, 검사 결과, 제한 사항을 기록한다. STATUS는 PUSH_PENDING으로 두고 증거 커밋 **E**를 만든다.
6. C와 E가 포함된 브랜치를 GitHub로 push한다. 원격을 조회해 E가 실제로 존재하고 C가 그 이력에 포함되는지 확인한다. 필요한 CI가 있으면 E의 결과도 확인한다.
7. 그때만 STATUS를 DONE으로 바꾸고 원격에서 이미 확인한 **E의 SHA와 commit URL**을 기록하는 문서 커밋 **D**를 만든 뒤 다시 push한다.
8. 마지막 D의 원격 반영과 필요한 CI를 확인한 시점에 단계 완료를 보고한다. D가 원격에 없으면 로컬 STATUS에 DONE이 적혀 있어도 단계는 PUSH_PENDING이다.

검증 코드가 바뀌지 않은 문서 커밋 때문에 제품 테스트 전체를 반복하지 않는다. 단, 설정·프롬프트·실행 코드·잠금 파일이 바뀌면 제품 동작 변경으로 보고 다시 검증한다.

## 순환하지 않는 증거

C는 구현, E는 C 검증 증거, D는 이미 원격에 올라간 E의 확인 기록이다. D 파일 안에 D 자신의 SHA를 적으려 하지 않는다. 마지막 push는 GitHub commit/branch 이력과 원격 조회로 확인한다. 다음 단계는 D가 원격에 포함되는 것을 확인한 뒤 시작한다.

원격 확인 예시(실제 브랜치를 사용):

```bash
git status --short
git diff --cached --check
git push -u origin develop/0.1.0
git fetch origin develop/0.1.0
git rev-parse HEAD
git rev-parse origin/develop/0.1.0
git ls-remote origin refs/heads/develop/0.1.0
```

동시 작업으로 원격 HEAD가 앞서간 경우 단순 SHA 일치 대신 해당 커밋이 원격 이력에 포함되는지 확인한다. 강제 push로 원격 작업을 덮어쓰지 않는다.

## 실패 및 복구

- push 실패: C/E/D를 보존하고 PUSH_PENDING을 유지한다. 원인을 해결한 뒤 같은 커밋부터 재시도한다.
- 테스트 실패: IN_PROGRESS 또는 BLOCKED로 원인과 재현 방법을 남긴다. 다음 의존 단계의 완료 판정을 금지한다.
- DONE 후 결함: 영향 단계와 버전을 다시 열고 수정·검증·push를 새 커밋으로 남긴다.
- 취소·장애·롤백도 결과와 대상 SHA를 기록한다. 운영 데이터 삭제, 공개 범위 변경, 강제 push를 복구 절차로 사용하지 않는다.
