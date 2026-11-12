# 접근성 트리(UI Automation)로 카카오톡 읽기 — 조사 결과

카카오톡 PC 26.9.1.5339, Windows 11에서 확인. 다시 확인할 때는 `scripts\probe_accessibility.ps1`을 실행한다
(이름·메시지 내용은 출력하지 않고 구조와 이름 길이만 보여 줌).

## 결론

메시지 읽기·채팅방 목록·보낸 사람/시간 파싱·이전 메시지 불러오기는 접근성 트리로 옮길 수 없다.
카카오톡 화면은 자체 프레임워크(EVA)가 직접 그리고, 목록 컨트롤이 항목을 접근성 트리에 내놓지 않는다.
그래서 지금 방식(Win32 창 찾기 + Ctrl+A/Ctrl+C 복사 + 일부 OCR)을 유지한다.

## 트리에 보이는 것

| 화면 요소 | 클래스 | UIA에서 보이는 것 |
|---|---|---|
| 채팅방 창 | `EVA_Window_Dblclk` | 창 하나(이름 = 방 이름). Win32 `GetWindowText`와 같음 |
| 메시지 목록 | `EVA_VH_ListControl_Dblclk` | 자식 없음, 이름 없음, 지원 패턴 없음 |
| 입력창 | `RICHEDIT50W` | Value·Text 패턴 지원 |
| 메인 창 채팅 목록 | `EVA_VH_ListControl_Dblclk` | 자식 없음 (컨트롤 이름만 있음) |
| 메인 창 검색칸 | `Edit` | 일반 Win32 Edit |

UIA는 네이티브 창에 MSAA 프록시를 붙여 보여 주므로, 위 결과는 MSAA(IAccessible) 쪽도 비어 있다는 뜻이다.
시스템의 "화면 읽기 프로그램 사용 중" 플래그(`SPI_SETSCREENREADER`)를 켜고 다시 봐도 달라지지 않았다.

창 전체를 깊이 제한 없이 훑어도 Table·List·ListItem·DataItem 요소는 하나도 없고, 메시지 목록의 자손은 스크롤바 하나뿐이다.
트리에 있는 Text·Hyperlink·Image 요소는 모두 메인 창 광고 배너(Chromium 웹뷰) 안의 것이다.

### macOS 카카오톡과의 차이

[kakaotalk-ax](https://github.com/HyunSeob/kakaotalk-ax)는 **맥용 카카오톡**(`com.kakao.KakaoTalkMac`)을 macOS AX API로 읽는다
(Swift 브리지, 손쉬운 사용 권한 필요). 메시지는 `AXTable` → `AXRows` → `AXRow`/`AXCell` → `AXStaticText`의 `AXValue`에서 꺼내고,
입력창은 `AXTextArea`(설명 "메시지 입력"), 이전 대화는 `AXVerticalScrollBar`의 `AXValue`를 바꿔 불러온다.
맥 앱은 네이티브 Cocoa 테이블이라 이 트리가 있지만, Windows PC 카카오톡은 다른 프로그램(EVA 프레임워크)이라
같은 역할(UIA Table/DataItem/Text)의 요소가 없다. 이 방식은 맥에서만 통한다.

## 입력창

입력창은 트리에서 보이고, `EM_REPLACESEL`(UIA ValuePattern과 같은 효과)로 창을 앞으로 가져오지 않고도
한글·기호를 그대로 넣을 수 있다. 하지만 이렇게 넣은 글은 Enter를 눌러도 **보내지지 않는다**
(카카오톡이 자기 키 입력/붙여넣기 처리로 들어온 글만 보냄). 그래서 전송은 클립보드 붙여넣기(Ctrl+V)를 유지한다.
입력창 내용 확인(`WM_GETTEXT`)은 이미 쓰고 있다.

## 앞으로

카카오톡 업데이트 뒤 `probe_accessibility.ps1`에서 메시지 목록 아래에 `ListItem`/`Text` 자식이 나타나면,
그때 읽기를 트리 기반으로 바꾸고 지금 방식을 대체 경로로 남긴다.
