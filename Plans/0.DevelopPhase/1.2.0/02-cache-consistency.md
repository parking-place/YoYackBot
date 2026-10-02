# 1.2.0-P2 — 캐시 정합성·보존

- 상태: **PUSH_PENDING** · 구현 완료 **0** · 검사: `T120-P2-A`~`D` **PASS**
- 대상: **B03·B04·B06·B07** · 환경: 개발 LXC, 시간 제어·합성 History·격리 SQLite
- 근거: [계약 3절](CONTRACT.md), [범위 추적표](SCOPE_MAP.md), [감사 결함](../../1.Improvements/02-bug-findings.md)

## 선행 조건

P1의 종료 D가 원격에 반영됐는지 확인한다. 현재 `build_workflow → CacheOnlyCollector` 경로를 기준으로 시험한다. 감사 B03의 삭제는 재현됐으나 오래된 메시지 편집은 정적 확인이다. B06도 초기 백필만 재현됐으며 cached edit 등 추가 저장 경로는 새 시험이 필요하다. 과거 `TimeRangeCollector` 시험으로 현행 경로를 대체하지 않는다.

## 대상 모듈과 작업

| 대상 | 작업 |
|---|---|
| `backfill.py`, `coverage.py`, `cache_collector.py`, `workflow.py` | 생성 공백 보충과 보관기간 내부의 수정·삭제 대조를 구분해 기록한다. 검증 필요 상태를 실제 collector가 소비하게 하고 정상 완료한 구간만 원자적으로 reconcile한다. |
| `backfill.py`, `discord.py` | history·overlap·ready 모두 새 연결 공백을 누적한다. 작업 phase와 검증 완료 경계를 분리하고 공백이 남으면 summary ready로 전환하지 않는다. |
| `watch_store.py`, `message_store.py`, `config.py`, `discord.py` | 초기 fetch·재개·upsert·raw/cached edit에 같은 현재 retention cutoff를 적용한다. 기간 축소와 장기 중단 뒤 재개의 오래된 cutoff도 갱신한다. |
| `message_store.py`, `discord.py` | raw update에 수정 시각 단조성을 적용한다. 동시각은 멱등 처리하고 timestamp 없는/과거 이벤트로 최신 본문을 덮어쓰지 않는다. live edit·삭제 tombstone이 오래된 History보다 우선한다. |

timestamp가 없거나 잘못된 raw edit는 보관기간 안의 알려진 주시 메시지 본문을 유지하고 재검증을 예약한다. 과거 timestamp는 무시하고 같은 timestamp의 본문은 멱등 유지한다. 재검증은 채널당 기존 상태 하나로 합치고 현재 retention(1~30일) 안에서 기존 100개 이하 페이지와 동시성 제한으로 수행한다. 이벤트별 작업 큐를 추가하지 않는다. cutoff와 같은 생성 시각은 포함하고 이전 시각은 저장하지 않는다. 동일 시각의 쓰기 순서는 선택 테이블 `cache_observation_clock`의 단일 논리 시각과 채널별 관측 인덱스로 보존한다. 메시지 삭제 뒤에도 시각이 역행하지 않으며 원문·식별값을 추가 저장하지 않는다. schema 5와 messages 레이아웃 및 설정 백업을 유지한다. 삭제 의도 보존을 위해 최신 이벤트와 대조 시작점/commit 순서를 증거에 기록한다. F02 진척 필드와 F10 참조는 후속 단계에서 붙이되 현재 캐시 불변조건을 훼손하지 않게 한다.

## 실패 경계

- 부분 페이지·403·429·timeout·DB commit 실패는 조회 완료 또는 원문 부재 증거가 아니다. 이 경우 캐시 삭제·검증 경계 전진·ready 처리를 금지한다.
- 대조 중 받은 live edit/delete를 오래된 페이지로 되돌리지 않는다. 미검증 구간을 빼고 완전한 요약처럼 게시하지 않는다.
- 보관기간 밖 원문을 저장한 뒤 나중 cleanup으로 지우는 방식은 허용하지 않는다. 조회 범위 제한만으로 저장 정책 준수를 판정하지 않는다.
- 새 재접속이 기존 작업에 합쳐지더라도 작업량·동시성은 유한하게 유지한다. 기존 토큰/주시 해제 경합 방어를 유지한다.

## 검증·완료 기준

| 검사 | 실행과 합격 기준 | 결과 |
|---|---|---|
| `T120-P2-A` | 현행 workflow에서 오프라인 삭제와 생성 시각이 단절보다 오래된 메시지의 편집을 복구한다. 완전한 빈 History는 삭제를 반영하고 부분/실패 조회는 삭제하지 않는다. 대조 중 live edit/delete와 오래된 페이지의 교차 순서에서도 최신 내용·tombstone이 유지된다. | PASS |
| `T120-P2-B` | history/overlap/ready 각각에서 중단하고 T1 이후 메시지를 넣은 뒤 T2에 store를 재오픈한다. overlap 중 두 번째 단절, 빈 구간, 경계 직전/동일/직후를 포함한다. 새 공백이 모두 검증되기 전 ready가 되지 않고 대상 메시지가 누락·중복되지 않는다. | PASS |
| `T120-P2-C` | retention 1/7/30일, 기간 축소, 장기 중단 후 재개, cleanup 직후 오래된 cached/raw edit를 검사한다. fetch 범위에 현재 cutoff를 적용하고 응답 도착·저장 때 다시 필터링한다. 새 저장·요약 선택에 현재 cutoff 밖 원문이 0개다. cutoff의 포함/제외 규칙을 고정하고 경계 직전/동일/직후를 검증한다. | PASS |
| `T120-P2-D` | raw T1→T2와 T2→T1, 동시각 중복, timestamp 없음, raw/cached 교차, 삭제 후 편집을 시험한다. 최신 본문과 수정 시각이 역행하지 않고 삭제가 부활하지 않는다. 모호한 이벤트는 정한 재검증 정책으로 처리하며 종료 시 pending 상태가 사실과 일치한다. | PASS |

시간을 전진하지 않은 단순 store 재생성은 B04 재시작 증거가 아니다. 같은 구현 C를 LXC에서 검증하고 `evidence/1.2.0-P2.md`에 조회 구간·합성 이벤트 순서·DB 결과·SHA를 남긴다. **C → 증거 E push·원격 확인 → E CI 성공 → 종료 D push·원격 및 필요한 CI 확인** 뒤 DONE 처리한다. 실패·미실행은 [STATUS](STATUS.md)에 보존하고 [Git 완료 규칙](../GIT_WORKFLOW.md)을 따른다.

[버전 개요](README.md) · [검증 목록](TEST_MATRIX.md) · [다음 P3](03-worker-memory.md)
