# Academy Timetable — 개발 초기 버전

[원본 설계 저장소](https://github.com/ljwoo8942/academy-timetable)의 설계를 참고해 만드는 오프라인 Python 데스크톱 프로그램입니다. 기준 문서: `98d86188d08440d3685c3122c7b883fff381f71d`의 [상세 설계](docs/DESIGN.md)와 [원본 README](docs/REFERENCE_README.md).

현재는 **첫 구현 단계**입니다. 학기, 학기별 반, 강사, 과목, 강의실의 이름을 관리하고 새 학기에 기본 11교시를 생성합니다. 학기별 교시 시각은 월~금 공통으로 수정할 수 있습니다. 과목은 기록 보존을 위해 삭제 대신 활성 상태를 변경합니다. 학기 삭제 시 그 학기의 반과 교시표도 함께 삭제됩니다.

시간표 편성, 충돌 검증, 자동 편성, 과목별 시수, 강사 가능 시간, 엑셀/PDF 출력, 백업 및 설치형 패키지는 아직 구현되지 않았습니다. 실제 운영용으로 사용하기에는 이릅니다.

## 개발 환경 실행

Python 3.9 이상과 인터넷 연결(최초 의존성 설치 시)이 필요합니다. 이후 프로그램은 로컬에서 동작합니다.

macOS/Linux:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python -m academy_timetable
```

Windows PowerShell:

```powershell
py -m venv .venv
.venv\Scripts\python -m pip install -e .
.venv\Scripts\python -m academy_timetable
```

SQLite 파일은 Qt의 사용자별 앱 데이터 디렉터리에 저장됩니다. 개발 테스트: `python -m unittest discover -s tests` (패키지 설치 후).
