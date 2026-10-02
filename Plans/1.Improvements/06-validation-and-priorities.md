# 06. 검증 기록과 개선 우선순위

작성일: 2026-10-02. 모든 제품 소스·행 번호는 최초 커밋 `5f85734cf75939888c544356e51d7d44aac30e94`를 기준으로 한다.

## 검증 환경과 안전한 분리

- 원본 저장소: `/root/CodexGround/YoYackBot`.
- 고정 사본: `/tmp/yoyackbot-audit-5f85734`. Git archive로 추적 파일 533개를 추출했고 최초 기록 해시와 모두 일치했다.
- 실행기: Python 3.13.5, 기존 `/tmp/yyvenv`의 `discord.py 2.7.1`, `pytest 9.1.1`, `ruff 0.16.9`. `requirements.lock` 17개 항목 모두 설치 버전과 일치했다. 새 의존성을 설치하지 않았다.
- 합성 검증은 현재 작업 호스트에서 수행했다. 프로젝트의 지정 운영/개발 서버에서 같은 배포 SHA를 실행한 인수 시험이 아니다.
- `env -i`로 환경을 비우고 필요한 PATH·PYTHONPATH만 전달했다. bytecode·pytest cache 생성을 막고 임시 DB·테스트 파일을 저장소 밖에 두었다.
- 실제 Discord·모델·운영 DB·운영 credential은 사용하지 않았다. 일부 기존 subprocess 시험은 합성 자식 프로세스를 실행한다.

## 실행 결과

| 검증 | 결과 | 증거의 범위 |
|---|---|---|
| 기존 pytest 전체 | **1,178 passed in 19.55s** | 기존 합성 회귀 통과; 실제 게시·모델·운영 PASS 아님 |
| Ruff `src tests scripts` | **All checks passed** | 정적 규칙 통과 |
| Python AST 파싱 | 122개 Python 파일 성공 | 문법 파싱; 실행 정확성 보증 아님 |
| `verify_repo.py` | 기존 55단계 및 1.1.3a까지 구조 검사 통과 | 고정 커밋 파일 목록을 사용한 사본 검사; 의미적 모순·새 버전 전체 검사 아님 |
| 공개 Git 이력 scanner | 6,099 객체·탐지 범주 0개 | 로컬 도달 가능 refs 기준; 실제 비밀값 대조 안 함 |
| 추가 결함 합성 재현 | B01~B07, B10~B13의 핵심 동작 11건 확인 | **결함을 재현했다는 결과**, 제품 정상 PASS 아님 |
| 정적 확인만 한 결함 | B08·B09·B14 | 대용량 부하·DB 잠금 UI·실제 역할 삭제는 후속 검증 필요 |

실행한 기본 검사:

```bash
cd /tmp/yoyackbot-audit-5f85734
env -i PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 \
  PYTHONPATH=/tmp/yoyackbot-audit-5f85734/src \
  /tmp/yyvenv/bin/python -m pytest -q -p no:cacheprovider \
  --basetemp=/tmp/yoyackbot-review-pytest-20261002
/tmp/yyvenv/bin/ruff check --no-cache src tests scripts
```

Git archive에는 `.git`이 없다. 문서 검사에는 검증 스크립트의 `git ls-files -z` 호출만 `git ls-tree -rz --name-only 5f85734`의 파일 목록으로 대체했다. 나머지 검사 로직과 문서는 그대로 실행했다. Git index나 ref는 변경하지 않았다. 이력 scanner는 고정 사본의 스크립트를 사용하되 원본 저장소의 로컬 객체를 읽도록 지정했다. 현재 GitHub CI의 실행 결과를 조회한 것은 아니다.

## 추가 재현 관측값

모든 ID·이름·본문은 합성값이다. 다음은 핵심 결과를 축약한 기록이다.

| ID | 구성·입력 | 관측 |
|---|---|---|
| B01 | 실제 `YoYackClient.on_message` + FakeMember/FakeChannel; 관리자는 비공개 채널 열람 가능, 공개 응답의 일반 독자는 불가능 | 공개 `send` 1회, 합성 비공개 채널 이름 포함 |
| B02 | 실제 role store; 삭제 이벤트의 read와 replace 사이에 별도 관리자 쓰기 삽입 | 전체 해제 후에도 오래된 집합의 역할 12가 다시 활성화 |
| B03 | 캐시 ID 101 저장, 복구 History는 빈 목록, 백필 완료 후 현행 collector 사용 | 예약 1, History 0개, ready=true, 요약 선택 IDs=[101] |
| B04 | overlap 종료 경계 뒤 새 메시지 생성, store 재오픈 및 startup recheck | 추가 예약 0, ready=true, 저장 IDs=[] |
| B05 | 실제 `_backfill_loop/_backfill_one`, 접근 불가 채널의 defer가 `BackfillError` 발생 | worker_done=true, 예외 전파, ready_event_still_true=true |
| B06 | `Settings.from_environment` retention=7, cleanup 후 20일 전 기록으로 초기 백필 | cutoff=30일, 정책 밖 메시지 저장 1개 |
| B07 | raw update에 T2/newer 적용 후 T1/older 적용 | 최종 본문 older, 수정 시각 T1 |
| B10 | FakeRunner가 현행 중첩 Markdown `**__P1__**` 반환 | 검사 결과 None, 본문 호출 1회, P1 그대로 반환 |
| B11 | 평가 한 줄만 반환; 기본 요청과 평가 생략 요청 각각 실행 | 기본은 빈 본문+평가 성공, 생략 요청은 빈 text 후 formatter ValueError |
| B12 | 첫 응답 정상 본문, rating-only에 실패 표식 삽입 | rating=retried로 표식 반환; 별도 최종 검사는 tool_report |
| B13 | 상대 실행파일 `codex`, 버전 검사는 대역, 합성 auth dict 사용 | 준비·엔진 구성 성공, runner command는 process 오류, usage 구성은 거부 |

B03의 오프라인 **수정** 누락, B06의 오래된 cached edit 재저장 경로는 위 실행과 별개로 정적 확인했다. B05는 오류 전파를 검증한 것으로 실제 디스크 장애나 5초 DB 잠금 재현은 아니다. B13의 준비 통과는 실제 인증 유효성 증거가 아니다.

재현용 일회성 스크립트는 저장소 밖 `/tmp/yoyackbot-audit-command-repro.py`, `/tmp/yoyackbot-data-audit-repro.py`, `/tmp/yoyackbot-audit-security-repro.py`에 작성했다. 제품 코드·테스트에는 추가하지 않았다. `/tmp` 파일은 영구 산출물이 아니므로 후속 검증은 아래 최소 절차와 [결함별 회귀 기준](02-bug-findings.md)을 기준으로 정식 테스트를 작성해야 한다.

## 주요 재현의 최소 절차

### 관리 역할 변경 경합

```text
store.replace(guild, {11, 12})
old = deletion_worker.get(guild)          # {11, 12}
admin_store.replace(guild, {})           # 관리자 전체 해제
deletion_worker.replace(guild, old - {11})
observe store.get(guild) == {12}          # 기대한 {}와 다름
```

실제 재현에서는 `remove_role()`을 호출하고 그 내부 `get()` 직후에 관리자 변경을 삽입했다. 단순히 별도 구현의 의사코드 결과만 확인한 것이 아니다. 삭제된 역할을 관리자 UI에서 다시 선택하는 불가능한 전제를 두지 않는다.

### 오프라인 삭제 복구

```text
주시 채널의 메시지 101을 캐시하고 backfill ready 상태를 만든다.
접속 공백 재검증을 예약한다.
History 대역이 완전한 빈 구간을 반환하도록 한다.
백필을 끝내고 실제 CacheOnlyCollector로 그 구간을 선택한다.
현재 결과: ready이지만 101이 남는다.
수정 후 기대: 삭제된 기록이 선택되지 않고 미검증 공백도 남지 않는다.
```

### overlap 재시작

```text
history 완료 → overlap으로 전환하고 종료 경계 T1을 저장한다.
T1보다 뒤·재시작 시각 T2보다 앞에 새 메시지를 둔다.
store를 재오픈하고 T2로 schedule_ready_recheck를 호출한다.
기존 overlap을 마친 뒤 새 메시지가 선택되는지 확인한다.
현재 결과: 예약 0, ready, 신규 메시지 누락.
```

### 백필 worker 오류

```text
ready_event를 set하고 pending state 1개를 반환한다.
해당 채널을 찾지 못하게 한다.
retry-state defer에서 BackfillError를 발생시킨다.
실제 _backfill_loop를 실행하고 task 종료 여부를 확인한다.
현재 결과: 예외로 종료되며 ready_event는 유지된다.
```

### 최종 출력 계약

FakeRunner로 출력 문자열만 교체하고 실제 `CodexSummaryEngine.summarize()`를 실행한다. 내부 키가 있는 현행 Markdown, 평가만 있는 응답, 평가 제거 후 빈 본문, 보조 응답의 실패 표식을 각각 입력한다. 모델 API가 아닌 후처리 계약의 실패를 검증한다.

## 개선 순서 제안

이 순서는 감사 권고이며 `Plans`의 단계·일정을 대체하지 않는다.

| 순서 | 대상 | 다음 판단에 필요한 증거 |
|---|---|---|
| 1 | B01·B02 권한·정보 노출 | 다중 수신자 권한 검사, 역할 삭제/저장 교차 순서 회귀 |
| 2 | B03·B04·B06·B07 캐시 신뢰성 | 실제 현행 경로의 삭제·수정·재시작·cutoff 불변조건 |
| 3 | B05·B08·B09 서비스 지속성 | worker 오류 뒤 복구, 제한된 peak RSS, DB 경합 중 이벤트 루프 생존 |
| 4 | B10~B13 출력·설치 계약 | 최종 본문·평가 공통 검증과 준비/실행 수락 기준 일치 |
| 5 | B14·운영 상태·문서 정합성 | 오프라인 설정 정리, 실제 진척 표시, 현재/역사적 계약 구분 |
| 6 | 추가 기능과 기존 1.2.0 구현 검토 | 위 결함 회귀 후 기능별 품질·비용·권한 검증 |

## 미검증 범위와 보존 확인

- 실제 Discord 권한 회수, 서버 UI·모바일 가독성, 새 게시 결과, 실제 모델의 공격 저항성·요약 품질은 이번에 확인하지 않았다.
- 장시간 부하·메모리 누수·운영 복구시간·실제 배포 버전·원격 CI/Release 현황을 측정하지 않았다. 과거 증거와 현재 실행 검증을 혼용하지 않는다.
- dependencies의 최신 CVE 부재나 운영 파일 권한·방화벽 상태를 인증하지 않는다.
- 본 감사가 작성한 저장소 산출물은 `1.Improvements/*.md` 7개뿐이다. 최종 확인에서 기존 추적 파일의 작업 내용 변경은 없었고, 초기 `.claude/` 파일의 내용도 보존됐다.
- 최초 기준 이후 외부 브랜치 전환은 되돌리지 않았다. 문서의 결론은 고정 커밋에 대한 것이며 다른 버전으로 적용할 때는 파일·호출 경로를 다시 확인해야 한다.
