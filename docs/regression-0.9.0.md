# 0.9.0-P1 명세 §53 전체 회귀 추적표

§53의 46개 항목을 원문 순서로 모두 매핑한다. 테스트 파일은 이번 후보 SHA에서 전체 회귀를 수행할 대상이고, 기존 증거는 당시 SHA의 실환경 또는 격리 실행 기록이다. **기존 SHA의 PASS를 새 SHA의 PASS로 옮기지 않는다.** 이번 SHA의 실제 검사 결과와 실행 환경은 [단계 증거](../Plans/0.DevelopPhase/evidence/0.9.0-P1.md)에 별도로 확정한다. 0.9.0-P2~P4가 맡는 신규 실환경·장애·보존 시험은 해당 단계의 증거에서 확인한다.

| 번호 | 영역 | §53 판정 항목 | 이번 SHA 회귀 검사 | 이전 단계 증거 |
|---:|---|---|---|---|
| 01 | 채널 설정 | `/채널 설정`으로 서버별 주시 채널 선택 가능 | [`test_channel_config.py`](../tests/test_channel_config.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.1.0-P5.md) |
| 02 | 채널 설정 | 선택된 채널만 실시간 SQLite 캐시 | [`test_gateway.py`](../tests/test_gateway.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.1.0-P5.md) |
| 03 | 채널 설정 | 설정은 봇 재시작 후에도 유지 | [`test_watch_store.py`](../tests/test_watch_store.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.1.0-P5.md) |
| 04 | 채널 설정 | 주시하지 않는 채널에서는 `!!요약좀` 실행 차단 | [`test_watch_gate.py`](../tests/test_watch_gate.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.1.0-P5.md) |
| 05 | 채널 설정 | 주시 해제 후 새 메시지는 캐시하지 않음 | [`test_gateway.py`](../tests/test_gateway.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.1.0-P5.md) |
| 06 | 채널 설정 | 새로 주시한 채널에서 과거 범위가 필요하면 Discord History로 보충 가능 | [`test_range_collection.py`](../tests/test_range_collection.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.1.0-P5.md) |
| 07 | 명령 | `!!요약좀` 입력 시 최근 1시간 수집 | [`test_parser.py`](../tests/test_parser.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.7.0-P5.md) |
| 08 | 명령 | `!!요약좀 3` 입력 시 최근 3시간 수집 | [`test_parser.py`](../tests/test_parser.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.7.0-P5.md) |
| 09 | 명령 | `!!요약좀 2시간` 정상 처리 | [`test_parser.py`](../tests/test_parser.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.7.0-P5.md) |
| 10 | 명령 | `!!요약좀 30분` 정상 처리 | [`test_parser.py`](../tests/test_parser.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.7.0-P5.md) |
| 11 | 명령 | `!!요약좀 100개` 정상 처리 | [`test_count_collection.py`](../tests/test_count_collection.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.7.0-P5.md) |
| 12 | 명령 | `!!요약좀 오늘` 한국시간 00:00부터 수집 | [`test_range_request.py`](../tests/test_range_request.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.7.0-P5.md) |
| 13 | 명령 | `!!요약좀 2일` 정상 처리 | [`test_parser.py`](../tests/test_parser.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.7.0-P5.md) |
| 14 | 명령 | `!!요약좀 1주` 정상 처리 | [`test_long_range.py`](../tests/test_long_range.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.7.0-P5.md) |
| 15 | 명령 | `!!요약좀 도움` 정상 출력 | [`test_parser.py`](../tests/test_parser.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.7.0-P5.md) |
| 16 | 로그 필터 | 요약봇 메시지 제외 | [`test_gateway.py`](../tests/test_gateway.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.4.0-P5.md) |
| 17 | 로그 필터 | 다른 봇 메시지 제외 | [`test_gateway.py`](../tests/test_gateway.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.4.0-P5.md) |
| 18 | 로그 필터 | 자동화 메시지 제외 권장 | [`test_history.py`](../tests/test_history.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.4.0-P5.md) |
| 19 | 로그 필터 | 현재 요약 명령 메시지 제외 | [`test_codex_engine.py`](../tests/test_codex_engine.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.4.0-P5.md) |
| 20 | 로그 필터 | 일반 사용자 메시지만 Codex 입력에 포함 | [`test_history.py`](../tests/test_history.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.4.0-P5.md) |
| 21 | SQLite 캐시 | 일반 사용자 메시지를 SQLite에 캐시 | [`test_gateway.py`](../tests/test_gateway.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.4.0-P5.md) |
| 22 | SQLite 캐시 | 메시지 캐시 최대 7일 보존 | [`test_gateway.py`](../tests/test_gateway.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.4.0-P5.md) |
| 23 | SQLite 캐시 | 7일이 지난 메시지 자동 삭제 | [`test_gateway.py`](../tests/test_gateway.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.4.0-P5.md) |
| 24 | SQLite 캐시 | Discord Message ID 기반 중복 방지 | [`test_message_store.py`](../tests/test_message_store.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.4.0-P5.md) |
| 25 | SQLite 캐시 | 동일 또는 겹치는 요약 범위에서 기존 캐시 재사용 | [`test_range_collection.py`](../tests/test_range_collection.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.4.0-P5.md) |
| 26 | SQLite 캐시 | 캐시에 없는 시간 구간만 Discord History에서 추가 조회 | [`test_range_collection.py`](../tests/test_range_collection.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.4.0-P5.md) |
| 27 | SQLite 캐시 | 채널별 수집 완료 범위 메타데이터 관리 권장 | [`test_coverage.py`](../tests/test_coverage.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.4.0-P5.md) |
| 28 | SQLite 캐시 | `X개` 요청 시 DB에 부족한 개수만 추가 수집 | [`test_count_collection.py`](../tests/test_count_collection.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.4.0-P5.md) |
| 29 | SQLite 캐시 | DB 장애 시 가능한 경우 Discord History 직접 조회로 fallback | [`test_collection.py`](../tests/test_collection.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.4.0-P5.md) |
| 30 | 요약 | SQLite에서 요청 범위 메시지 조회 | [`test_collection.py`](../tests/test_collection.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.6.0-P5.md) |
| 31 | 요약 | Codex 입력용 임시 파일 생성 | [`test_input_files.py`](../tests/test_input_files.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.6.0-P5.md) |
| 32 | 요약 | Codex CLI가 임시 파일을 읽음 | [`test_codex_engine.py`](../tests/test_codex_engine.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.6.0-P5.md) |
| 33 | 요약 | 요약 작업 종료 후 임시 파일 삭제 | [`test_input_files.py`](../tests/test_input_files.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.6.0-P5.md) |
| 34 | 요약 | GPT-6 Luna Light 사용 | [`test_codex_contract.py`](../tests/test_codex_contract.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.6.0-P5.md) |
| 35 | 요약 | 화자별 발언 내용 식별 | [`test_summary_prompt.py`](../tests/test_summary_prompt.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.6.0-P5.md) |
| 36 | 요약 | 주요 결정 및 미해결 사항 정리 | [`test_summary_prompt.py`](../tests/test_summary_prompt.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.6.0-P5.md) |
| 37 | 요약 | 없는 내용 생성 금지 | [`test_summary_prompt.py`](../tests/test_summary_prompt.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.6.0-P5.md) |
| 38 | 요약 | 자연스러운 한국어 하오체 사용 | [`test_summary_prompt.py`](../tests/test_summary_prompt.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.6.0-P5.md) |
| 39 | 출력 | 명령을 실행한 동일 채널에 결과 게시 | [`test_publisher.py`](../tests/test_publisher.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.6.0-P5.md) |
| 40 | 출력 | `XX부터 지금까지의 요약이오.` 머리말 사용 | [`test_summary_format.py`](../tests/test_summary_format.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.6.0-P5.md) |
| 41 | 출력 | 길 경우 Discord 제한에 맞춰 분할 | [`test_publisher.py`](../tests/test_publisher.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.6.0-P5.md) |
| 42 | 쿨타임 | 요약 처리 중 중복 실행 차단 | [`test_workflow.py`](../tests/test_workflow.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.7.0-P5.md) |
| 43 | 쿨타임 | 처리 중 호출 시 `요약중이오. 좀 기다리시오.` | [`test_workflow.py`](../tests/test_workflow.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.7.0-P5.md) |
| 44 | 쿨타임 | 성공 후 5분 동안 재실행 차단 | [`test_cooldown.py`](../tests/test_cooldown.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.7.0-P5.md) |
| 45 | 쿨타임 | 성공 쿨타임 중 `아직은 때가 아니오. 00분 00초 뒤에 오시오.` | [`test_cooldown.py`](../tests/test_cooldown.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.7.0-P5.md) |
| 46 | 쿨타임 | 요약 실패 시 성공 쿨타임 미적용 | [`test_cooldown.py`](../tests/test_cooldown.py) | [기존 증거](../Plans/0.DevelopPhase/evidence/0.7.0-P5.md) |

## 별도 경계와 후속 검사

- `100개`와 최신 X개, 7일 캐시 밖 2~4주 요청, KST 오늘 자정, 동일 시각 ID 순서, 부분 전송, 주시 해제 중 작업은 관련 테스트로 추가 확인한다.
- 실제 Discord 관리/일반 사용자 8개 옵션과 모델 품질은 0.9.0-P2에서, 권한 회수·DB/CLI 장애는 P3에서, 보존 경계와 짧은 부하는 P4에서 새 후보 SHA로 확인한다.
- 8/24시간 지속 시간은 [사용자 결정](../Plans/0.DevelopPhase/DURATION_WAIVER.md)에 따라 생략한다. 기능 회귀의 PASS가 장시간 신뢰성 PASS를 뜻하지 않는다.
- §54 제외 기능은 코드·문서에 지원 주장이나 자동 접근 경로가 없는지 검토한다. 자동화된 정적 검색만으로 접근 부재를 완전히 증명하지 않는다.
