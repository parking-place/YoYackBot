# 1.0.0-P1 출시 범위와 선행 증거 검토

0.0.0~0.9.0의 50단계가 STATUS에서 DONE이고, 각 단계 E 증거 커밋이 원격 `main` 이력의 조상임을 확인한다. 이 문서의 검토는 1.0.0 패키지 설치·롤백·운영 배포를 완료했다는 뜻이 아니다. 0.9.0 [출시 후보](release-candidate-0.9.0.md)의 제품 코드 기준은 `8085be4a6958826045be37d423a1806bbf2ecd87`이며, 0.9.0 이후 새 후보 SHA의 전체 검사는 단계 증거에 기록한다.

| 버전 | 5단계 선행 결과 | 확인할 제한 |
|---|---|---|
| [0.0.0](../Plans/0.DevelopPhase/0.0.0/README.md) | 계약·환경·검증 기반 | 단계별 제품 검사 범위를 혼동하지 않음 |
| [0.1.0](../Plans/0.DevelopPhase/0.1.0/README.md) | Guild별 주시 설정·재시작 보존 | 실제 권한 거부 조작 미실행 |
| [0.2.0](../Plans/0.DevelopPhase/0.2.0/README.md) | 명령 문법·KST·상한 | 당시 기능 전 단계 결과와 구분 |
| [0.3.0](../Plans/0.DevelopPhase/0.3.0/README.md) | 실시간 캐시·TTL·coverage | 중지 중 절대 7일 삭제 지연 가능 |
| [0.4.0](../Plans/0.DevelopPhase/0.4.0/README.md) | Discord History·겹침·개수·fallback | 실제 권한 회수 미실행 |
| [0.5.0](../Plans/0.DevelopPhase/0.5.0/README.md) | 고정 CLI/model·격리·정리 | 모델 인증 갱신은 운영 관리 |
| [0.6.0](../Plans/0.DevelopPhase/0.6.0/README.md) | 품질·같은 채널 게시·분할 | 모델 결과 사실성은 모든 대화에서 보장되지 않음 |
| [0.7.0](../Plans/0.DevelopPhase/0.7.0/README.md) | 자동 흐름·중복·성공 대기 | 실제 장애 주입은 후속 단계와 구분 |
| [0.8.0](../Plans/0.DevelopPhase/0.8.0/README.md) | 서비스·상태·복원·보안·부분 관측 | 8시간 연속 시험 `SKIPPED_BY_USER` |
| [0.9.0](../Plans/0.DevelopPhase/0.9.0/README.md) | 전체 회귀·실제 베타·장애·짧은 부하·후보 | 24시간 베타 시험 `SKIPPED_BY_USER` |

## 출시 범위와 남은 게이트

- 운영 대상은 [사용자가 고른 현재 개발 LXC와 봇 계정](../Plans/0.DevelopPhase/1.0.0/TARGET_DECISION.md)의 제자리 승격이다. 단일 Gateway 인스턴스를 유지한다.
- [P2](../Plans/0.DevelopPhase/1.0.0/02-release-package.md)에서 버전을 1.0.0으로 맞춘 깨끗한 설치 산출물과 설치 문서를 검증한다.
- [P3](../Plans/0.DevelopPhase/1.0.0/03-rollback-rehearsal.md)에서 운영 DB를 건드리지 않는 격리 업데이트·복귀를 검증한다.
- [P4](../Plans/0.DevelopPhase/1.0.0/04-production-validation.md)에서 실제 배포 SHA의 같은 채널 게시·쿨타임·서비스·보존 상태를 확인한다. 24시간 관측은 [사용자 결정](../Plans/0.DevelopPhase/DURATION_WAIVER.md)에 따라 생략한다.
- [P5](../Plans/0.DevelopPhase/1.0.0/05-release-publish.md)에서 앞선 검증 SHA에 태그와 GitHub Release를 붙이고 운영 인수·55단계 원격 확인을 마친다.

현재 관찰된 치명/높음 결함은 0건이지만 미실행을 PASS로 바꾸지 않는다. 모델 평가 한 사례에서 ‘내일’ 시점을 놓친 낮은 심각도 결함과 장시간 운영·실제 권한 조작·외부 경고 미검증을 공개 안내에 남긴다. 실제 대화·인증값·서버 식별자는 공개하지 않는다.
