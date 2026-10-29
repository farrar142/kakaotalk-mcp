# KakaoTalk MCP Server

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Windows](https://img.shields.io/badge/platform-Windows-0078d4.svg)](https://www.microsoft.com/windows)

> 이 저장소는 [kronenz/kakaotalk-mcp](https://github.com/kronenz/kakaotalk-mcp)(MIT)를 포크해
> 오픈채팅(검색·참여·만들기·나가기), 대화 기록 DB, 톡게시판 읽기, 원격 접속용 OAuth 2.1 인가 서버,
> 링크 오클릭 방지 등을 더한 확장판입니다. 원본의 저작권 표시와 라이선스는 [LICENSE](LICENSE)에 그대로 두었습니다.

카카오톡 PC를 Win32 API로 제어하는 [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) 서버입니다.

Claude Desktop, Claude Code 등 MCP 클라이언트에서 카카오톡 메시지를 보내고, 읽고, 채팅방을 관리할 수 있습니다.

## 주요 기능

### 기본 도구

| 도구 | 설명 |
|------|------|
| `kakao_health_check` | 카카오톡 PC 실행 상태 확인 |
| `kakao_list_open_rooms` | 열려있는 채팅방 목록 조회 |
| `kakao_open_room` | 채팅방 검색 및 열기 |
| `kakao_send_message` | 채팅방에 메시지 전송 |
| `kakao_send_bulk` | 여러 채팅방에 동일 메시지 일괄 전송 |
| `kakao_send_mention` | @멘션과 함께 메시지 전송 |
| `kakao_read_messages` | 채팅방 메시지 읽기 (날짜·24시간 시각 포함, 읽은 내용은 대화 기록 DB에도 저장) |
| `kakao_extract_links` | 채팅방에서 공유된 URL 추출 |
| `kakao_send_image` | 채팅방에 이미지 파일 전송 |
| `kakao_download_images` | 카카오톡 캐시에서 최근 이미지 다운로드 |

### 오픈채팅 도구

| 도구 | 설명 |
|------|------|
| `kakao_openchat_search` | 오픈채팅방 검색 (이름/소개/태그, OCR로 결과 읽기) |
| `kakao_openchat_join` | 검색 결과의 오픈채팅방 참여 (카카오 프로필 / 랜덤 닉네임 / 지정 닉네임 오픈프로필, 참여 코드). 커뮤니티 방의 "커뮤니티 시작하기"는 `accept_community=true`, "세이프봇 적용 동의"는 `accept_safebot=true`일 때만 수락, 아니면 취소 후 중단 |
| `kakao_openchat_create` | 그룹 오픈채팅방 만들기 (이름, 소개, 주제, 검색 허용 등) |
| `kakao_leave_room` | 채팅방 나가기 (`confirm=true` 필요) |
| `kakao_get_room_link` | 오픈채팅방 공유 URL 가져오기 |

참여한 오픈채팅방은 일반 채팅방과 같은 창이므로 `kakao_send_message`, `kakao_read_messages` 등을 그대로 사용합니다.

오픈채팅 목록·메뉴는 카카오톡이 직접 그리는 화면이라 Windows 내장 OCR(한국어)로 읽습니다. 제목에 약간의 인식 오류가 있을 수 있으며, 참여/선택은 유사도 매칭으로 처리합니다. 좌표는 카카오톡 PC 26.9, 디스플레이 배율 100% 기준입니다.

### 대화 기록 · 게시판 도구

| 도구 | 설명 |
|------|------|
| `kakao_history_record` | 채팅방 대화를 SQLite DB에 기록 (지금 한 번 + 주기적으로, 서버 재시작 후에도 계속) |
| `kakao_history_stop` | 기록 중지 (저장된 내용은 유지) |
| `kakao_history_status` | 기록 중인 방, 마지막 수집 시각·오류, 방별 저장 건수 |
| `kakao_history_search` | 저장된 대화 검색: 방, 날짜(`date` / `date_from`~`date_to`), 키워드, 보낸 사람, 최근 N건(`limit`) |
| `kakao_read_board` | 톡게시판 글 읽기 (공지 / 일정 / 투표 / 퀴즈 탭, 제목·작성자·작성일·댓글 수·본문) |

대화 기록은 `%LOCALAPPDATA%\kakaotalk-mcp\history.db`에 저장됩니다. 카카오톡이 메시지 ID를 주지 않으므로
(방, 날짜, 시각, 보낸 사람, 내용, 같은 분 안에서 같은 내용의 순번)으로 같은 메시지를 판별해 중복 저장하지 않습니다.
한 번의 수집은 채팅방 창에 불러와진 메시지만 복사하므로, 대화가 많은 방은 수집 간격을 짧게 두세요.
게시판 목록의 제목·날짜는 OCR로 읽고(약간의 인식 오류 가능), 본문은 상세보기에서 복사해 정확합니다. 댓글 내용은 읽지 않습니다.

### 모니터링 도구

| 도구 | 설명 |
|------|------|
| `kakao_start_monitor` | 채팅방 키워드 모니터링 시작 |
| `kakao_stop_monitor` | 모니터링 중지 |
| `kakao_get_monitor_events` | 감지된 키워드 이벤트 조회 |

## 요구사항

- **Windows 10/11** (Win32 API 기반이므로 Windows 전용)
- **카카오톡 PC** 설치 및 로그인 상태
- **Python 3.10** 이상

## 설치

> PyPI의 `kakaotalk-mcp` 패키지(`uvx kakaotalk-mcp`, `pip install kakaotalk-mcp`)는 **원본** 버전이라
> 이 저장소의 확장 기능이 없습니다. 이 버전은 아래처럼 GitHub에서 설치하세요.

### uvx (권장)

별도 설치 없이 바로 실행:

```bash
uvx --from git+https://github.com/farrar142/kakaotalk-mcp kakaotalk-mcp
```

### pip

```bash
pip install git+https://github.com/farrar142/kakaotalk-mcp
```

### 소스에서 설치

```bash
git clone https://github.com/farrar142/kakaotalk-mcp.git
cd kakaotalk-mcp
pip install -e .
```

## 설정

### Claude Desktop

`%APPDATA%\Claude\claude_desktop_config.json` 파일에 추가:

**uvx 사용 시:**

```json
{
  "mcpServers": {
    "kakao": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/farrar142/kakaotalk-mcp", "kakaotalk-mcp"]
    }
  }
}
```

**pip 설치 후:**

```json
{
  "mcpServers": {
    "kakao": {
      "command": "kakaotalk-mcp"
    }
  }
}
```

**소스에서 직접 실행:**

```json
{
  "mcpServers": {
    "kakao": {
      "command": "python",
      "args": ["C:/경로/kakaotalk-mcp/src/kakao_mcp/server.py"],
      "env": {
        "PYTHONPATH": "C:/경로/kakaotalk-mcp/src"
      }
    }
  }
}
```

### Claude Code

Claude Code 설정에서 MCP 서버 추가:

```bash
claude mcp add kakao -- uvx --from git+https://github.com/farrar142/kakaotalk-mcp kakaotalk-mcp
```

또는 `.claude/settings.json`에 직접 추가:

```json
{
  "mcpServers": {
    "kakao": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/farrar142/kakaotalk-mcp", "kakaotalk-mcp"]
    }
  }
}
```

### 원격 실행 (VM 등)

UI 자동화는 로그인된 데스크톱 세션에서만 동작하므로, 카카오톡이 있는 PC(VM)의 사용자 세션에서 HTTP 모드로 실행하고 다른 PC에서 접속합니다. SSH나 서비스로 실행하면 카카오톡 창에 접근할 수 없습니다.

```bash
kakaotalk-mcp --transport streamable-http --host 0.0.0.0 --port 8765
```

```bash
claude mcp add --transport http kakao http://<VM-IP>:8765/mcp
```

`--host`가 localhost가 아니면 DNS 리바인딩 보호가 꺼지므로, 방화벽으로 접근 가능한 주소를 제한하세요.

로그온 시 자동 실행(시작프로그램 폴더, 관리자 권한 불필요, 종료되면 5초 후 재시작):

```bash
powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
```

로그는 `%LOCALAPPDATA%\kakaotalk-mcp\server.log`, 해제는 `-Uninstall`.

### 공개 접속 (Claude 커스텀 커넥터, OAuth 2.1)

리버스 프록시(예: Nginx Proxy Manager)로 HTTPS 도메인에 연결하고 OAuth를 켜면 claude.ai 커스텀 커넥터로 연결할 수 있습니다. 설계는 [docs/remote-auth.md](docs/remote-auth.md)를 참고하세요.

```bash
kakaotalk-mcp auth init --public-url https://kakao-mcp.example.com --trusted-proxy <NPM IP> --extra-host "192.168.1.20:*"
```

비밀번호를 정하고, 출력되는 TOTP 시크릿을 인증 앱(Google Authenticator 등)에 등록합니다. `%LOCALAPPDATA%\kakaotalk-mcp\auth.toml`이 생기면 HTTP 모드에서 인증이 자동으로 켜집니다(서버 재시작 필요).

- claude.ai: 설정 → 커넥터 → 커스텀 커넥터 추가 → `https://kakao-mcp.example.com/mcp` → 로그인/동의 화면에서 비밀번호, 인증 코드, 허용할 권한 선택
- Claude Code (토큰 방식):

```bash
kakaotalk-mcp token create --name main-pc --scopes kakao.read,kakao.send
```

```bash
claude mcp add --transport http kakao https://kakao-mcp.example.com/mcp --header "Authorization: Bearer <토큰>"
```

권한(스코프): `kakao.read`(읽기), `kakao.send`(보내기), `kakao.manage`(오픈채팅 참여/만들기/나가기). 긴급 차단은 `kakaotalk-mcp token revoke --all`. 도구 호출은 `%LOCALAPPDATA%\kakaotalk-mcp\audit.log`에 기록됩니다.

## 사용 예시

Claude에게 자연어로 요청하면 됩니다:

- "카카오톡 실행 중인지 확인해줘"
- "열린 채팅방 목록 보여줘"
- "홍길동 채팅방 열어줘"
- "홍길동에게 '회의 10분 후에 시작합니다' 보내줘"
- "홍길동에게 @멘션으로 '확인 부탁드립니다' 보내줘"
- "홍길동 채팅방 최근 대화 읽어줘"
- "홍길동 채팅방에서 공유된 링크 추출해줘"
- "이 이미지를 홍길동에게 보내줘: C:\Users\사용자\Pictures\photo.jpg"
- "최근 카카오톡 이미지 다운로드해줘"
- "홍길동, 김철수, 이영희에게 '내일 회의 참석 부탁드립니다' 보내줘"
- "공학자들 채팅방에서 '회의', '점심' 키워드를 모니터링하고 감지되면 답장해줘"
- "모니터링 중지해줘"
- "'파이썬' 오픈채팅방 검색해줘"
- "검색 결과 두 번째 방에 랜덤 닉네임으로 참여해줘"
- "샌드코프 테스트 방에 '파라' 닉네임으로 참여해줘"
- "'샌드코프 테스트' 방에 '안녕하세요' 보내고 공유 링크 알려줘"
- "'스터디 모임' 오픈채팅방 만들어줘, 주제는 자기계발"
- "'샌드코프 테스트' 방에서 나가줘"

## 제한사항 및 주의사항

- **Windows 전용**: Win32 API를 사용하므로 macOS/Linux에서는 동작하지 않습니다.
- **포그라운드 필요**: 메시지 읽기(`kakao_read_messages`), 채팅방 열기(`kakao_open_room`), 멘션 전송(`kakao_send_mention`) 시 카카오톡 창이 잠시 최전면으로 올라옵니다.
- **멘션(@) 기능**: `kakao_send_mention`은 키보드 시뮬레이션으로 @멘션 팝업을 활성화합니다. 한글 2벌식 자판 입력을 사용하므로 시스템 키보드 레이아웃이 한글이어야 합니다.
- **클립보드 사용**: 메시지 읽기/전송 시 시스템 클립보드를 사용합니다. 작업 중 클립보드 내용이 변경될 수 있습니다.
- **채팅방 이름 정확히 입력**: `kakao_send_message`, `kakao_read_messages`는 채팅방 창 제목이 정확히 일치해야 합니다. 먼저 `kakao_list_open_rooms`로 정확한 이름을 확인하세요.
- **이미지 전송**: `kakao_send_image`는 파일을 클립보드에 복사한 후 Ctrl+V로 붙여넣는 방식입니다. 전송 확인 다이얼로그가 자동으로 처리됩니다. JPG, PNG, GIF, BMP, WebP 형식을 지원합니다.
- **이미지 다운로드**: 카카오톡 로컬 캐시에서 가져오며, 채팅방별 구분 없이 최근 캐시된 이미지가 다운로드됩니다.
- **대화 기록**: `kakao_history_record`는 수집할 때마다 채팅방 창을 잠시 최전면으로 올립니다(최소 간격 60초). 창이 닫혀 있으면 검색으로 다시 엽니다. 모든 UI 조작은 하나의 잠금으로 순서대로 실행되어 수집이 다른 도구 호출과 섞이지 않습니다.
- **링크 보호**: 메시지 목록은 클릭하지 않고 키보드로만 다룹니다. 그래도 작업 중 브라우저 창·탭, 카톡 링크 미리보기, "이 링크에 연결할까요?" 확인 창이 뜨면 자동으로 닫고 원래 창으로 돌아가며, 결과의 `link_warnings`와 `kakao_history_status`의 `link_events`에 남깁니다. 작업하는 몇 초 사이에 직접 연 브라우저 창도 닫힐 수 있습니다.
- **모니터링 기능**: `kakao_start_monitor`는 백그라운드에서 채팅방을 주기적으로 폴링합니다. 폴링 시마다 카카오톡 창이 잠시 최전면으로 올라오며, 최소 폴링 간격은 3초입니다.

## 로드맵

### v0.2.0 — 서버 사이드 자동 응답 (예정)

클라이언트 폴링 방식의 토큰 비효율 문제를 해결하기 위해, MCP 서버 내부에서 채팅 감지 + AI 답장 생성 + 전송을 처리하는 기능을 추가할 예정입니다.

| 도구 | 설명 |
|------|------|
| `kakao_start_auto_reply` | AI 자동 응답 모니터링 시작 (서버 사이드) |
| `kakao_stop_auto_reply` | 자동 응답 중지 |
| `kakao_get_auto_reply_log` | 자동 응답 이력 조회 |

**핵심 개선:**
- 새 메시지 감지는 서버 내부 hash 비교로 처리 (토큰 0)
- AI 답장이 필요할 때만 Claude API를 최소 컨텍스트(최근 10개 메시지)로 호출
- 클라이언트 폴링 대비 **토큰 ~99% 절감**

## 프로젝트 구조

```
kakaotalk-mcp/
├── pyproject.toml
├── README.md
├── CHANGELOG.md
├── LICENSE
├── requirements.txt
├── src/
│   └── kakao_mcp/
│       ├── __init__.py
│       ├── __main__.py      # python -m kakao_mcp 지원
│       ├── server.py        # MCP 서버 + 13개 도구 정의
│       ├── controller.py    # Win32 API 래퍼
│       ├── openchat.py      # 오픈채팅 검색/참여/만들기/나가기
│       ├── ocr.py           # 화면 캡처 + Windows OCR
│       ├── parser.py        # 클립보드 텍스트 파싱
│       └── config.py        # 상수 및 설정
└── tests/
    ├── test_parser.py       # 파서 단위 테스트
    └── test_controller.py   # 컨트롤러 mock 테스트
```

## 라이선스

[MIT License](LICENSE)
