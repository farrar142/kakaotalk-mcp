"""Central configuration for KakaoTalk MCP Server."""
import os

# KakaoTalk window class names
KAKAO_MAIN_WINDOW_CLASS = "EVA_Window_Dblclk"
KAKAO_MAIN_WINDOW_TITLE = "카카오톡"
KAKAO_CHAT_WINDOW_CLASS = "EVA_Window_Dblclk"
KAKAO_LIST_CONTROL_CLASS = "EVA_VH_ListControl_Dblclk"
KAKAO_EDIT_CLASS = "RICHEDIT50W"

# Win32 message constants
WM_SETTEXT = 0x000C
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
VK_RETURN = 0x0D
VK_CONTROL = 0x11
VK_ESCAPE = 0x1B
VK_A = 0x41
VK_C = 0x43
KEYEVENTF_KEYUP = 0x0002

# KakaoTalk data paths
KAKAO_LOCAL_DATA = os.path.join(
    os.environ.get("LOCALAPPDATA", ""),
    "Kakao", "KakaoTalk"
)
KAKAO_USERS_DIR = os.path.join(KAKAO_LOCAL_DATA, "users")

# Image cache subdirectories to monitor
IMAGE_CACHE_SUBDIRS = [
    "chat_data/cli_http_v2",
    "chat_data/cli/thumbnail",
    "chat_data/oci_v2",
    "chat_data/mci_v2",
]

# Timeouts and intervals
CLIPBOARD_MAX_RETRIES = 5
CLIPBOARD_RETRY_INTERVAL_SEC = 0.1
KEY_COMBO_WAIT_SEC = 0.15  # Was 0.3 — Ctrl+A/C combo wait
READ_SELECT_WAITS_SEC = (0.5, 1.0, 2.0, 3.0)  # Ctrl+A → Ctrl+C, longer each time until two copies agree

# Background read: Ctrl+A/C posted to the message list, the room is never brought to the front
BACKGROUND_READ = True
BACKGROUND_COPY_TIMEOUT_SEC = 3.0  # per copy, waiting for the clipboard to change
BACKGROUND_READ_ATTEMPTS = 4  # copies until two agree (a long selection may finish late)
BACKGROUND_CLICK_ATTEMPTS = 4  # posted clicks are now and then ignored; checked and retried
BACKGROUND_CLICK_RETRY_SEC = 1.5

# Link confirmation ("주의 … 이 링크에 연결할까요?"): untitled EVA_Window_Dblclk owned by the room
LINK_DIALOG_SIZE = (261, 180)  # at 100% display scale; measured 260x178 and 262x182 on two PCs
LINK_DIALOG_SIZE_TOLERANCE = 6  # px
LINK_DIALOG_TEMPLATE = "link_warning"  # its "주의" heading; a leave confirmation has the room name there

# Templates (templates.py): reference images matched by their dark pixels
TEMPLATE_INK_LUMA = 128  # darker than this counts as ink
TEMPLATE_MAX_SHIFT = 3  # px searched around the expected spot
TEMPLATE_MAX_MISMATCH = 0.4  # share of the template ink allowed to differ (other text scores ~1.0)

# Menus (EVA_Menu) driven by posted Down / Enter (screen.menu_select)
MENU_HIGHLIGHT_MIN_DIFF = 8  # gray-level change that marks the highlighted row
MENU_ROW_TOLERANCE = 8  # px between the highlighted row center and the target
MENU_MAX_ENTRIES = 12
MENU_KEY_WAIT_SEC = 1.0  # for the highlight to move after a key

# Window and focus timing
WINDOW_ACTIVATE_WAIT_SEC = 0.15  # Was 0.2 — after bring_window_to_front
EDIT_CLICK_WAIT_SEC = 0.08  # Was 0.1 — after clicking edit control
CLIPBOARD_PASTE_WAIT_SEC = 0.03  # Was 0.05 — after clipboard set, before Ctrl+V
AFTER_PASTE_WAIT_SEC = 0.05  # Was 0.1 — after Ctrl+V, before Enter

# Search and open room timing
SEARCH_ACTIVATE_WAIT_SEC = 0.3  # Was 0.5 — after Ctrl+F
SEARCH_CHAR_INTERVAL_SEC = 0.02  # Per-character typing delay
SEARCH_RESULTS_WAIT_SEC = 0.8  # Was 1.5 — wait for search results
SEARCH_OPEN_WAIT_SEC = 0.5  # Was 1.0 — after Enter to open room

# Image sending
SUPPORTED_IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp'}
IMAGE_CONFIRM_WAIT_SEC = 0.5  # Was 1.0 — dialog render wait
IMAGE_BETWEEN_SEND_WAIT_SEC = 1.0  # Was 1.5 — between multiple images
IMAGE_FOCUS_WAIT_SEC = 0.2  # Was 0.3 — after bring_window_to_front for image
IMAGE_SET_FOCUS_WAIT_SEC = 0.2  # Was 0.3 — after SetFocus on edit
IMAGE_DIALOG_POLL_INTERVAL_SEC = 0.15  # Was 0.2 — dialog poll interval
IMAGE_AFTER_CONFIRM_WAIT_SEC = 0.3  # Was 0.5 — after Enter on dialog

# Mention timing
MENTION_FOCUS_WAIT_SEC = 0.2  # Was 0.3 — after bring to front
MENTION_CLICK_WAIT_SEC = 0.15  # Was 0.2 — after clicking edit
MENTION_AT_WAIT_SEC = 0.5  # Was 0.8 — after typing @
MENTION_NAME_WAIT_SEC = 0.6  # Was 1.0 — after typing name
MENTION_SELECT_WAIT_SEC = 0.3  # Was 0.5 — after Enter to select
MENTION_PASTE_WAIT_SEC = 0.2  # Was 0.3 — after Ctrl+V
MENTION_SEND_WAIT_SEC = 0.3  # Was 0.5 — after final Enter

# Open chat (window-relative pixels, KakaoTalk PC 26.9 at 100% display scale; screen.px scales them)
MAIN_CHAT_TAB_POS = (32, 118)  # left sidebar chat tab
MAIN_OPENCHAT_ICON_OFFSET = (72, 57)  # open-chat icon: (from right edge, y)
OPENCHAT_BACK_POS = (28, 47)  # back arrow in search view
OPENCHAT_THUMB_WIDTH = 110  # thumbnail column cropped off result rows before OCR
OPENCHAT_TITLE_MAX_LUMA = 80  # title text is near-black, descriptions are gray
OPENCHAT_OCR_SCALE = 3.0
OPENCHAT_ITEM_CLICK_X = 150
OPENCHAT_SCROLL_NOTCHES = 3
OPENCHAT_RESULTS_WAIT_SEC = 1.0
OPENCHAT_PREVIEW_BUTTON_FROM_BOTTOM = 41  # "오픈채팅 참여하기" button
PROFILE_RANDOM_RADIO_POS = (268, 155)  # "프로필 설정" random-nickname radio
PROFILE_CONFIRM_FROM_CENTER = 14  # "확인" sits left of the dialog center
DIALOG_BUTTON_FROM_BOTTOM = 41
ROOM_MENU_ICON_OFFSET = (22, 57)  # chat room ≡ menu: (from right edge, y)
FORM_OPTION_CHECK_X = 32  # radio/checkbox column on the create form
FORM_CONFIRM_FROM_CENTER = 69  # "확인" sits right of the form center
FORM_CANCEL_FROM_RIGHT = 62
LEAVE_ACK_CHECK_OFFSET = 20  # owner-leave checkbox sits left of its label

# Room board (톡게시판) window
BOARD_BACK_POS = (28, 47)  # ← in 상세보기
BOARD_TAB_Y = 90
BOARD_TAB_X = {"공지": 34, "일정": 80, "투표": 126, "퀴즈": 172}
BOARD_LIST_TOP = 110  # list viewport starts below the tabs
BOARD_THUMB_WIDTH = 75  # thumbnail column cropped off before OCR
BOARD_META_MIN_LUMA = 90  # meta lines are gray (~118), titles near-black
BOARD_TITLE_GAP = 25  # px between lines that still belong to one title
BOARD_SCROLL_NOTCHES = 3
BOARD_NAV_WAIT_SEC = 0.8

# Chat room ≡ menu (EVA_Menu) layouts, told apart by the menu's size at 100% scale:
# entry -> its row center in px above the menu's bottom edge. Measured on KakaoTalk
# PC 26.9 with posted Down keys. A menu of any other size is not used.
ROOM_MENU_LAYOUTS = {
    (225, 298): {"톡게시판": 189, "채팅방 나가기": 52},  # 1:1 room (8 entries)
    (225, 324): {"톡게시판": 189, "채팅방 나가기": 52},  # group room (+ "채팅방 다시 만들기" on top)
    # open chat as its owner (9 entries + icon bar): URL 복사 / 서랍 / 톡게시판 / 입장·퇴장 표시 /
    # 오픈채팅 관리 / 커버 보기 / 챗봇 / 대화 내용 / 나가기
    (179, 335): {"채팅방 URL 복사": 315, "톡게시판": 252, "채팅방 나가기": 52},
}
ROOM_MENU_SIZE_TOLERANCE = 4

# Default output directory for downloaded images
DEFAULT_IMAGE_OUTPUT_DIR = os.path.join(
    os.environ.get("USERPROFILE", ""),
    "Documents", "KakaoMCP_Images"
)
