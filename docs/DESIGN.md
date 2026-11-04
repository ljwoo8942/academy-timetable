# 재수종합반 시간표 관리 시스템 — 상세 설계서

- 문서 버전: 2.1
- 작성일: 2026-11-04
- 상태: Python 데스크톱 설계안 (구현 전)
- 프로젝트: academy-timetable
- 기반 운영 모델: 종로학원 재수종합반과 유사한 **반·요일·교시 중심 운영**
- 편성 방식: **수동 배치 + 자동 최적화 혼합형**
- 운영 형태: **Windows PC 우선 / Python 오프라인 데스크톱 프로그램**
- UI: **GUI 우선(PySide6), 일반 사용자 터미널 명령 불필요**

> 주의: 이 문서는 공개적으로 알려진 재수종합반의 교시제 운영 방식을 참고한 독립 소프트웨어 설계안입니다. 종로학원의 공식 시스템이나 내부 업무 규칙을 재현했다고 주장하지 않습니다. 실제 교시 시간, 시수, 캠퍼스 규칙은 운영자가 직접 설정합니다. 예시 데이터는 모두 가상입니다.

## 1. 목표와 범위

### 1.1 목표

학원 관리자가 설치형 Python 프로그램에서 학기별로 반, 교시, 과목별 시수, 강사, 강의실, 선택수업을 정의하고 다음 작업을 수행한다. 기본 기능은 인터넷 연결 없이 작동한다.

1. 반별 주간 시간표를 수동으로 작성한다.
2. 수업 블록을 잠가 자동 편성에서 보호한다.
3. 아직 배정되지 않았거나 재배정이 허용된 수업을 자동 편성한다.
4. 강사·학생·반·강의실 충돌과 시수 미충족을 실시간 검증한다.
5. 생성된 배치안을 검토·수정하여 확정한다.
6. 강사별·반별·강의실별 시간표를 조회하고 출력한다.
7. 정규 반복 시간표와 날짜별 휴강·보강·모의고사를 별도로 관리한다.

### 1.2 주요 사용자와 운영 형태

**MVP는 관리자 PC 한 대에서 실행하는 GUI 기반 단일 사용자 데스크톱 프로그램**이다. 일반 사용자는 Python 코드나 터미널 명령을 직접 입력하지 않는다. 웹 로그인, 서버, 온라인 계정 없이 로컬 DB 파일을 사용한다.

| 사용자 | 지원 범위 |
| --- | --- |
| 관리자 | 모든 정보 수정, 편성, 검토, 확정, 백업, 출력 |
| 강사 | 관리자가 내보낸 강사별 시간표를 열람 |
| 학생/학부모 | 관리자가 내보낸 시간표를 열람(개별 조회는 후속) |

- 첫 버전은 다중 PC 동시 편집/온라인 계정/웹 권한을 제공하지 않는다.
- 운영체제 사용자 계정과 파일 권한으로 로컬 파일 접근을 제한한다. 이는 앱 수준의 다중 사용자 인증을 대체하지 않는다.
- 향후 공동 편집이 필요하면 중앙 서버 구조로 별도 확장한다. SQLite 파일을 네트워크 공유 폴더에서 다중 PC 동시 편집용으로 쓰지 않는다.

### 1.3 우선 구현 범위(MVP)

- 교시표/학기/반/강사/과목/강의실 관리
- 반별 과목 시수 관리
- 주간 반복 시간표 수동 편집 및 잠금
- 충돌 검증과 저장
- 기본 자동 편성 및 미배치 사유
- 배치안 검토 및 게시(확정)
- 반별/강사별 보기와 인쇄

후속 확장: 학생별 선택수업, 특강·모의고사, 날짜별 예외 일정, 세밀한 알림·통계, 선택적 다중 PC 연동.

### 1.4 비목표

- 출결, 학원비 수납, 성적 분석을 첫 버전에 포함하지 않는다.
- 특정 학원의 내부 시수·강사 배정 규칙을 추정하여 기본값으로 강제하지 않는다.
- 자동 편성 결과를 검증 없이 즉시 운영 시간표에 반영하지 않는다.
- 브라우저 UI, REST API, 웹 서버, 온라인 계정은 MVP에 포함하지 않는다.

## 2. 용어와 기본 원칙

| 용어 | 의미 |
| --- | --- |
| 캠퍼스(Academy) | 데이터를 관리하는 학원 또는 지점 |
| 학기(Term) | 하나의 시간표가 적용되는 운영 기간 |
| 반(Cohort) | 자연계 A반 등 정규수업의 기본 학생 집합 |
| 교시(Period) | 운영자가 설정한 수업 시간 슬롯. 예: 08:40~09:30 |
| 과목 시수(Quota) | 반·과목별 일주일에 필요한 수업 교시 수 |
| 배정 항목(Entry) | 요일/교시에 과목·강사·강의실을 배치한 기록 |
| 고정(Locked) | 자동 편성 및 자동 재편성에서 변경할 수 없는 항목 |
| 시간표 버전(Version) | 운영 시간표와 분리된 편집·검토·게시 단위 |
| 선택수업 그룹(Elective Group) | 소속 반과 별개로 학생을 묶어 수업하는 집합 |
| 예외 일정(Exception) | 특정 날짜에만 적용되는 휴강·보강·시험 |

**중요 불변식**

1. 정규수업은 원칙적으로 한 반에 같은 시각 하나만 배정한다.
2. 강사 한 명은 같은 시각에 둘 이상의 수업 또는 감독 업무를 담당할 수 없다.
3. 강의실 한 곳은 동일 시각에 중복 점유할 수 없다.
4. 학생은 서로 다른 반·선택수업을 포함해 같은 시각에 두 수업을 들을 수 없다.
5. 확정된 버전은 직접 수정하지 않으며 복사한 초안에서 수정한다.
6. 잠금된 항목은 자동 편성기가 이동·삭제·변경하지 않는다.
7. 충돌 검사는 교시 번호뿐 아니라 실제 시작·종료 시각의 구간 교집합으로 판단한다.
8. 점심·저녁 등 수업 불가 교시는 일반 수업을 배정할 수 없다.

## 3. 재수종합반 교시 운영 모델

### 3.1 교시 설정 예시

아래 표는 **프로그램 동작을 보여주는 가상 템플릿**이다. 캠퍼스마다 시간과 유형을 바꿀 수 있다.

| 이름 | 시간 | 유형 | 자동 정규수업 배정 |
| --- | --- | --- | --- |
| 아침 테스트/조회 | 08:00~08:30 | 공통 일정 | 불가 |
| 1교시 | 08:40~09:30 | 정규 교시 | 가능 |
| 2교시 | 09:40~10:30 | 정규 교시 | 가능 |
| 3교시 | 10:40~11:30 | 정규 교시 | 가능 |
| 4교시 | 11:40~12:30 | 정규 교시 | 가능 |
| 점심 | 12:30~13:30 | 식사·휴식 | 불가 |
| 5교시 | 13:30~14:20 | 정규 교시 | 가능 |
| 6교시 | 14:30~15:20 | 정규 교시 | 가능 |
| 7교시 | 15:30~16:20 | 정규/선택 | 설정 가능 |
| 저녁/야간 | 운영자 지정 | 자습·특강 등 | 별도 규칙 |

- 교시의 시작·종료 시각은 분 단위로 저장한다.
- 월~토 등 운영 요일과 교시표를 캠퍼스/학기별로 설정한다.
- 2교시 연속 수업은 두 개의 인접한 수업 가능 교시를 점유한다. 쉬는 시간 포함 방식은 템플릿 규칙에 따른다.
- 학기 중 교시표가 변경되면 기존 시간표를 덮어쓰지 않고 새 적용 기간/버전에서 처리한다.

### 3.2 수업 유형

| 유형 | 대상 | 배정 요구 |
| --- | --- | --- |
| REGULAR | 반 전체 | 과목 시수 충족, 담당 강사 지정 |
| ELECTIVE | 선택 학생 그룹 | 실제 학생 충돌 검사 |
| SPECIAL | 특강 그룹 | 선택 강사·강의실·날짜 조건 |
| SELF_STUDY | 반 또는 학생 그룹 | 자습 공간, 필요 시 감독 강사 |
| EXAM | 반/캠퍼스 | 날짜별 예외 일정 우선 |
| COMMON | 조회, 아침 테스트 등 | 공통 고정 일정 |
| BREAK | 점심·저녁 등 | 수업 배정 금지 |

## 4. 사용 흐름

~~~mermaid
flowchart TD
  A["캠퍼스·학기·교시표 설정"] --> B["반·강사·강의실·과목 등록"]
  B --> C["반별 과목 시수·강사 가능 시간 설정"]
  C --> D["수동으로 일부 교시 배치"]
  D --> E["중요 수업 잠금"]
  E --> F["미배치/재배정 허용 교시 자동 편성"]
  F --> G["충돌·시수·선호 조건 검증"]
  G --> H{"승인 가능한가?"}
  H -->|"아니오"| I["수동 수정·조건 변경·부분 재편성"]
  I --> G
  H -->|"예"| J["시간표 버전 확정"]
  J --> K["반별·강사별 출력 및 조회"]
~~~

### 4.1 신규 시간표 생성

1. 학기와 적용 교시표를 선택한다.
2. 반을 생성하고, 반별 과목 시수(예: 국어 6, 수학 9)를 입력한다.
3. 과목별 배정 가능 강사와 강사별 근무 가능 시간/휴무를 입력한다.
4. 수업 가능 교시, 연속 수업 조건, 강의실 수용 인원과 시설을 설정한다.
5. 관리자가 특정 교시를 직접 배치하고 필요한 항목은 잠근다.
6. 자동 편성 범위를 선택하고 배치안을 생성한다.
7. 미배치 사유와 충돌을 확인하여 수동 조정한다.
8. 필수 검증을 통과하면 확정 후 출력한다.

### 4.2 재편성 동작

- **미배치만**: 현재 배정을 모두 유지하고 비어 있는 요구 수업만 탐색한다.
- **잠금 해제 항목 포함**: 잠금 항목은 유지하고 일반 항목은 이동할 수 있다.
- **전체 재편성(잠금 제외)**: 잠기지 않은 항목을 재탐색한다.
- 실행 결과는 별도 배치안으로 저장하며 사용자 승인 전에는 원본 버전을 변경하지 않는다.
- 관리자가 수동으로 만든 항목은 기본 잠금을 권장하되 해제할 수 있게 한다.

## 5. Python 데스크톱 화면 설계

메인 창은 **PySide6 QMainWindow**를 사용한다. 좌측 메뉴, 상단 도구 모음, 중앙 시간표 그리드, 하단 알림 영역으로 구성하며 **URL 없이 Python 위젯 사이를 전환**한다.

| 화면/위젯 이름 | 기능 |
| --- | --- |
| DashboardPage | 전체 반/강사 수, 미배치 시수, 충돌 |
| TermSettingsPage | 학기·운영 기간·요일 |
| PeriodTemplatePage | 0~N교시, 시간, 공통 일정 |
| CohortPage | 반·계열·정원·담임·학생 |
| TeacherPage | 강사·담당 과목·근무 가능 교시 |
| RoomPage | 강의실·시설·정원 |
| QuotaPage | 반별 과목 시수/연속 교시 |
| TimetableEditorPage | 반별·강사별·강의실별 주간표, 수동 배정, 잠금 |
| GenerateDialog | 자동 편성 범위, 가중치, 진행 상태/취소 |
| ProposalReviewDialog | 기존안/새 제안 비교, 미배치 사유, 적용/폐기 |
| VersionHistoryPage | 초안 생성, 검증, 확정, 버전 복사 |
| ExportDialog | 반/강사/강의실 선택, 편집 가능한 .xlsx, PDF, 인쇄 미리보기 |
| BackupRestoreDialog | 로컬 SQLite 백업/복원 |
| ExceptionPage | 날짜별 휴강/보강/모의고사(후속) |

### 5.1 주간 시간표 편집기

~~~text
┌──────────────────────────────────────────────────────────────┐
│ 파일  편집  시간표  자동편성  도구  도움말                        │
│ [학기 ▼] [버전 ▼] [반별][강사별][강의실별] [검증][자동편성][출력]│
├──────────────┬───────────────────────────────────────────────┤
│ 반/강사 목록 │         월    화    수    목    금             │
│ 자연계 A     │ 1교시   국어  수학  영어  수학  국어            │
│ 자연계 B     │ 2교시   수학  영어  국어  영어  수학            │
│ 인문계 A     │ 3교시   영어  국어  수학  국어  탐구            │
│ ...          │ ...                                           │
├──────────────┴───────────────────────────────────────────────┤
│ 선택 셀: 과목/강사/강의실/유형/잠금/삭제                        │
│ 미배치 시수 · 충돌 상세 · [실행 취소][다시 실행][초안 저장]      │
└──────────────────────────────────────────────────────────────┘
~~~

**구현 세부 사항**
- 시간표: QTableView + QAbstractTableModel. 색상과 잠금 아이콘은 데이터 역할 또는 delegate로 표시한다.
- 교시 클릭: QDialog에서 과목·강사·강의실 선택 후 저장. 수업 드래그 이동과 연속 교시 블록을 지원한다.
- 잠금·수정·삭제·복사·실행 취소: QUndoStack 및 명령 객체 사용.
- 반별/강사별/강의실별 화면은 동일한 DB 배정 정보를 다른 관점으로 표시한다.
- 충돌은 해당 셀에 표시하고 하단 패널에 원인·해결 후보를 안내한다.
- QPrintPreviewDialog 및 QPrinter로 인쇄 미리보기와 PDF 출력.

### 5.2 자동 편성의 GUI 응답성

자동 편성(CP-SAT)은 메인 GUI 스레드에서 수행하지 않는다. QThread + Worker 또는 별도 프로세스에서 실행하고 Qt Signal/Slot으로 진행 상태·완료·취소·오류를 전달한다. 워커에서 GUI 위젯을 직접 변경하지 않는다. 진행 중 원본 초안을 보존하고 완료 후 검토 대화상자를 연다.

### 5.3 GUI 필수 사용 시나리오

**프로그램 실행부터 시간표 저장·내보내기까지 모든 일반 사용자의 핵심 기능은 GUI로 수행한다.** 개발자용 명령행은 일반 사용자에게 요구하지 않는다.

| 작업 | GUI 화면 | 조작 | 처리 결과 |
| --- | --- | --- | --- |
| 학기/교시표 | [기본 설정] | 교시 추가, 시간 입력, 저장 | 교시표 갱신 |
| 강사·반·강의실 | [기본 정보 관리] | [추가] 버튼과 입력 양식 | 목록 갱신 |
| 과목 시수 | [과목 시수 관리] | 반 선택, 과목별 주당 교시 수 입력 | 잔여 시수 표시 |
| 수동 편성 | [시간표 편집] | 빈 교시 클릭 → 과목·강사·실 선택 | 수업 블록 생성 |
| 배정 이동 | [시간표 편집] | 드래그 또는 [이동] 대화상자 | 충돌 검사, 셀 갱신 |
| 교시 잠금 | 선택 수업 메뉴 | [잠금/해제] | 자물쇠 아이콘 |
| 자동 편성 | 상단 [자동 편성] | 범위/선호 설정 후 [생성] | 진행 상태와 제안안 |
| 결과 검토 | [배치안 검토] | 미배치 확인, 적용/폐기 | 초안 업데이트 |
| 시간표 확정 | 상단 [검증] → [확정] | 필수 조건 통과 후 확인 | 확정본 |
| 엑셀 저장 | 상단 **[엑셀 저장]** | 반별/강사별/강의실별/전체 선택 → 경로 지정 | 편집 가능한 .xlsx |
| PDF/인쇄 | [PDF/인쇄] | 미리보기 후 저장/출력 | PDF 또는 인쇄 |
| 백업·복원 | [파일] → [백업·복원] | 백업/복원할 파일 선택 | DB 백업/복원 |

**상호작용·안전성 필수 조건**
- 주간 교시 그리드, 클릭/더블클릭 배정, 드래그 이동, 잠금, 검색/필터, 다이얼로그를 제공한다.
- 드래그를 쓰기 어려운 사용자도 버튼 및 키보드로 수업을 이동할 수 있어야 한다.
- 저장되지 않은 변경이 있을 때 학기 전환/창 종료 전에 저장·버리기·취소를 확인한다.
- 삭제·대규모 재편성·시간표 확정·DB 복원 전 영향 범위와 확인 대화상자를 표시한다.
- 충돌 발생 시 관련 반·강사·교시·강의실 및 해결 방향을 한국어로 안내한다.
- Windows 실행 파일을 더블클릭하면 별도 콘솔 창 없이 GUI가 열리는 형태로 패키징한다.
- 편성은 백그라운드에서 실행하고 완료·실패·취소를 Qt Signal로 표시한다.

### 5.4 엑셀 저장 GUI 상세

1. 시간표 화면에서 **[엑셀 저장]** 버튼을 클릭한다.
2. ExportDialog에서 [반별] [강사별] [강의실별] [전체]를 선택한다.
3. 하나 이상의 대상 또는 [모두 선택]을 지정한다.
4. 출력 버전, [전체 배정 목록 포함], [시수 요약 포함], [강사명 표시], [강의실 표시]를 선택한다.
5. [저장] 후 PySide6 QFileDialog에서 파일 이름과 저장 위치를 지정한다.
6. Python openpyxl이 수정 가능한 셀·시트·A4 가로 인쇄 설정이 포함된 .xlsx 파일을 생성한다.
7. 성공 시 파일 경로를 표시하고, 실패 시 파일 잠김/쓰기 권한 등 원인을 안내한다.

Excel 파일에서 수정한 정보는 SQLite 원본에 자동 반영되지 않는다. 엑셀 가져오기는 별도 후속 기능이다.

## 6. 데이터 모델

### 6.1 핵심 엔터티

| 테이블 | 주요 필드 및 목적 |
| --- | --- |
| academies | id, name, timezone |
| operators | id, display_name, created_at (MVP 로컬 이력용, 웹 로그인 없음) |
| academic_terms | id, academy_id, name, start_date, end_date, period_template_id |
| period_templates | id, academy_id, name, active |
| period_slots | id, template_id, day_of_week, period_order, label, start_minute, end_minute, slot_type, allows_regular |
| cohorts | id, term_id, name, track, capacity, home_room_id, homeroom_teacher_id |
| students | id, academy_id, student_code, name, status |
| cohort_enrollments | cohort_id, student_id, valid_from, valid_to |
| subjects | id, academy_id, name, category, color |
| teachers | id, academy_id, name, employment_status, max_daily_periods |
| teacher_subjects | teacher_id, subject_id |
| teacher_availability | id, teacher_id, day_of_week, start_minute, end_minute, availability_type, valid_from, valid_to |
| rooms | id, academy_id, name, capacity, facilities |
| room_unavailability | id, room_id, day_of_week, start_minute, end_minute, reason |
| subject_quotas | id, cohort_id, subject_id, required_periods_per_week, min_per_day, max_per_day, consecutive_periods, preferred_days |
| elective_groups | id, term_id, subject_id, name, teacher_id, capacity |
| elective_enrollments | elective_group_id, student_id |
| timetable_versions | id, term_id, name, status, base_version_id, revision, created_by, published_at |
| timetable_entries | id, version_id, cohort_id?, elective_group_id?, day_of_week, start_period_id, period_count, subject_id?, teacher_id?, room_id?, activity_type, source, is_locked |
| generation_runs | id, timetable_version_id, status, options_json, result_json, started_at, finished_at |
| generation_proposals | id, run_id, entries_snapshot_json, validation_json, score |
| schedule_exceptions | id, term_id, on_date, target_entry_id?, action, replacement_data, reason |
| audit_logs | id, actor_id, entity_type, entity_id, action, before_data, after_data, created_at |

**관계/무결성 주의**

- 모든 엔터티 참조는 같은 캠퍼스/학기에 속하는지 확인한다.
- cohort_id 또는 elective_group_id 중 정확히 하나를 사용하는 수업과 전 캠퍼스 공통일정을 구분하기 위해 대상 유형(audience_type)을 명시적으로 둔다.
- 교시표의 day_of_week 및 실제 시간은 연결된 학기의 설정과 일치해야 한다.
- 복수 교시에 걸친 수업은 점유하는 교시 전체가 유효하고 수업 허용 상태여야 한다.
- 시간표 버전이 달라지면 배정 항목도 버전별로 독립 저장한다.
- 특정 날짜 예외를 적용한 실제 일정 조회에서는 반복 시간표보다 예외의 우선순위가 높다.
- 정규반의 학생 명단과 선택수업 등록 학생 명단을 조합해 실질 학생 충돌을 계산한다.
- 선호 교시, 일일 최대 강의 교시 수 등은 단일 구조에 고정하지 않고 확장 가능한 제약 설정으로 둔다.
- 개인정보를 최소 수집하며, OS 파일 권한·백업 관리·삭제 정책을 별도로 둔다.
- SQLite에서 PRAGMA foreign_keys=ON을 설정하고 트랜잭션을 사용한다.
- DB는 설치 폴더가 아닌 사용자별 앱 데이터 폴더에 저장한다. schema_version과 마이그레이션으로 스키마를 관리한다.

### 6.2 논리 관계도

~~~mermaid
erDiagram
  ACADEMIES ||--o{ ACADEMIC_TERMS : has
  ACADEMIES ||--o{ TEACHERS : employs
  ACADEMIES ||--o{ STUDENTS : enrolls
  ACADEMIES ||--o{ ROOMS : owns
  ACADEMIC_TERMS ||--o{ COHORTS : contains
  ACADEMIC_TERMS ||--o{ TIMETABLE_VERSIONS : has
  PERIOD_TEMPLATES ||--o{ PERIOD_SLOTS : defines
  ACADEMIC_TERMS }o--|| PERIOD_TEMPLATES : uses
  COHORTS ||--o{ SUBJECT_QUOTAS : requires
  SUBJECTS ||--o{ SUBJECT_QUOTAS : counted_in
  TEACHERS ||--o{ TEACHER_SUBJECTS : qualified_for
  SUBJECTS ||--o{ TEACHER_SUBJECTS : eligible_teacher
  STUDENTS ||--o{ COHORT_ENROLLMENTS : joins
  COHORTS ||--o{ COHORT_ENROLLMENTS : contains
  ELECTIVE_GROUPS ||--o{ ELECTIVE_ENROLLMENTS : contains
  STUDENTS ||--o{ ELECTIVE_ENROLLMENTS : joins
  TIMETABLE_VERSIONS ||--o{ TIMETABLE_ENTRIES : contains
  COHORTS o|--o{ TIMETABLE_ENTRIES : audience
  ELECTIVE_GROUPS o|--o{ TIMETABLE_ENTRIES : audience
  TEACHERS o|--o{ TIMETABLE_ENTRIES : teaches
  ROOMS o|--o{ TIMETABLE_ENTRIES : hosted_in
  TIMETABLE_VERSIONS ||--o{ GENERATION_RUNS : requested_for
~~~

### 6.3 배정 데이터 예시

~~~json
{
  "id": "entry_001",
  "version_id": "v1_draft",
  "audience_type": "COHORT",
  "cohort_id": "natural_a",
  "elective_group_id": null,
  "day_of_week": 1,
  "start_period_id": "mon_p1",
  "period_count": 1,
  "subject_id": "math",
  "teacher_id": "teacher_03",
  "room_id": "room_201",
  "activity_type": "REGULAR",
  "source": "MANUAL",
  "is_locked": true
}
~~~

교시 시작·종료 시각은 period_slots를 참조하여 계산한다. 동일한 수업을 서로 다른 화면에 중복 저장하지 않는다.

### 6.4 시간표 버전 상태

~~~text
DRAFT -> VALIDATING -> READY -> PUBLISHED -> ARCHIVED
  ^                      |
  └------ 수정 후 재검증 ┘
~~~

- DRAFT: 수동 변경·자동 생성안 적용 가능
- VALIDATING: 로컬 Python 서비스에서 전체 충돌 검사 진행
- READY: 필수 조건 충족, 게시 가능
- PUBLISHED: 조회 대상이 되는 운영본, 직접 변경 금지
- ARCHIVED: 이전 게시본 기록 보관
- 자동 편성 중 수동 수정으로 기존 배치안이 오래된 경우 revision 검사로 적용을 거절한다.
- 운영본 변경 시 새 DRAFT를 생성하여 게시 후 활성 운영본을 교체한다.

## 7. 충돌 검증 규칙

### 7.1 반드시 충족해야 하는 Hard Constraints

| ID | 검증 규칙 | 오류 예시 |
| --- | --- | --- |
| H01 | 동일 강사는 겹치는 시간에 복수 업무 불가 | 1교시 자연 A/인문 B 동시 강의 |
| H02 | 동일 강의실은 겹치는 시간에 중복 사용 불가 | 201호에 두 수업 배정 |
| H03 | 같은 반의 정규 전체수업 중복 금지 | 자연 A반 국어/수학 동시 |
| H04 | 학생 단위 수강 일정 중복 금지 | 탐구 선택과 정규수업 중복 |
| H05 | 반·과목별 주당 필수 시수 충족 | 수학 9교시 중 8교시만 배정 |
| H06 | 담당 강사는 해당 과목 지도 가능 | 국어 강사에게 수학 배정 |
| H07 | 강사 근무 불가 시간 배정 금지 | 수요일 휴무 강사 배정 |
| H08 | 강의실 정원·필수 시설 충족 | 30명 수업을 20석 교실에 배정 |
| H09 | 수업 가능한 교시에만 배정 | 점심시간 정규수업 생성 |
| H10 | 연속 수업은 유효한 교시를 모두 점유 | 교시 3·4 연속 요구 불충족 |
| H11 | 잠금 항목 자동 변경 금지 | 잠금 수업 자동 이동 |
| H12 | 캠퍼스·학기·버전 소속 일치 | 다른 캠퍼스 강의실 배정 |
| H13 | 게시 시 모든 필수 수업 요구량 충족 | 미배치 시수 존재 |
| H14 | 특정 날짜 예외를 적용한 실제 일정도 충돌 검사 | 보강 강사 중복 |

시간 겹침 판정은 두 시간 구간 [시작, 종료)가 교차하는지를 기준으로 한다. 시작 시각이 다른 일정의 종료 시각과 같다면 겹치지 않는다.

### 7.2 가중치 기반 Soft Constraints

아래 값은 제품 초기 기본값의 **예시**이며 실제 운영에서 변경할 수 있다.

| ID | 선호 규칙 | 예시 가중치 |
| --- | --- | ---: |
| S01 | 강사 선호 시간 충족 | 25 |
| S02 | 반/학생 선호 시간 충족 | 25 |
| S03 | 과목의 요일별 분산 | 15 |
| S04 | 강사 공백 시간 최소화 | 15 |
| S05 | 강의실 이동 최소화 | 10 |
| S06 | 기존 시간표 변경 최소화 | 10 |

필수 조건은 점수와 무관하게 반드시 만족해야 한다. 유연 조건 위반량을 정규화해 가중합을 최소화한다. 필요 시 운영자가 우선순위를 바꿀 수 있다.

## 8. 자동 편성 엔진

### 8.1 기술 선택 — Python 설치형 프로그램

| 영역 | 선택 | 역할 |
| --- | --- | --- |
| 언어 | Python 3.12+ (호환성 확인) | 앱 전체 |
| 데스크톱 GUI | PySide6 (Qt for Python) | 창, 시간표, 대화상자 |
| 데이터 저장 | SQLite / Python sqlite3 | 오프라인 DB |
| 자동 편성 | Google OR-Tools CP-SAT | 제약 조건 최적화 |
| 계산 작업 | QThread/Worker 또는 별도 프로세스 | UI 멈춤 방지 |
| Excel | openpyxl | XLSX 출력 |
| PDF/인쇄 | PySide6 QPrinter, QPrintPreviewDialog | PDF·인쇄 |
| 배포 | PyInstaller | Windows 실행 파일(후속) |
| 테스트 | pytest, pytest-qt(선택) | 규칙·화면 테스트 |

**React, TypeScript, Node.js, FastAPI 서버, PostgreSQL, REST API를 MVP에 사용하지 않는다.** 하나의 로컬 Python 애플리케이션이 화면 → 서비스 → DB 및 최적화 엔진을 직접 호출한다.

~~~text
PySide6 GUI
   │ Python 메서드 및 Qt Signal/Slot
   ▼
Service / Validation
   ├── Repositories ── sqlite3 ── academy_timetable.db
   ├── Scheduler ── OR-Tools CP-SAT
   ├── Version / Audit / Backup
   └── Export ── PDF / XLSX / 인쇄
~~~

**로컬 저장/백업**
- DB 경로는 사용자별 OS 앱 데이터 경로(Windows 예: %LOCALAPPDATA%/AcademyTimetable)에 둔다.
- 일관성 있는 백업은 sqlite3 Connection.backup()을 사용한다. 실행 중 DB 파일을 단순 복사하지 않는다.
- 복원 전에 DB 연결을 닫고 현재 데이터를 별도 백업한다.
- 동시 PC 접속용 네트워크 드라이브/클라우드 동기화 폴더에 DB 원본을 두지 않는다.

### 8.2 입력/출력

입력:
- 학기 및 교시표
- 반 목록, 과목별 요구 시수 및 연속 수업 조건
- 강사별 지도 가능 과목, 근무 가능/불가 교시
- 강의실 정원, 설비, 사용 불가 시간
- 현재 배정 데이터와 잠금 정보
- 자동 편성 범위 및 선호 가중치
- 학생/선택수업 충돌 정보(해당 기능 활성화 시)

출력:
- 배정 제안(entries)
- 배치 완료/미배치 교시 수
- 규칙 검증 결과 및 경고
- 최적화 점수 및 사용한 설정
- 해결 불가능한 조건에 대한 진단 정보

### 8.3 편성 흐름

~~~text
1. 요청 검증 및 데이터 스냅샷 생성
2. 잠금된 배정과 수업 불가 교시를 점유 상태로 적용
3. 반별 요구 시수를 실제 배치 단위(session)로 생성
4. session별 가능한 (요일, 교시, 강사, 강의실) 후보 계산
5. Hard Constraints로 불가능한 후보 제거
6. CP-SAT로 유효한 조합 탐색
7. Soft Constraints 점수로 후보 최적화
8. 결과 재검증 후 SQLite에 배치안(proposal) 저장
9. 관리자가 PySide6 GUI에서 수동 조정하거나 제안안을 초안에 적용
10. 최종 확정 전에 로컬 서비스가 전체 조건을 재검사
~~~

### 8.4 모델링 원칙

- 결정 변수는 각 session이 특정 시간·강사·강의실 후보에 선택되었는지 나타내는 불리언 변수로 둔다.
- 각 필수 session은 정확히 하나의 후보를 선택한다. 부분 편성 모드에서는 미배치를 명시적인 선택으로 표현한다.
- 강사·반·학생·강의실은 점유 시간 구간별 at-most-one 제약을 둔다.
- 과목 시수는 배정된 session의 교시 수 합계로 계산한다.
- 연속 수업은 단일 session이 여러 교시를 점유하도록 모델링한다.
- 기존 고정 배정은 모델의 상수 제약으로 반영한다.
- 불가능한 경우 원본 초안은 그대로 두고 실패 사유 또는 부분 제안만 반환한다.
- 부분 편성 모드에서는 **먼저 배정 가능한 필수 시수의 최대화, 그다음 선호 최적화** 순서의 우선순위(사전식 최적화)를 사용한다.
- 최적화 시간 제한과 중단 정책은 실제 학원 규모를 측정한 후 결정한다.

### 8.5 실패 이유 안내

예시:

> 수학 1교시 미배치: 담당 가능 강사의 남은 근무 시간에 수용 가능한 강의실이 존재하지 않습니다.

실패 진단은 확정적인 전체 불가능 원인 증명과 간단한 후보 필터 분석을 구분해야 한다. 복잡한 모델에서는 여러 제약이 복합적으로 충돌할 수 있으므로 원인을 단정하지 않는다. 관리자에게 강사 가능 시간 조정, 강의실 변경, 고정 교시 해제 검토 등의 해결 후보를 보여준다.

## 9. Python 서비스 인터페이스 설계

웹 API가 아니라 **PySide6 UI → Python Service → SQLite/OR-Tools** 직접 호출 구조를 사용한다.

### 9.1 계층별 책임

| 계층 | 모듈 예시 | 역할 |
| --- | --- | --- |
| UI | ui/pages, ui/dialogs | 화면 표시·사용자 입력 |
| View Model | ui/models/timetable_model.py | QAbstractTableModel, 셀 색상/잠금 |
| Service | services/timetable_service.py | 수동 배정, 이동, 확정, 버전 |
| Validation | services/validation_service.py | 자원 중복, 주간 시수 및 조건 검증 |
| Solver | scheduler/cp_sat_solver.py | 후보 생성과 최적 배치 |
| Repository | repositories | SQLite CRUD 및 트랜잭션 |
| Export | export/pdf_exporter.py, excel_exporter.py | 인쇄/PDF/편집 가능한 다중 시트 XLSX |
| Backup | services/backup_service.py | 로컬 DB 백업/복원 |

### 9.2 Python 메서드(설계 예시)

~~~python
class TimetableService:
    def create_draft(self, term_id: str, base_version_id: str | None = None) -> str: ...
    def list_entries(self, version_id: str, view: str, target_id: str | None = None) -> list: ...
    def assign_entry(self, version_id: str, entry_data: dict) -> str: ...
    def move_entry(self, entry_id: str, new_slot_id: str) -> None: ...
    def set_locked(self, entry_id: str, locked: bool) -> None: ...
    def validate(self, version_id: str) -> list: ...
    def apply_proposal(self, version_id: str, proposal_id: str, expected_revision: int) -> None: ...
    def publish(self, version_id: str) -> None: ...

class SchedulerService:
    def generate(self, version_id: str, options: dict, on_progress=None) -> str: ...
    def cancel(self, run_id: str) -> None: ...

class BackupService:
    def backup_to(self, destination_path: str) -> None: ...
    def restore_from(self, source_path: str) -> None: ...
~~~

서비스 계층의 반환 값은 추후 dataclass/Typed 모델로 구체화한다. UI에서 직접 SQL을 실행하지 않는다.

### 9.3 자동 편성 옵션 예시

~~~python
options = {
    "mode": "UNLOCKED_AND_UNASSIGNED",
    "preserve_locked": True,
    "allow_partial": True,
    "weights": {
        "teacher_preference": 25,
        "cohort_preference": 25,
        "weekday_distribution": 15,
        "teacher_idle_gap": 15,
        "room_consistency": 10,
        "minimize_changes": 10,
    },
    "expected_revision": 7,
}
run_id = scheduler_service.generate("v1_draft", options)
~~~

- 최적화는 DB에서 읽은 불변 스냅샷을 입력으로 사용한다.
- 워커에서 계산한 제안은 별도 테이블에 저장하며 관리자 확인 전 기존 초안을 덮어쓰지 않는다.
- 적용 직전 expected_revision과 현재 revision을 비교해 변경되었으면 확인/재편성을 요청한다.

### 9.4 오류 처리

HTTP 오류 코드 대신 Python 예외 및 결과 타입을 사용한다. 예: ValidationError, ScheduleConflictError, StaleRevisionError, SolverInfeasibleError, StorageError, BackupError. 사용자는 한국어 오류 대화상자와 관련 반/강사/교시 및 해결 후보를 확인한다.

## 10. 시간표 검증 및 게시 정책

1. 편집 중에는 오류를 즉시 표시할 수 있으나 유효하지 않은 제안 상태는 운영본에 반영되지 않는다.
2. 로컬 Python 서비스 계층은 기본 무결성 및 자원 중복을 검사한다.
3. 자동 편성 결과를 **원본이 아닌 제안안**으로 저장한다.
4. 제안안 적용 때 입력 시점의 revision과 현재 revision이 같은지 확인한다.
5. '시간표 확정' 기능은 전체 Hard Constraints, 필수 시수, 적용 기간을 재검증한다.
6. 통과한 경우 단일 트랜잭션으로 기존 운영본을 보관하고 새 버전을 PUBLISHED로 만든다.
7. 게시본 직접 편집을 차단하고 변경이 필요하면 새 DRAFT를 생성한다.
8. 모든 주요 변경과 게시 이력은 audit_logs에 남긴다.

자동 편성 도중 수동 편집이 이루어졌다면 revision 검사를 통해 이전 계산 결과가 최신 초안을 덮어쓰지 못하도록 한다. HTTP/ETag는 사용하지 않는다.

## 11. 날짜별 예외와 자습

- **정규 반복 시간표**: 요일·교시별 기본 수업. term 기간 내 매주 반복.
- **특정 날짜 예외**: EXAM, CANCEL, SUBSTITUTE, MAKEUP, MOVE 등.
- **조회 규칙**: 특정 날짜의 시간표를 요청하면 정규 시간표를 복제한 가상 결과에 예외를 적용한다.
- **검증 규칙**: 보강·대체 수업도 강사/학생/강의실 자원 중복 검사 대상이다.
- **자습**: 별도 활동 유형이며 강의실 또는 자습실, 감독 강사 필요 여부를 설정한다.

선택수업은 반 전체 시간표에 단일 과목이 아니라 "선택수업 블록"으로 보여줄 수 있으며, 학생·선택그룹별 세부 시간표에서는 실제 선택 과목과 강의실을 표시한다.

## 12. 출력 및 조회 — Excel(.xlsx) 정식 지원

**Excel 출력은 MVP의 필수 기능이다.** 화면을 캡처한 이미지가 아니라 **Excel에서 직접 수정할 수 있는 일반 셀 기반의 .xlsx 파일**로 내보낸다. PDF와 프린터 출력은 별도로 유지한다.

### 12.1 내보내기 대상 및 선택 옵션

| 종류 | 엑셀 시트 | 셀에 포함되는 정보 |
| --- | --- | --- |
| 반별 시간표 | 선택 반 또는 모든 반 각각 시트 | 요일×교시, 과목, 강사, 강의실 |
| 강사별 시간표 | 선택 강사 또는 모든 강사 각각 시트 | 요일×교시, 반, 과목, 강의실 |
| 강의실별 시간표 | 선택 강의실 또는 모든 강의실 각각 시트 | 요일×교시, 반, 강사, 과목 |
| 전체 배정 목록 | 전체_배정목록 시트 | 학기, 요일, 교시, 시간, 반, 과목, 강사, 강의실, 수업 유형, 잠금 |
| 시수 요약 | 시수_요약 시트 | 반·과목별 필수 시수, 실제 배정, 차이 |
| 검증 결과(선택) | 검증_결과 시트 | 충돌/미배치 항목 및 원인, 관리자용 |

내보내기 대화상자(ExportDialog)에 **대상 유형, 대상 여러 개 선택, 초안/확정본, 과목·강사·실 표시 여부, 시수 요약 포함 여부, 파일 경로**를 제공한다. 파일 머리말에 학기명, 시간표 버전, 적용 기간, 출력일, 초안 여부를 기록한다.

### 12.2 Excel 파일 기능 요구사항

- Python openpyxl로 Workbook을 생성하고 .xlsx로 저장한다. 사용 PC에 Microsoft Excel이 설치되어 있지 않아도 생성할 수 있어야 한다.
- 엑셀 파일은 텍스트를 포함하는 **편집 가능한 셀**로 만든다. 과목, 담당 강사, 강의실은 줄바꿈으로 표시할 수 있다.
- 교시·시간을 행 헤더, 운영 요일(월~토 등)을 열 헤더로 작성한다.
- 과목별 색상, 제목 강조, 테두리, 셀 가운데 정렬, 자동 줄바꿈, 열 너비/행 높이, 헤더 행 고정을 적용한다.
- 연속 교시 수업은 필요한 경우 세로 셀 병합으로 표시하되, 병합 전 다른 배정이 덮이지 않는지 확인한다.
- 인쇄 설정은 기본 A4 가로, 인쇄 영역 지정, 한 페이지 너비 맞춤, 상단 제목/헤더 반복, 여백 설정으로 한다.
- 워크시트 이름의 31자 제한, 금지 문자, 중복 시트명 문제를 자동 처리한다.
- UTF-8 기반 한국어 텍스트를 유니코드 셀 값으로 저장하여 한글이 정상 표시되도록 한다.
- 저장 대상 파일이 존재하면 덮어쓰기 확인, 파일 사용 중 또는 권한 부족이면 오류 안내, 원본 시간표 유지.
- 출력에 불필요한 학생 연락처/개인정보를 넣지 않는다.
- **Excel을 수정해도 SQLite 원본 시간표가 자동 변경되지는 않는다.** Excel 가져오기(import)는 후속 기능으로 분리한다.

### 12.3 엑셀 파일 구성 예시

~~~text
재수종합반_2026-2학기_시간표.xlsx
├── 자연계_A반
├── 자연계_B반
├── 인문계_A반
├── 강사_김OO
├── 강사_이OO
├── 강의실_201
├── 전체_배정목록
└── 시수_요약
~~~

각 반의 시간표 시트 예시:

| 교시 | 시간 | 월 | 화 | 수 | 목 | 금 |
| --- | --- | --- | --- | --- | --- | --- |
| 1교시 | 08:40~09:30 | 국어 / 김OO / 201 | 수학 / 이OO / 201 | 영어 / 박OO / 201 | 수학 / 이OO / 201 | 국어 / 김OO / 201 |
| 2교시 | 09:40~10:30 | 수학 / 이OO / 201 | 영어 / 박OO / 201 | 국어 / 김OO / 201 | 영어 / 박OO / 201 | 수학 / 이OO / 201 |

모든 시트와 데이터는 설계 예시이며, 실제 편성은 저장된 교시표와 배정 내역에 따라 생성한다.

### 12.4 Python 내보내기 서비스 인터페이스

~~~python
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

@dataclass
class ExportOptions:
    scope: Literal["cohort", "teacher", "room", "all"]
    target_ids: list[str]
    include_assignment_list: bool = True
    include_quota_summary: bool = True
    include_validation_sheet: bool = False
    show_teacher: bool = True
    show_room: bool = True

class ExcelExporter:
    def export_timetable(
        self, version_id: str, destination: Path, options: ExportOptions
    ) -> Path: ...
~~~

- GUI는 QFileDialog로 경로를 선택하고, ExcelExporter는 서비스 계층에서 전달받은 검증된 조회 데이터로 xlsx를 만든다.
- ExcelExporter는 UI 위젯, SQLite 커서에 직접 의존하지 않도록 구현한다.
- 성공 시 저장 경로를 반환하고 오류 시 명시적 예외를 발생시킨다.
- PDF 인쇄는 별도 exporter를 사용하되 동일한 조회 데이터를 공유한다.

### 12.5 기능 검증 및 테스트

1. 특정 반/강사/강의실을 선택하면 정확한 대상 시트만 생성된다.
2. 전체 내보내기에서는 모든 대상별 시트와 전체 배정 목록/시수 요약이 생성된다.
3. 생성된 xlsx를 openpyxl.load_workbook으로 다시 열었을 때 모든 시트/셀 정보가 일치한다.
4. 과목 색상, 셀 병합, 헤더 고정, A4 가로, 인쇄 영역이 설정된다.
5. 한글 텍스트, 31자 이상의 이름, 같은 이름을 가진 시트, 금지 문자가 안전하게 처리된다.
6. 파일의 수업 셀을 수정해 다시 저장할 수 있다.
7. 엑셀 출력이 원본 SQLite DB를 수정하지 않는다.
8. 파일 잠김/권한 부족/덮어쓰기 취소 등 실패 상황을 사용자에게 설명한다.
9. 초안 표기, 적용 기간, 출력일 등 메타데이터가 정확하다.
10. 개인정보와 내부 감사 정보가 선택하지 않은 출력물에 포함되지 않는다.

### 12.6 PDF 및 프린터 출력

- PySide6 QPrinter와 QPrintPreviewDialog를 사용하여 인쇄와 PDF 저장을 지원한다.
- PDF는 인쇄·공유용, **Excel(.xlsx)은 편집·추가 가공용**으로 구분한다.
- 반별·강사별·강의실별 조회 데이터를 공통으로 사용해 Excel·PDF의 시간표 내용 불일치를 방지한다.


## 13. 권장 Python 프로젝트 구조

~~~text
academy-timetable/
├── README.md
├── docs/
│   └── DESIGN.md
├── pyproject.toml                   # Python 의존성 및 설정 (예정)
├── src/
│   └── academy_timetable/
│       ├── __init__.py
│       ├── __main__.py              # python -m academy_timetable
│       ├── app.py                   # QApplication 진입점
│       ├── config.py                # 로컬 앱 데이터 경로
│       ├── ui/
│       │   ├── main_window.py
│       │   ├── pages/
│       │   ├── dialogs/
│       │   └── models/              # Qt 테이블 모델
│       ├── domain/                  # 데이터 클래스/enum
│       ├── services/                # 배정·검증·확정·백업
│       ├── scheduler/               # CP-SAT
│       ├── repositories/            # SQLite CRUD
│       ├── db/
│       │   ├── connection.py
│       │   ├── schema.sql
│       │   └── migrations/
│       ├── export/                  # PDF·엑셀·인쇄
│       └── resources/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── gui/
└── packaging/
    └── pyinstaller.spec             # 실행 파일 배포 (후속)
~~~

위 파일 트리는 **개발 목표**이며 소스 파일을 실제 생성했다는 의미는 아니다.

### 13.1 개발·배포

- 개발 환경: Python 가상환경, python -m academy_timetable 진입점.
- Windows 배포 우선: PyInstaller 폴더 배포 형태로 빌드, 필요 시 단일 exe 검토.
- macOS 실행은 별도 빌드/테스트로 후속 지원 가능. Windows exe는 Windows에서 빌드한다.
- 앱 데이터(데이터베이스·설정·로그)는 설치 폴더가 아닌 사용자 데이터 디렉터리에 둔다.
- 첫 실행 시 DB 스키마 생성/마이그레이션. 샘플 데이터는 명시적 메뉴에서만 추가한다.

## 14. 개발 단계 및 완료 기준

| 단계 | 구현 내용 | 완료 기준 |
| --- | --- | --- |
| M1 | 기준정보·교시표·과목 시수 | 반, 과목, 강사, 강의실, 교시를 CRUD 가능 |
| M2 | 수동 시간표 편집기 | 교시 배정·이동·삭제·잠금·저장 가능 |
| M3 | 충돌 검사 | 강사/반/교실 중복과 시수 오류 정확히 검출 |
| M4 | 자동 편성 | 고정 교시 유지, 남은 시수 배치, 미배치 반환 |
| M5 | 혼합 편성 검토 | 제안 비교·적용·부분 재편성·undo |
| M6 | 확정·버전 관리·출력 | 운영본 보호, 게시, 복원, 출력 |
| M7 | 선택수업·예외 일정 | 학생 그룹/휴강/보강/모의고사 처리 |
| M8 | 운영 고도화 | 권한, 배포, 관측, 성능 개선 |

### 14.1 핵심 테스트 케이스

1. **강사 중복**: A반과 B반이 동일 교시에 같은 강사를 사용하면 거절된다.
2. **강의실 중복**: 서로 다른 반에서 같은 공간을 같은 시간에 쓰면 거절된다.
3. **학생 중복**: 선택수업 학생이 정규반 수업과 겹치면 거절된다.
4. **고정 보호**: 자동 재배치 후 잠금된 entry의 시간·강사·강의실이 유지된다.
5. **시수 보존**: 과목별 required_periods_per_week와 실제 배정 교시 수가 일치한다.
6. **연속 교시**: 두 교시 수업이 허용 슬롯을 모두 점유하며 중복되지 않는다.
7. **부분 편성**: 완전 해가 없어도 기존 초안 보존, 미배치 목록과 원인 표시.
8. **낙관적 잠금**: 오래된 revision 기반 배치안 적용은 StaleRevisionError로 거절한다.
9. **게시 원자성**: 게시 실패 시 기존 PUBLISHED 버전은 그대로 유지된다.
10. **날짜별 예외**: 하루만 휴강해도 다른 주 반복 시간표는 변경되지 않는다.
11. **로컬 데이터 접근**: SQLite가 OS 사용자별 데이터 폴더에 생성되고 파일 접근 권한이 적용된다.
12. **시간 충돌 경계**: 한 수업의 종료와 다른 수업의 시작이 같으면 겹치지 않는다.
13. **GUI 응답성**: 자동 편성 중에도 창이 멈추지 않고 완료/취소/실패 상태가 표시된다.
14. **백업·복원**: 일관성 있는 DB 백업을 만들고 복원 이전 원본을 보존한다.
15. **오프라인**: 인터넷 없이 등록·수동/자동 편성·출력이 작동한다.
16. **엑셀 출력**: 모든 반·강사·강의실별 편집 가능한 .xlsx와 인쇄 설정을 검증한다.

### 14.2 품질 및 보안

- Python 서비스 계층 검증, SQLite 외래키/트랜잭션, 캠퍼스별 데이터 범위 확인
- 학생 개인정보 최소화, OS 파일 접근 권한, 변경 감사 로그. 첫 버전에는 온라인 계정/비밀번호를 저장하지 않음
- 정기 백업과 시간표 버전 복원 절차
- 자동 편성 시간 제한과 작업 취소/실패 복구
- 성능 목표는 실제 반·강사·교실 수 데이터를 확보한 뒤 확정
- 핵심 충돌 검사와 게시 처리에 자동화 테스트 적용

## 15. 설계 결정 및 미확정 항목

### 확정된 기본 방향

- **재수종합반의 반×요일×교시 중심**
- **교시표는 캠퍼스/학기별 설정 가능**
- **수동 고정 + 자동 편성 + 관리자 검토**
- **강사·반·학생·강의실 중복 검증**
- **초안과 게시본 분리**
- **Python + PySide6 + SQLite + OR-Tools**를 기본 스택으로 사용
- **Windows PC용 설치형 오프라인 프로그램** 우선
- **웹 UI·REST API·웹 서버 없이 로컬 Python 함수 호출**

### 구현 전에 결정할 항목

- 실제 운영 캠퍼스의 교시 수 및 운영 요일
- 과목별 필수 시수와 반별 편차
- 한 교시에 여러 과목을 병행하는 이동수업의 세부 운영
- 자습실/감독 강사 배치 기준
- 강사별 일일 최대 강의 및 연속 강의 제한
- 인쇄·파일 공유 외 별도 학생/학부모 조회 도구의 도입 여부
- 인쇄 레이아웃 및 파일 양식
- 자동 편성 성능 목표를 검증할 샘플 데이터 규모

## 16. 참고 자료

- [종로학원 공식 홈페이지](https://www.jongro.co.kr/) — 시간표 운영 구조의 참고 출처. 교시 구성은 캠퍼스·모집 과정·연도에 따라 변동될 수 있음.
- [Google OR-Tools CP-SAT](https://developers.google.com/optimization/cp/cp_solver)
- [Qt for Python / PySide6](https://doc.qt.io/qtforpython-6/)
- [Python sqlite3](https://docs.python.org/3/library/sqlite3.html)
- [openpyxl](https://openpyxl.readthedocs.io/)
- [PyInstaller](https://pyinstaller.org/)

---

**문서 활용 안내:** 이 설계서를 기준으로 다음 작업은 (1) 실제 캠퍼스의 교시표·시수 결정, (2) DB 마이그레이션, (3) 수동 편집기, (4) 제약 검증, (5) 자동 편성 엔진 순서로 진행한다.
