# 1.2.0 검증 목록

총 **7단계·28검사**. 계획 게시 시점의 모든 결과는 **NOT_RUN**이다. 감사의 11건 합성 재현은 결함 존재 증거이며 수정 결과가 아니다. 실제 모델은 P6 8건, 시험 Discord는 P7 배포 후 사용자 확인이다.

| 검사 ID | 단계·범위 | 환경 | 통과 기준 | 결과 |
|---|---|---|---|---|
| `T120-P1-A` | [P1](01-permissions-settings.md) B01 | LXC 대역 | 요청자/공개 독자의 권한 차이, 모든 DM 분할·권한 변경·DM 실패에서 공개 이름/ID/존재 누출 없음 | NOT_RUN |
| `T120-P1-B` | P1 B02 | LXC 임시 DB | 역할 삭제와 추가·해제·전체 해제의 모든 결정적 교차 순서에서 권한 부활·변경 유실 없음 | NOT_RUN |
| `T120-P1-C` | P1 B09 | LXC 잠금 주입 | 실제 UI callback의 DB 대기 전 defer, event-loop tick 유지, 저장 결과·revision·권한 일치 | NOT_RUN |
| `T120-P1-D` | P1 B14 | LXC 대역 | 오프라인 삭제·cleanup 실패 후 유효한 draft 저장, 사라진 ID만 정리, 전체 회귀 | NOT_RUN |
| `T120-P2-A` | [P2](02-cache-consistency.md) B03 | LXC 임시 DB·History | 현행 workflow에서 오프라인 삭제·오래된 편집 복구, 실패 구간 삭제/ready 금지, live 경합 보존 | NOT_RUN |
| `T120-P2-B` | P2 B04 | LXC 시계·재시작 | history/overlap/ready 중단·시간 전진·재단절의 공백 해소 전 ready 금지 | NOT_RUN |
| `T120-P2-C` | P2 B06 | LXC 임시 DB | retention 1/7/30일·축소·장기중단·cached edit의 모든 쓰기에 현재 cutoff 적용 | NOT_RUN |
| `T120-P2-D` | P2 B07 | LXC 임시 DB | T1/T2·동시각·timestamp 없음·raw/cached 교차에서 시간 역행·삭제 부활 없음, 전체 회귀 | NOT_RUN |
| `T120-P3-A` | [P3](03-worker-memory.md) B05 | LXC 오류 주입 | 페이지 오류 뒤 defer/block 오류가 전체 loop를 종료하지 않고 다른 채널 처리 유지 | NOT_RUN |
| `T120-P3-B` | P3 B05 | LXC 오류·취소 | DB 복구 후 재개, worker 종료 감지, backoff·정상 취소·슬롯/파일 정리 | NOT_RUN |
| `T120-P3-C` | P3 B08 | LXC 실제 collector·합성 입력 | bounded batch·최종 JSONL budget 준수, 초과 시 모델/게시/성공 쿨타임 없음, F10 추가 후 재검사 | NOT_RUN |
| `T120-P3-D` | P3 B08·통합 | LXC 합성 부하 | DB 10배·총 6회에서 사전 고정한 행 수/RSS/시간 한도 충족, 병렬·취소·빈 입력·전체 회귀 | NOT_RUN |
| `T120-P4-A` | [P4](04-output-runtime.md) B10 | LXC FakeRunner | 중첩 Markdown의 화자 내부 키 차단, 코드/인용의 정상 문자열 유지 | NOT_RUN |
| `T120-P4-B` | P4 B11 | LXC FakeRunner | 평가/고지 단독·평가 제거 뒤 빈 본문은 성공·게시·쿨타임 불가 | NOT_RUN |
| `T120-P4-C` | P4 B12 | LXC FakeRunner | 보조·최종 출력 공통 검증, 실패 표식/도구 경로 거절, 유효 본문+불량 평가의 안전한 생략 | NOT_RUN |
| `T120-P4-D` | P4 B13 | LXC 합성 CLI | PATH/절대/누락/비실행/버전불일치의 config·ready·runner·usage 판정 일치, 전체 회귀 | NOT_RUN |
| `T120-P5-A` | [P5](05-collection-progress.md) F02 | LXC 대역 | 단계·차단·retry·준비 안내 대기·공백·worker 상태와 표시 일치 | NOT_RUN |
| `T120-P5-B` | P5 F02 | LXC 임시 DB | 페이지/cursor/진척 원자 commit, 실패·재시도·stale token 중복 집계 없음, 회차·재시작 일관 | NOT_RUN |
| `T120-P5-C` | P5 F02 | LXC 대역 | 현재 채널만 표시, 원문·다른 채널·예외 미노출, 추정 ETA/퍼센트 없음, 모름과 0 구분 | NOT_RUN |
| `T120-P5-D` | P5 F02 | LXC 복귀 DB | 선택 테이블 생성·백업 제외·해제/탈퇴 정리·구버전 복귀 후 재업그레이드, 전체 회귀 | NOT_RUN |
| `T120-P6-A` | [P6](06-reply-context.md) F10 | LXC 합성 입력 | 단일/교차/동명/체인의 선택 집합 내부 참조 정확, 기존 범위·개수·순서 유지 | NOT_RUN |
| `T120-P6-B` | P6 F10 | LXC 대역 | 범위 밖/삭제/필터 제외/다른 채널/미확인은 null, 추가 fetch·raw ID·키 누출 없음, byte·호출 상한 유지 | NOT_RUN |
| `T120-P6-C` | P6 F10 | LXC 복귀 DB | 기존 캐시·복원·경합·구버전 writer·정리·재업그레이드의 참조 무효화와 백업 제외 | NOT_RUN |
| `T120-P6-D` | P6 F10 | LXC 실제 모델 | 합성 8건의 화자/대상 귀속·허구·키 누출 오류 0, 호출 수·지연 기록 | NOT_RUN |
| `T120-P7-A` | [P7](07-integration-release.md) 전체 | LXC/CI | 정확 후보 SHA의 전체 회귀·집계·범위·설정·비밀정보·문서 검사 | NOT_RUN |
| `T120-P7-B` | P7 설치·복귀 | LXC 격리 | 1.1.3a↔1.2.0 재업그레이드, 선택 테이블·설정 백업/복원·깨끗한 설치 | NOT_RUN |
| `T120-P7-C` | P7 사용자 확인 | 시험 Discord/LXC | DM 목록/실패·역할·F02·F10·기존 명령의 사용자 확인과 로그 일치, 미확인 명시 | NOT_RUN |
| `T120-P7-D` | P7 출시 이력 | GitHub/LXC | 후보·서비스·패키지 SHA, C/E/D·main CI·태그·Release 일치 | NOT_RUN |

실행 시 각 검사 결과·정확한 SHA·환경·한계·공개 가능한 증거를 [증거 양식](../EVIDENCE_TEMPLATE.md)에 남긴다. 검사 A~D와 구현 C 검증, 증거 E의 원격 반영·CI 성공 후 [STATUS](STATUS.md)에 DONE을 기록하는 종료 커밋 D를 만든다. D의 원격 반영·필요 CI까지 확인한 뒤 완료를 보고한다. 마지막 P7의 출시 전·후 증거 순서는 [출시 단계](07-integration-release.md)를 따른다.
