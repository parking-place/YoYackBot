# 02. 버그 탐색 결과

기준: `5f85734cf75939888c544356e51d7d44aac30e94`. 파일·행은 이 커밋 기준이다. 아래 재현은 임시 DB·가짜 Discord/모델 응답으로 확인한 것이며 운영 장애·실제 모델의 발생 빈도를 입증하지 않는다. 우선순위 정의는 [README](README.md), 관측값은 [검증 기록](06-validation-and-priorities.md)을 따른다.

## B01 · P1 · 비공개 채널 이름을 공개 응답으로 노출

**상태: 실제 명령 처리 경로의 합성 재현.**

- 근거: [channel_list.py:26–40](https://github.com/parking-place/YoYackBot/blob/5f85734cf75939888c544356e51d7d44aac30e94/src/yoyackbot/channel_list.py#L26), `discord.py:518–528,618–628`.
- 원인: 목록을 요청자의 `view_channel`로 걸러낸 뒤 요청 채널의 일반 `send()`로 게시한다. 요청자 권한과 공개 응답 수신자의 권한이 다르다.
- 조건: 공개 채널과 비공개 채널을 모두 주시한다. 양쪽을 볼 수 있는 관리자가 공개 채널에서 `!!요약좀 채널`을 실행한다.
- 관측: 비공개 채널을 볼 수 없는 일반 사용자도 읽는 공개 응답에 합성 비공개 이름이 포함됐다.
- 영향: 비공개 채널 이름·존재 노출. 비공개 대화 본문까지 유출된다는 주장은 하지 않는다.
- 계약: `Plans/0.DevelopPhase/1.0.2b/COMMAND_CONTRACT.md:29`는 권한 없는 사람에게 비공개 이름·존재를 노출하지 않는 목적을 명시한다.

**개선 방향:** 개인 권한으로 생성한 목록은 ephemeral 상호작용 등 개인 응답으로 전달한다. 텍스트 명령의 공개 출력을 유지하려면 공개 가능한 정보의 기준을 별도로 정의해야 한다.

**회귀 기준:** 요청자 A는 비공개 채널을 보고 수신자 B는 못 보는 사례, 둘 다 못 보는 사례, 서버 분리, 응답 분할을 검사한다. `tests/test_channel_list.py`의 요청자 필터 검사만으로는 부족하다.

## B02 · P1 · 역할 삭제 경합으로 회수한 관리 권한이 복구

**상태: 실제 SQLite 저장소의 결정적 경합 재현.**

- 근거: [manager_roles.py:133–137](https://github.com/parking-place/YoYackBot/blob/5f85734cf75939888c544356e51d7d44aac30e94/src/yoyackbot/manager_roles.py#L133), `discord.py:433–435`.
- 원인: `remove_role()`의 `get → replace`는 별도 트랜잭션이며 읽은 revision을 쓰기 때 확인하지 않는다.
- 재현 순서: 관리 역할 `{11,12}`를 삭제 이벤트가 읽는다 → 관리자가 전체 해제로 빈 집합을 저장 → 이벤트가 역할 11을 뺀 오래된 집합 `{12}` 저장. 빈 집합은 삭제된 역할이 없어 UI의 유효성 검사도 통과한다.
- 관측: 최종 역할은 기대한 빈 집합 대신 `{12}`였다. 실제 스레드 타이밍 대신 읽기 직후 관리 변경을 삽입해 동일한 순서를 만들었다.
- 영향: 회수한 권한이 되살아나거나 새로 추가한 역할이 사라진다. 역할 설정 화면 자체의 CAS는 이 별도 이벤트 경로를 보호하지 않는다.

**개선 방향:** 단일 `BEGIN IMMEDIATE`에서 대상 역할만 삭제하고 revision을 증가시키거나, revision 확인과 재시도를 적용한다. 오래된 전체 집합으로 덮어쓰지 않는다.

**회귀 기준:** 역할 삭제와 관리자 추가·해제·전체 초기화의 교차 순서를 검증한다. `tests/test_manager_roles.py`의 순차 삭제·version 검사는 유지하되 경합을 추가한다.

## B03 · P1 · 오프라인 삭제·수정이 현행 요약에 남음

**상태: 삭제 잔존 합성 재현, 오래된 메시지 편집 누락은 정적 확인.**

- 근거: [backfill.py:273–299](https://github.com/parking-place/YoYackBot/blob/5f85734cf75939888c544356e51d7d44aac30e94/src/yoyackbot/backfill.py#L273), `backfill.py:327–330`, `discord.py:279–290`, `cache_collector.py:59–99`, `workflow.py:330–345`.
- 원인 1: 재수집 페이지는 존재하는 메시지를 upsert하지만 History에서 사라진 캐시 행을 제거하지 않는다.
- 원인 2: 보충 범위는 메시지 **생성 시각** 기준의 단절 구간이다. 그보다 오래전에 작성한 메시지를 단절 중 수정하면 그 행은 재조회되지 않는다.
- 원인 3: 전체 보관기간에 `coverage_recheck` 표시를 남기는 코드가 있지만 현행 `CacheOnlyCollector`는 이를 소비하지 않는다. 옛 `TimeRangeCollector → commit_history_complete()`의 reconcile 방어는 현행 경로에 연결되지 않는다.
- 관측: 재검증이 예약되고 빈 History를 모두 처리해 ready가 됐는데도 삭제된 합성 캐시 ID 101이 요약 대상으로 선택됐다.
- 영향: 삭제·수정한 원문이 다시 모델 입력과 요약에 들어갈 수 있다. 데이터 정확성뿐 아니라 삭제 의도와 개인정보 처리에도 영향을 준다.

**개선 방향:** 생성 공백 보충과 기존 행의 수정·삭제 대조를 구분한다. 정상 완료한 범위만 원자적으로 reconcile하고, live 편집과 tombstone의 순서를 보존한다. 비용 때문에 전체 재검증을 늦춘다면 해당 상태와 사용자에게 보장하는 최신성 범위를 명시해야 한다.

**회귀 기준:** 현행 `build_workflow` 경로로 오프라인 삭제·오래된 메시지 수정·빈 페이지·조회 실패·재검증 중 live 편집을 검증한다. `tests/test_range_collection.py:104–119`의 옛 경로 검사는 이 결함의 방어 증거가 아니다.

## B04 · P1 · overlap 도중 재시작하면 공백이 남아도 ready

**상태: store 재오픈과 시간 경계를 포함한 합성 재현.**

- 근거: [backfill.py:282–297](https://github.com/parking-place/YoYackBot/blob/5f85734cf75939888c544356e51d7d44aac30e94/src/yoyackbot/backfill.py#L282), `backfill.py:352–357,439–448`, `discord.py:176–183`.
- 원인: 재접속 재검증은 `phase='ready'`만 선택한다. 이미 overlap인 작업은 과거 `finished_us`를 유지한 채 끝나고, 그 이후 단절 구간을 추가하지 않는다.
- 재현 순서: overlap 종료 경계 T1 저장 → 완료 전에 중단 → T1 이후 새 메시지 생성 → T2 재시작 → 기존 overlap 완료.
- 관측: 추가 재검증 예약은 0이고 T1 이후 메시지가 저장되지 않았지만 ready가 됐다.
- 영향: 누락된 범위를 완전한 캐시로 간주하여 요약한다. 단순히 “준비가 느리다”는 문제가 아니다.

**개선 방향:** 진행 중 백필에도 새 연결 공백을 누적하고, 기존 작업 완료 후 추가 공백을 해소한 뒤 ready로 전환한다. 작업 phase와 검증 완료 경계를 별도 불변조건으로 다룬다.

**회귀 기준:** history·overlap·ready 각각에서 중단·재시작, overlap 중 두 번째 단절, 빈 구간, 경계 직전/직후 메시지를 넣는다. 시간 고정 상태에서 store 객체만 다시 만드는 시험으로 대체하지 않는다.

## B05 · P1 · 재시도 상태 저장 실패가 전체 백필 worker 종료

**상태: 실제 worker 제어 흐름에 저장 실패를 주입해 재현.**

- 근거: [discord.py:350–364](https://github.com/parking-place/YoYackBot/blob/5f85734cf75939888c544356e51d7d44aac30e94/src/yoyackbot/discord.py#L350), `discord.py:379–382,397–410`.
- 원인: `gather()` 밖으로 빠지는 예외를 worker가 처리하지 않는다. 접근 불가 채널의 `defer()`는 try 밖이고, 오류 처리 안의 `block()/defer()` 실패도 다시 잡지 않는다.
- 조건: DB 쓰기 잠금·쓰기 불가 등으로 재시도 메타데이터 기록마저 실패한다.
- 관측: 합성 `defer()`가 `BackfillError`를 내자 `_backfill_loop` task는 종료됐고 `ready_event`는 여전히 true였다. 실제 디스크 장애나 DB 장기 잠금을 주입한 시험은 아니다.
- 영향: 문제가 한 채널에서 발생해도 전체 백필 진행이 멈출 수 있다. 이후 DB가 복구돼도 자동 worker 재생성 경로가 없으며 Gateway 연결은 정상으로 보일 수 있다.

**개선 방향:** 페이지 처리·재시도 기록·worker 수명을 각각 보호한다. 모든 예외를 무시하지 말고 고정 오류 분류·backoff·생존 감지를 적용하며, 취소는 정상 종료로 전달한다.

**회귀 기준:** 페이지 실패 후 defer 실패, 영구 차단 기록 실패, DB 복구 후 재개, 다른 채널 계속 처리, 종료 시 취소 전파를 검사한다.

## B06 · P2 · 설정한 보관기간 밖의 원문을 백필이 저장

**상태: 실제 retention=7 설정과 임시 SQLite로 재현.**

- 근거: [watch_store.py:18–28](https://github.com/parking-place/YoYackBot/blob/5f85734cf75939888c544356e51d7d44aac30e94/src/yoyackbot/watch_store.py#L18), `config.py:98–100`, `backfill.py:276,327–330,439–448`.
- 원인: 설정은 1~30일을 허용하지만 초기·공백 백필은 30일 기준을 사용한다. 저장 시점의 현재 retention cutoff를 적용하지 않는다.
- 관측: 7일 설정으로 cleanup을 실행한 뒤 초기 백필을 진행하면 20일 전 메시지가 DB에 저장됐다. 초기 cutoff는 30일이었다.
- 추가 경로: 오래 중단된 백필의 고정 cutoff, 오래된 메시지의 cached edit 저장(`discord.py:440–448,642–665`)도 현재 보존 경계를 넘길 가능성이 있다. 추가 경로는 정적 확인이다.
- 영향: 요약 조회가 7일로 제한되더라도 정책 밖 원문을 디스크에 수집·저장한다. 다음 cleanup에서 삭제될 수 있다는 사실이 이 불일치를 해소하지 않는다.

**개선 방향:** 수집과 모든 저장 경로에서 동일한 retention·현재 cutoff를 적용한다. 보존 기간을 줄일 때 진행 중 작업의 cutoff도 갱신한다.

**회귀 기준:** 1·7·30일, 설정 변경, 장기 중단 후 재개, 정리 직후 오래된 메시지 편집, 경계 시각을 검증한다.

## B07 · P2 · 늦은 raw 편집이 최신 본문을 덮어씀

**상태: 저장소 메서드 합성 재현.**

- 근거: [message_store.py:178–194](https://github.com/parking-place/YoYackBot/blob/5f85734cf75939888c544356e51d7d44aac30e94/src/yoyackbot/message_store.py#L178), `discord.py:450–472`.
- 원인: 일반 upsert에는 수정 시각 비교가 있지만 raw `update_content()`는 ID만 조건으로 덮어쓴다. `to_thread()`로 수행한 작업이 같은 순서로 DB 잠금을 얻는다는 보장은 없다.
- 관측: T2의 새 본문을 적용한 뒤 T1의 오래된 본문을 적용하면 최종 본문과 수정 시각이 T1로 돌아갔다.
- 영향: 빠른 연속 편집이나 지연된 이벤트 처리에서 과거 발언이 요약에 사용될 수 있다. 실제 Gateway 역전 빈도는 측정하지 않았다.

**개선 방향:** raw update에도 수정 시각의 단조 증가 조건을 적용하고, timestamp가 없는 변경·동일 시각·삭제 tombstone과의 우선순위를 정한다.

**회귀 기준:** T1→T2, T2→T1, 동일 시각, raw/cached edit 교차, 삭제 후 편집을 검증한다.

## B08 · P2 · 입력 한도가 조회 메모리를 보호하지 못함

**상태: 정적 확인. 실제 대용량 부하·OOM 미실행.**

- 근거: [message_store.py:264–282](https://github.com/parking-place/YoYackBot/blob/5f85734cf75939888c544356e51d7d44aac30e94/src/yoyackbot/message_store.py#L264), `cache_collector.py:72–77,92–93`.
- 원인: 기간 전체 `fetchall()`과 객체·tuple 생성 후에야 입력 바이트 합계를 검사한다. 모델 입력 상한은 앞단 메모리 상한이 아니다.
- 조건·영향: 대화량이 큰 채널의 장기간 요청에서 높은 RSS·지연, 심하면 프로세스 종료 위험이 있다. 실제 임계값은 알 수 없다.

**개선 방향:** DB cursor를 제한된 batch로 읽고 누적 바이트·행 수를 확인해 초과 즉시 종료한다. 일부만 잘라 완전한 요약으로 보내지는 않는다.

**회귀 기준:** 입력 한도보다 훨씬 큰 합성 DB에서 읽은 행 수·peak RSS가 전체 DB 크기에 선형으로 늘지 않는지 확인한다. 단순히 최종 `ConversationTooLarge`만 확인하면 부족하다.

## B09 · P2 · 설정 UI의 동기 DB 호출로 전체 이벤트 루프 지연

**상태: 정적 확인. DB 잠금 부하·실제 Discord 응답 만료 미재현.**

- 근거: [channel_config.py:248–251](https://github.com/parking-place/YoYackBot/blob/5f85734cf75939888c544356e51d7d44aac30e94/src/yoyackbot/channel_config.py#L248), `channel_config.py:293`, `role_config.py:101–104,143`, `watch_store.py:178`, `manager_roles.py:72`.
- 원인: async callback과 화면 생성에서 동기 SQLite 작업을 직접 호출한다. writer 잠금 timeout은 5초다.
- 영향: 다른 채널 이벤트·heartbeat까지 같이 멈춘다. Discord는 초기 응답을 3초 안에 요구하므로 저장 후 화면 응답이 실패하는 상황도 가능하다. [Discord 공식 문서](https://docs.discord.com/developers/interactions/receiving-and-responding#interaction-callback).

**개선 방향:** 먼저 defer한 뒤 DB 접근을 thread 등으로 분리한다. 기존 소유자·권한·revision 재검사는 유지한다.

**회귀 기준:** 임시 DB의 writer lock을 다른 연결에서 점유하고 실제 callback을 실행한다. 같은 이벤트 루프의 tick과 defer 시점, 최종 저장 결과가 일치하는지 검사한다.

## B10 · P2 · 현행 중첩 마크다운의 내부 화자 키 검출 누락

**상태: 검사기와 FakeRunner 엔진 합성 재현.**

- 근거: [output_quality.py:132–134](https://github.com/parking-place/YoYackBot/blob/5f85734cf75939888c544356e51d7d44aac30e94/src/yoyackbot/output_quality.py#L132), `summary_prompt.py:35–45`, `codex_engine.py:77–83`.
- 원인: 프롬프트는 `- **__화자 이름__**:`을 요구하지만 내부 키 검사 정규식은 굵게·밑줄 중 한 겹만 처리한다.
- 관측: `- **__P1__**: 금요일 배포를 제안했소.`를 `inspect_output()`이 거절하지 않았다. 엔진은 재생성 없이 P1을 반환했다.
- 영향: 사용자에게 실제 닉네임 대신 내부 키가 보인다. 일반 코드·인용에 등장한 P1까지 막자는 주장은 아니다.

**개선 방향:** 화자 위치의 마크다운을 정규화한 뒤 키를 검사한다.

**회귀 기준:** `**P1**`, `__P1__`, `**__P1__**`, `__**P1**__`, 조사형, 코드·인용 예외를 묶어 검사한다.

## B11 · P2 · 평가만 있는 응답을 정상 요약으로 처리

**상태: 엔진·formatter 합성 재현.**

- 근거: [codex_engine.py:92–115](https://github.com/parking-place/YoYackBot/blob/5f85734cf75939888c544356e51d7d44aac30e94/src/yoyackbot/codex_engine.py#L92), `summary_format.py:119–121`.
- 원인: 전체 응답을 검사한 뒤 평가를 분리하지만 남은 본문이 비어 있는지 재검사하지 않는다.
- 입력: `**요약창섭의 떡밥 한줄 평가** : 요란하오.`만 반환하는 모델 대역.
- 관측: 기본 요청은 본문이 없어도 평가만 성공 결과로 반환했다. `평가 빼줘` 요청은 빈 text가 되어 formatter에서 뒤늦게 `ValueError`가 발생했다.
- 영향: 요약 없는 평가가 게시되거나 모델 결과가 게시 단계 오류로 처리된다.

**개선 방향:** 평가·고지 등 부속 내용을 제거한 실제 본문 존재를 검증하고 `OUTPUT_INVALID` 또는 한정 재시도로 처리한다.

**회귀 기준:** 평가 단독, 평가 생략, 고지 단독, 정상 본문, 평가 생성 실패를 검사하고 본문 없는 성공·쿨타임을 허용하지 않는다.

## B12 · P2 · 평가 재생성에서 공통 출력 검증 우회

**상태: 엔진 합성 재현.**

- 근거: [codex_engine.py:126–140](https://github.com/parking-place/YoYackBot/blob/5f85734cf75939888c544356e51d7d44aac30e94/src/yoyackbot/codex_engine.py#L126), `codex_engine.py:115–123`, `output_quality.py:163–166`.
- 원인: `_rating_only()`는 평가 유무·혐오어만 확인한다. 본문과 다시 합친 최종 문자열에도 공통 검사기가 적용되지 않는다.
- 관측: 첫 응답은 정상 본문, 두 번째는 평가에 `YOYACK_INPUT_UNAVAILABLE`을 넣었다. 엔진은 이를 그대로 반환했고, 반환값에 별도로 공통 검사를 적용하면 `tool_report`였다.
- 영향: 최초 응답이면 거절할 실패 표식·도구 설명이 평가 경로로 통과한다. 실제 토큰 유출이나 OS 샌드박스 탈출을 입증한 것은 아니다.

**개선 방향:** 보조 생성에도 공통 검사를 적용하고 최종 합성 결과를 검증한다. 평가만 불량하면 유효한 본문은 살리고 평가를 생략할 수 있다.

**회귀 기준:** 정상 본문 뒤 실패 표식, 도구 경로, 잘못된 화자 키·평가 형식을 반환하게 하고 결과 계약이 일관되는지 검사한다.

## B13 · P2 · 기본 Codex 경로가 실제 실행에서는 거부됨

**상태: 버전 검사 대역과 합성 인증 파일로 준비·실행 조건 불일치 재현.**

- 근거: [config.py:134](https://github.com/parking-place/YoYackBot/blob/5f85734cf75939888c544356e51d7d44aac30e94/src/yoyackbot/config.py#L134), `.env.example:6`, `codex_runner.py:126–131`, `usage.py:223–224`, `readiness.py:30–34`.
- 원인: 설정 기본값과 예시는 `codex`지만 runner·사용량 실행은 절대 경로만 허용한다. 모델 준비 검사는 버전·인증 파일 상태만 확인한다.
- 조건: 예시대로 설정하고 PATH에 올바른 CLI가 있는 새 설치.
- 관측: 버전 조회를 대역으로 통과시키면 `check_ready()`와 엔진 구성이 성공하지만, runner command 생성은 `process`, 사용량 구성은 설정 오류로 거부했다. 실제 CLI를 실행하거나 실제 인증 성공을 확인한 것은 아니다.
- 영향: 시작·준비 상태가 정상이면서 요약·사용량이 실패하는 설치 경험을 만든다. 운영 환경이 절대 경로를 쓰고 있다면 그 환경은 영향 대상이 아니다.

**개선 방향:** 시작 시 검증된 절대 경로로 해석하거나 설정 단계에서 명확히 거부하고 예시를 일치시킨다.

**회귀 기준:** PATH 이름, 절대 경로, 누락·비실행 파일에 대해 설정·준비·runner의 수락 기준을 일치시킨다.

## B14 · P2 · 오프라인 삭제 역할이 남아 설정 저장을 막음

**상태: 정적 확인. 실제 Discord 역할 삭제 미실행.**

- 근거: [role_config.py:98–104](https://github.com/parking-place/YoYackBot/blob/5f85734cf75939888c544356e51d7d44aac30e94/src/yoyackbot/role_config.py#L98), `role_config.py:143–144`, `discord.py:198–220,304–342,433–435`.
- 원인: 저장된 ID를 그대로 draft로 만들고 하나라도 현재 Guild에서 유효하지 않으면 전체 저장을 거부한다. 실시간 삭제 이벤트 처리는 있으나 오프라인 삭제를 재접속 때 대조하지 않는다.
- 조건: 봇이 받지 못한 동안 관리 역할 삭제, 또는 삭제 cleanup 실패 후 다시 설정 화면을 연다.
- 영향: 없는 역할을 선택 UI에서 제거하기 어려워 새 역할 추가·저장이 거부된다. **전체 해제 후 재설정 또는 운영 CLI로 복구 가능**하므로 영구 관리 잠금은 아니다.
- 계약: `Plans/0.DevelopPhase/1.1.3/CONTRACT.md:38`의 다음 저장 때 삭제 역할 정리 목표와 어긋난다.

**개선 방향:** Guild에서 사라진 ID를 표시하고 안전하게 제거한 draft를 제공하거나, 저장 시 정리 사실을 알려 일관되게 반영한다. B02와 함께 원자성·revision을 유지한다.

**회귀 기준:** 오프라인 삭제, cleanup 실패, 일부 역할만 유효, 전체 해제, 권한 회수와 저장 경합을 검증한다.
