# 재수종합반 시간표 관리 시스템 — 상세 설계서

- 문서 버전: 1.0
- 작성일: 2026-11-04
- 상태: 초기 설계안 (구현 전)
- 프로젝트: academy-timetable
- 기반 운영 모델: 종로학원 재수종합반과 유사한 **반·요일·교시 중심 운영**
- 편성 방식: **수동 배치 + 자동 최적화 혼합형**

> 주의: 이 문서는 공개적으로 알려진 재수종합반의 교시제 운영 방식을 참고한 독립 소프트웨어 설계안입니다. 종로학원의 공식 시스템이나 내부 업무 규칙을 재현했다고 주장하지 않습니다. 실제 교시 시간, 시수, 캠퍼스 규칙은 운영자가 직접 설정합니다. 예시 데이터는 모두 가상입니다.

## 1. 목표와 범위

### 1.1 목표

학원 관리자가 학기별로 반, 교시, 과목별 시수, 강사, 강의실, 선택수업을 정의하고 다음 작업을 한 화면에서 수행한다.

1. 반별 주간 시간표를 수동으로 작성한다.
2. 수업 블록을 잠가 자동 편성에서 보호한다.
3. 아직 배정되지 않았거나 재배정이 허용된 수업을 자동 편성한다.
4. 강사·학생·반·강의실 충돌과 시수 미충족을 실시간 검증한다.
5. 생성된 배치안을 검토·수정하여 확정한다.
6. 강사별·반별·강의실별 시간표를 조회하고 출력한다.
7. 정규 반복 시간표와 날짜별 휴강·보강·모의고사를 별도로 관리한다.

### 1.2 주요 사용자

| 역할 | 권한 |
| --- | --- |
| 총괄 관리자 | 캠퍼스/학기 설정, 사용자 관리, 모든 초안 편집, 편성 실행, 확정·복원 |
| 시간표 담당자 | 기준정보 등록, 시간표 초안 편집, 자동 편성 실행, 검증, 출력 |
| 강사 | 본인 시간표 열람, 가능 시간 제출, 변경 요청 |
| 학생/학부모 | 본인 시간표 열람 (후속 버전) |

모든 쓰기 API는 서버에서 학원 소속 및 역할 권한을 검사한다.

### 1.3 우선 구현 범위(MVP)

- 교시표/학기/반/강사/과목/강의실 관리
- 반별 과목 시수 관리
- 주간 반복 시간표 수동 편집 및 잠금
- 충돌 검증과 저장
- 기본 자동 편성 및 미배치 사유
- 배치안 검토 및 게시(확정)
- 반별/강사별 보기와 인쇄

후속 확장: 학생별 선택수업, 특강·모의고사, 날짜별 예외 일정, 학부모 조회, 세밀한 알림·통계.

### 1.4 비목표

- 출결, 학원비 수납, 성적 분석을 첫 버전에 포함하지 않는다.
- 특정 학원의 내부 시수·강사 배정 규칙을 추정하여 기본값으로 강제하지 않는다.
- 자동 편성 결과를 검증 없이 즉시 운영 시간표에 반영하지 않는다.

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

## 5. 화면 설계

| 화면/경로(안) | 핵심 기능 |
| --- | --- |
| /dashboard | 전체 반/강사 수, 시수 미충족, 충돌, 최신 편성 작업 |
| /settings/terms | 학기·운영 기간·공휴일 기본 설정 |
| /settings/periods | 교시표 편집, 수업 가능 교시 및 공통 시간 설정 |
| /cohorts | 반 생성·계열·정원·담임·학생 명단 |
| /teachers | 강사/담당 과목/가능 교시/불가 교시 |
| /rooms | 강의실/정원/시설/사용 불가 시간 |
| /subjects/quotas | 반별 과목 시수, 연속 교시·요일 분산 조건 |
| /timetables/:id/editor | 주간 시간표 수동 편집·고정·복사·충돌 표시 |
| /timetables/:id/generate | 자동 편성 범위·우선순위·작업 상태 |
| /timetables/:id/review | 기존 안/자동 생성안 비교·미배치 진단·적용 |
| /timetables/:id/publish | 검증·게시/이력/복원 |
| /schedules | 반별·강사별·강의실별 시간표 조회/출력 |
| /exceptions | 날짜별 휴강/보강/모의고사 (후속) |

### 5.1 시간표 편집기 레이아웃

~~~text
┌────────────────────────────────────────────────────────────┐
│ 학기 · 시간표 버전    [반별][강사별][강의실별]   [검증][자동편성] │
├──────────────┬─────────────────────────────────────────────┤
│ 반 목록       │          월   화   수   목   금              │
│ 자연계 A      │ 1교시    국어 수학 영어 수학 국어              │
│ 자연계 B      │ 2교시    수학 영어 국어 영어 수학              │
│ 인문계 A      │ 3교시    영어 국어 수학 국어 탐구              │
│ ...           │ ...                                         │
├──────────────┴─────────────────────────────────────────────┤
│ 선택 교시: 과목 / 강사 / 강의실 / 유형 / 잠금 / 삭제          │
│ 미배치 시수 · 충돌 상세 · 실행 취소                            │
└────────────────────────────────────────────────────────────┘
~~~

편집 요구:
- 교시 클릭: 과목/강사/강의실 선택 및 배치
- 수업 드래그: 교시 이동, 필요 시 다른 강의실로 이동
- 잠금 토글: 자동 편성 보호
- 연속 교시 수업: 서로 연결된 블록으로 표시
- 충돌: 해당 셀과 원인을 함께 표시. 충돌을 숨기고 저장하는 기능은 제공하지 않는다.
- 반/강사/강의실 보기 모두 **하나의 배정 데이터**를 다르게 표시한다.
- 화면은 PC 우선, 모바일은 조회·간단 수정 우선
- 저장 전 미리보기와 이전 상태로 되돌리기(undo) 지원

## 6. 데이터 모델

### 6.1 핵심 엔터티

| 테이블 | 주요 필드 및 목적 |
| --- | --- |
| academies | id, name, timezone |
| users | id, academy_id, role, email, password_hash, status |
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
| generation_jobs | id, timetable_version_id, status, request_options, result_summary, created_by, started_at, finished_at |
| generation_proposals | id, job_id, entries_snapshot, validation_summary, score |
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
- 개인 정보는 필요한 범위만 수집하고 접근 권한·삭제 정책을 별도로 둔다.

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
  TIMETABLE_VERSIONS ||--o{ GENERATION_JOBS : requested_for
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
- VALIDATING: 서버 전체 충돌 검사 진행
- READY: 필수 조건 충족, 게시 가능
- PUBLISHED: 조회 대상이 되는 운영본, 직접 변경 금지
- ARCHIVED: 이전 게시본 기록 보관
- 동시 수정은 revision(낙관적 잠금)으로 감지한다.
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

### 8.1 기술 선택

- UI: React + TypeScript
- API/업무 로직: Python FastAPI
- DB: PostgreSQL (초기 로컬 개발은 SQLite 가능하나 운영은 PostgreSQL 권장)
- 제약 최적화: Google OR-Tools CP-SAT
- 작업 실행: 별도 백그라운드 워커/작업 큐 (고도화 단계)
- 배포: 프론트엔드, API, DB 분리

이미 Node.js 백엔드가 생기면 API를 유지하고 Python 편성 엔진만 독립 서비스로 둘 수 있다.

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
8. 결과 재검증 후 배치안(proposal) 저장
9. 관리자가 수동 조정하거나 제안안을 초안에 적용
10. 게시 전에 서버가 전체 조건을 재검사
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

## 9. API 설계(초안)

REST + JSON, 인증 및 academy scope 필수. 아래 엔드포인트는 구현 전 합의할 초안이다.

| 메서드 | 경로 | 설명 |
| --- | --- | --- |
| GET/POST | /api/terms | 학기 조회/생성 |
| GET/POST | /api/period-templates | 교시표 조회/생성 |
| GET/POST | /api/cohorts | 반 조회/생성 |
| GET/POST | /api/teachers | 강사 조회/생성 |
| GET/POST | /api/rooms | 강의실 조회/생성 |
| GET/PUT | /api/cohorts/{id}/quotas | 과목별 시수 조회/수정 |
| GET/POST | /api/timetables | 시간표 버전 조회/초안 생성 |
| GET | /api/timetables/{id} | 반/강사/실별 배정 조회 |
| POST | /api/timetables/{id}/entries | 수동 수업 배정 |
| PATCH/DELETE | /api/timetables/{id}/entries/{entryId} | 수업 수정·삭제 |
| POST | /api/timetables/{id}/validate | 전체 제약 검증 |
| POST | /api/timetables/{id}/generate | 자동 편성 작업 생성 |
| GET | /api/generation-jobs/{id} | 작업 상태/결과/배치안 |
| POST | /api/timetables/{id}/proposals/{proposalId}/apply | 배치안 초안 적용 |
| POST | /api/timetables/{id}/publish | 전체 검증 후 게시 |
| GET | /api/schedules | 반/강사/실 기준 시간표 조회 |
| GET | /api/timetables/{id}/export | 인쇄/PDF/엑셀 내보내기 |

자동 생성 요청 예시:

~~~json
{
  "mode": "UNLOCKED_AND_UNASSIGNED",
  "preserve_locked": true,
  "allow_partial": true,
  "weights": {
    "teacher_preference": 25,
    "cohort_preference": 25,
    "weekday_distribution": 15,
    "teacher_idle_gap": 15,
    "room_consistency": 10,
    "minimize_changes": 10
  },
  "expected_revision": 7
}
~~~

응답은 장시간 동기 요청이 아니라 작업 ID를 돌려준다.

~~~json
{
  "job_id": "job_001",
  "status": "PENDING",
  "timetable_version_id": "v1_draft"
}
~~~

**API 예외 규약**
- 400: 필드 유효성 오류
- 401/403: 인증 또는 권한 오류
- 404: 해당 캠퍼스 범위에서 미존재
- 409: revision 충돌/현재 상태에서 작업 불가
- 422: 의미적 제약 위반(예: 강사 중복/과목 시수 초과)
- 500: 예기치 못한 서버 오류

에러에는 machine-readable code, 사용자에게 보여줄 message, 충돌한 entry ID 및 권고 조치를 선택적으로 포함한다.

## 10. 시간표 검증 및 게시 정책

1. 편집 중에는 오류를 즉시 표시할 수 있으나 유효하지 않은 제안 상태는 운영본에 반영되지 않는다.
2. 저장 API는 기본 무결성 및 명백한 자원 중복을 검사한다.
3. 자동 편성 결과를 **원본이 아닌 제안안**으로 저장한다.
4. 제안안 적용 때 입력 시점의 revision과 현재 revision이 같은지 확인한다.
5. 게시 요청에는 전체 Hard Constraints, 필수 시수, 적용 기간을 재검증한다.
6. 통과한 경우 단일 트랜잭션으로 기존 운영본을 보관하고 새 버전을 PUBLISHED로 만든다.
7. 게시본 직접 편집을 차단하고 변경이 필요하면 새 DRAFT를 생성한다.
8. 모든 주요 변경과 게시 이력은 audit_logs에 남긴다.

동시 수정 시 오래된 화면의 변경으로 최신 시간표가 덮이지 않도록 낙관적 잠금(버전 필드 또는 ETag)을 사용한다.

## 11. 날짜별 예외와 자습

- **정규 반복 시간표**: 요일·교시별 기본 수업. term 기간 내 매주 반복.
- **특정 날짜 예외**: EXAM, CANCEL, SUBSTITUTE, MAKEUP, MOVE 등.
- **조회 규칙**: 특정 날짜의 시간표를 요청하면 정규 시간표를 복제한 가상 결과에 예외를 적용한다.
- **검증 규칙**: 보강·대체 수업도 강사/학생/강의실 자원 중복 검사 대상이다.
- **자습**: 별도 활동 유형이며 강의실 또는 자습실, 감독 강사 필요 여부를 설정한다.

선택수업은 반 전체 시간표에 단일 과목이 아니라 "선택수업 블록"으로 보여줄 수 있으며, 학생·선택그룹별 세부 시간표에서는 실제 선택 과목과 강의실을 표시한다.

## 12. 출력 및 조회

- 반별: 월~금 1~N교시, 과목명·강사명·강의실
- 강사별: 담당 반·과목·교시와 공강 표시
- 강의실별: 해당 공간의 점유 현황
- 학생별(후속): 정규반 + 선택수업 + 날짜별 예외 통합
- 출력: A4 가로 우선, PDF/엑셀, 출력일·적용 기간·버전 표시
- 비공개 초안은 관리자 권한에서만 조회
- 시간표를 공개할 때 학생 연락처 등 불필요한 개인정보는 포함하지 않음

## 13. 권장 프로젝트 구조

~~~text
academy-timetable/
├── README.md
├── docs/
│   └── DESIGN.md
├── frontend/                       # React + TypeScript (구현 예정)
│   └── src/
│       ├── pages/
│       ├── components/timetable/
│       ├── features/
│       └── api/
├── backend/                        # FastAPI (구현 예정)
│   └── app/
│       ├── api/
│       ├── models/
│       ├── schemas/
│       ├── services/
│       ├── scheduler/              # CP-SAT 편성 엔진
│       └── tests/
├── migrations/                     # DB 마이그레이션 (구현 예정)
└── docker-compose.yml              # 로컬 개발 환경 (구현 예정)
~~~

위 디렉터리는 **목표 구조 예시**이며, 실제 파일과 애플리케이션 구현을 완료했다는 뜻이 아니다.

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
8. **낙관적 잠금**: 오래된 revision 기반 수정/배치안 적용을 409로 거절한다.
9. **게시 원자성**: 게시 실패 시 기존 PUBLISHED 버전은 그대로 유지된다.
10. **날짜별 예외**: 하루만 휴강해도 다른 주 반복 시간표는 변경되지 않는다.
11. **권한 분리**: 강사·학생은 관리자 전용 편성/게시 API에 접근할 수 없다.
12. **시간 충돌 경계**: 한 수업의 종료와 다른 수업의 시작이 같으면 겹치지 않는다.

### 14.2 품질 및 보안

- 서버 측 데이터 검증, 역할 기반 권한, 캠퍼스별 데이터 격리
- 학생 개인정보 최소화, 비밀번호 해싱, 감사 로그
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
- **React/TypeScript + FastAPI + PostgreSQL + OR-Tools**를 신규 프로젝트의 기본 기술 후보로 사용

### 구현 전에 결정할 항목

- 실제 운영 캠퍼스의 교시 수 및 운영 요일
- 과목별 필수 시수와 반별 편차
- 한 교시에 여러 과목을 병행하는 이동수업의 세부 운영
- 자습실/감독 강사 배치 기준
- 강사별 일일 최대 강의 및 연속 강의 제한
- 외부 학생/학부모 조회 허용 범위
- 인쇄 레이아웃 및 파일 양식
- 자동 편성 성능 목표를 검증할 샘플 데이터 규모

## 16. 참고 자료

- [종로학원 공식 홈페이지](https://www.jongro.co.kr/) — 시간표 운영 구조의 참고 출처. 교시 구성은 캠퍼스·모집 과정·연도에 따라 변동될 수 있음.
- [Google OR-Tools CP-SAT](https://developers.google.com/optimization/cp/cp_solver)
- [FastAPI](https://fastapi.tiangolo.com/)
- [React](https://react.dev/)
- [PostgreSQL](https://www.postgresql.org/)

---

**문서 활용 안내:** 이 설계서를 기준으로 다음 작업은 (1) 실제 캠퍼스의 교시표·시수 결정, (2) DB 마이그레이션, (3) 수동 편집기, (4) 제약 검증, (5) 자동 편성 엔진 순서로 진행한다.
