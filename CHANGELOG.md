# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- 대화 기록 DB (SQLite, `history.db`): `kakao_history_record` / `kakao_history_stop` / `kakao_history_status` / `kakao_history_search`
  - 방별 주기 수집(최소 60초), 기록 대상은 DB에 남아 서버 재시작 후 이어서 수집
  - 날짜·기간·키워드·보낸 사람·최근 N건 검색
  - `kakao_read_messages`와 키워드 모니터가 읽은 메시지도 저장
- `kakao_read_board` — 톡게시판(공지 / 일정 / 투표 / 퀴즈) 글 목록과 본문 읽기
- `kakao_openchat_join`의 `accept_safebot` — "세이프봇 적용 동의" 창을 "동의하고 참여"로 넘김 (기본은 "취소" 후 중단)

### Changed
- 메시지에 `date`(YYYY-MM-DD)와 `time24`(HH:MM) 추가. 카카오톡 26.x 복사 형식(레코드는 CRLF, 메시지 안 줄바꿈은 LF)을 구분해
  입장/퇴장 같은 시스템 줄이 앞 메시지 본문에 붙지 않고 `system`으로 분리됨
- 모든 UI 조작 도구와 백그라운드 수집이 하나의 잠금(`UI_LOCK`)을 공유

### Fixed
- 다른 방의 대화가 엉뚱한 방 이름으로 저장되던 문제: 클립보드와 포커스는 프로세스 사이에 공유되는데 UI 잠금은 프로세스 안에서만
  걸려, 다른 프로세스가 동시에 대화를 복사하면 섞였음
  - UI 잠금에 이름 있는 뮤텍스(`Local\kakaotalk-mcp-ui`)를 더해 다른 서버/스크립트와도 순서대로 실행
  - 복사 직후 그 방 창이 여전히 앞에 있는지 확인하고, 아니면 복사 내용을 버림
  - 저장 전 검사: 최근 메시지가 이 방에는 하나도 없고 다른 한 방에 절반 이상 저장돼 있으면 저장하지 않고 `rejected`로 알림
- 메시지 읽기(기록 수집·`kakao_read_messages`·모니터)가 메시지 목록 한가운데를 클릭해 포커스를 잡다가 링크를 눌러
  "주의 … 이 링크에 연결할까요?" 확인 창이나 브라우저가 뜨던 문제: 이제 목록을 클릭하지 않고 키보드 포커스만 옮김(SetFocus)
- 링크가 열려도 복구: 작업 전후 창을 비교해 새 브라우저 창(WM_CLOSE)·새 탭(Ctrl+W)·카톡 웹뷰·링크 확인 창("취소")을 닫고
  원래 창으로 포커스를 돌림. 읽기 전에는 방에 남아 있던 링크 확인 창도 "취소"로 닫음(이 모달 때문에 방이 앞으로 오지 못해
  수집이 계속 실패하던 원인). 닫은 내역은 도구 결과 `link_warnings`와 `kakao_history_status`의 `link_events`에 남음
- 불러온 대화가 많은 방에서 전체 선택이 끝나기 전에 복사해 아무것도 복사되지 않던 문제(선택 대기를 늘려 재시도)
- 참여 중 예상하지 못한 창이 뜨거나 실패하면 남은 창을 "취소"(없으면 WM_CLOSE)로 닫고 미리보기도 닫음 (남은 창이 포커스를 잡아 다음 조작이 실패하던 문제)
- 톡게시판 창이 채팅방과 같은 제목이라 `find_chat_window` / `kakao_list_open_rooms`가 게시판 창을 채팅방으로 잡던 문제
- `kakao_openchat_join`이 커뮤니티 방의 "커뮤니티 시작하기" 동의 창(메시지 공개·90일 보관)에서 멈추던 문제
  - `accept_community=true`면 "동의", 아니면 "취소" 후 미리보기를 닫고 동의가 필요하다는 오류를 반환
  - 미리보기 위에 뜬 그 밖의 제목 있는 창은 무시하지 않고 내용을 담아 오류로 보고
  - 실패 정리 시 미리보기가 띄운 모달을 먼저 닫음 (모달이 있으면 미리보기 WM_CLOSE가 무시됨)

## [0.2.0] - 2026-03-22

### Added
- `kakao_send_bulk` — 여러 채팅방에 동일 메시지를 한 번에 전송하는 일괄 전송 도구
  - `room_names` 리스트로 다수 채팅방 지정
  - `interval_sec` 파라미터로 방 간 전송 간격 조절 (기본 0.5초, 최소 0.3초)
  - 이미 열린 창은 재검색 없이 재활용하여 속도 향상
  - 개별 전송 결과를 room별로 반환
- `kakao_send_image` — 채팅방에 이미지 파일 전송 (CF_HDROP 클립보드 + Ctrl+V 방식)
  - JPG, PNG, GIF, BMP, WebP 형식 지원
  - 단일 또는 다수 이미지 순차 전송 지원
  - 카카오톡 전송 확인 다이얼로그 자동 처리

### Changed
- **타이밍 최적화**: 모든 하드코딩된 `time.sleep()` 값을 `config.py` 상수로 중앙 관리화
  - 채팅방 검색+열기: ~3.0초 → ~1.6초 (약 47% 단축)
  - 메시지 전송: ~0.35초 → ~0.16초 (약 54% 단축)
  - 3개 채팅방 전송 총합: ~10초 → ~5초 (약 50% 단축)
- `config.py`에 카테고리별 타이밍 상수 추가 (Window, Search, Image, Mention)
- `controller.py` 내 모든 `time.sleep()` 호출을 `config.상수`로 교체

## [0.1.0] - 2025-02-27

### Added

#### 기본 도구 (8개)
- `kakao_health_check` — 카카오톡 PC 실행 상태 확인 (윈도우 핸들, PID)
- `kakao_list_open_rooms` — 열려있는 채팅방 목록 조회
- `kakao_open_room` — 채팅방 검색 및 열기 (이미 열려있으면 포그라운드로)
- `kakao_send_message` — 채팅방에 메시지 전송 (클립보드 기반)
- `kakao_send_mention` — @멘션과 함께 메시지 전송 (한글 2벌식 키보드 시뮬레이션)
- `kakao_read_messages` — 채팅방 메시지 읽기 (Ctrl+A, Ctrl+C 클립보드 복사)
- `kakao_extract_links` — 채팅방에서 공유된 URL 추출
- `kakao_download_images` — 카카오톡 로컬 캐시에서 최근 이미지 다운로드

#### 모니터링 도구 (3개)
- `kakao_start_monitor` — 채팅방 키워드 모니터링 시작 (백그라운드 스레드)
- `kakao_stop_monitor` — 모니터링 중지
- `kakao_get_monitor_events` — 감지된 키워드 이벤트 조회 (트리거 메시지 + 최근 컨텍스트)

#### 인프라
- Win32 API 기반 카카오톡 PC 자동화 (`controller.py`)
- 카카오톡 클립보드 텍스트 파서 (`parser.py`)
- 한글 2벌식 자판 분해 및 키 입력 시뮬레이션 (초성/중성/종성 + 복합 자모)
- `pyproject.toml` 기반 패키지 구성 (`uvx kakaotalk-mcp` 실행 지원)
- 파서 단위 테스트 및 컨트롤러 mock 테스트 (28개)

### Fixed
- Windows 11에서 `SetForegroundWindow` 예외 처리
- 채팅방 검색 시 기존 검색어 잔류 문제 (ESC로 초기화)
- 메시지 전송 시 클립보드 충돌 방지 (`WM_SETTEXT` → 클립보드 `Ctrl+V` 방식)

[0.2.0]: https://github.com/kronenz/kakaotalk-mcp/releases/tag/v0.2.0
[0.1.0]: https://github.com/kronenz/kakaotalk-mcp/releases/tag/v0.1.0
