import re


SUPPORTED_LANGUAGES = {"ko", "en"}

STATIC_EN = {
    "서버 안에서만 사용할 수 있습니다.": "This command can only be used in a server.",
    "이 명령어는 서버 관리자만 사용할 수 있습니다.": "This command is available to server administrators only.",
    "이 명령어를 사용할 권한이 없습니다.": "You do not have permission to use this command.",
    "입력값 형식을 확인해 주세요. 채널은 목록에서 선택하거나 채널 이름을 입력해 주세요.": "Check the input format. Select a channel from the list or enter its name.",
    "요청을 처리하지 못했습니다.": "The request could not be processed.",
    "요청 처리 중 오류가 발생했습니다. 관리자에게 문의하세요.": "The command failed. Please contact a server administrator.",
    "작업을 완료하지 못했습니다. 관리자에게 문의하세요.": "The action could not be completed. Contact a server administrator.",
    "메뉴를 열지 못했습니다. 다시 시도하거나 관리자에게 문의하세요.": "Could not open the menu. Try again or contact a server administrator.",
    "데이터베이스 문제로 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.": "The request could not be processed because of a database issue. Please try again later.",
    "Unsupported language.": "Unsupported language.",
    "상장 종목이 없습니다.": "There are no listed stocks.",
    "상장 폐지된 종목입니다.": "This stock has been delisted.",
    "해당 이름의 활성 주식을 찾을 수 없습니다.": "No active stock with that name was found.",
    "활성 재화가 없습니다.": "There are no active currencies.",
    "보유 중인 가상주식이 없습니다.": "You do not hold any virtual stocks.",
    "대출 내역이 없습니다.": "You have no loan history.",
    "거래 내역이 없습니다.": "You have no transaction history.",
    "등록된 계좌가 없습니다.": "No registered accounts were found.",
    "미체결 주문이 없습니다.": "You have no open orders.",
    "보관 중인 아이템이 없습니다.": "You have no items stored at the bank.",
    "심사 대기 대출이 없습니다.": "There are no loans awaiting review.",
    "진행 중인 은행 의뢰가 없습니다.": "There are no active bank requests.",
    "은행 의뢰 내역이 없습니다.": "You have no bank request history.",
    "등록된 시장 공지가 없습니다.": "There are no market announcements.",
    "점수 미등록 · 무작위 변동": "Unscored · random movement",
    "점수 미등록 종목에 하루 -10%~+10% 무작위 변동을 적용했습니다.": "A random daily price movement of -10% to +10% was applied to stocks without scores.",
    "저장하고 공지 채널에 게시했습니다.": "Saved and posted to the announcement channel.",
    "저장했습니다. 게시할 채널이 설정되지 않아 공지 채널에는 올라가지 않았습니다.": "Saved, but no announcement channel is configured.",
    "아직 공개된 평가가 없습니다.": "No evaluation has been published yet.",
    "아직 체결된 거래가 없습니다.": "No trades have been completed yet.",
    "기본재화는 삭제할 수 없습니다.": "The base currency cannot be removed.",
    "잔액 또는 대출이 남아 있어 비활성화할 수 없습니다.": "This currency cannot be disabled while balances or loans remain.",
    "본인에게 송금할 수 없습니다.": "You cannot transfer funds to yourself.",
    "본인 계좌 상태는 변경할 수 없습니다.": "You cannot change your own account status.",
    "동결된 계좌와는 송금할 수 없습니다.": "Transfers to or from frozen accounts are not allowed.",
    "계좌가 동결되어 거래할 수 없습니다. 관리자에게 문의하세요.": "This account is frozen and cannot make transactions. Contact a server administrator.",
    "지갑 잔액이 부족합니다.": "Your wallet balance is insufficient.",
    "예금 잔액이 부족합니다.": "Your deposit balance is insufficient.",
    "서로 다른 재화를 선택하세요.": "Choose two different currencies.",
    "환전 결과가 1 미만입니다. 더 큰 금액을 입력하세요.": "The exchange result is less than 1. Enter a larger amount.",
    "이 계좌는 동결되어 거래할 수 없습니다. 관리자에게 문의하세요.": "This account is frozen. Contact a server administrator.",
    "계좌가 없습니다. 먼저 /register를 사용하세요.": "You do not have an account. Run /register first.",
    "취소할 수 있는 본인 주문이 없습니다.": "You have no open order that can be canceled.",
    "상환 가능한 본인 대출을 찾을 수 없습니다.": "No repayable loan was found for your account.",
    "연장할 수 있는 본인 대출을 찾을 수 없습니다.": "No loan that can be extended was found for your account.",
    "관리자가 대출 연장 기간과 횟수를 아직 설정하지 않았습니다.": "An administrator has not configured loan extension settings yet.",
    "이 대출은 설정된 연장 횟수를 모두 사용했습니다.": "This loan has reached its extension limit.",
    "신용 대출은 골드 등급 이상부터 신청할 수 있습니다.": "Credit loans are available to Gold tier and above.",
    "신용 대출은 벨로만 신청할 수 있습니다.": "Credit loans can only be requested in Bell.",
    "담보 대출은 실버 등급 이상부터 신청할 수 있습니다.": "Collateral loans are available to Silver tier and above.",
    "담보 대출은 벨로만 신청할 수 있습니다.": "Collateral loans can only be requested in Bell.",
    "대출 기간 연장은 실버 등급 이상부터 사용할 수 있습니다.": "Loan extensions are available to Silver tier and above.",
    "대기 중인 대출 신청을 찾을 수 없습니다.": "No pending loan application was found.",
    "관리자가 게임에서 확인한 담보 가치를 입력해야 합니다.": "Enter the collateral value verified by an administrator in-game.",
    "신청 금액이 확인된 담보 가치보다 큽니다.": "The requested amount exceeds the verified collateral value.",
    "신용 대출 승인에는 담보 가치를 입력할 수 없습니다.": "Collateral value cannot be entered when approving a credit loan.",
    "신용 대출은 골드 등급 이상만 승인할 수 있습니다.": "Only Gold tier and above can receive an approved credit loan.",
    "현재 신용 대출 한도를 초과해 승인할 수 없습니다.": "This loan cannot be approved because it exceeds the current credit limit.",
    "반환 가능한 상환 완료 담보를 찾을 수 없습니다.": "No repaid collateral loan ready for return was found.",
    "대출을 지급할 수 없습니다.": "The loan cannot be paid out.",
    "동결된 계좌에는 대출을 지급할 수 없습니다.": "A loan cannot be paid to a frozen account.",
    "대상 사용자의 지갑 잔액이 부족합니다.": "The target user's wallet balance is insufficient.",
    "이 등급의 보관 한도가 설정되지 않았습니다.": "A storage limit has not been configured for this tier.",
    "은행 보관 수량이 부족합니다.": "The stored item quantity is insufficient.",
    "은행 의뢰는 플레티넘 등급 이상부터 이용할 수 있습니다.": "Bank requests are available to Platinum tier and above.",
    "은행 의뢰는 플래티넘 등급 이상부터 이용할 수 있습니다.": "Bank requests are available to Platinum tier and above.",
    "진행 중인 은행 의뢰는 사용자당 최대 5건까지 가능합니다.": "Each user can have up to 5 active bank requests.",
    "은행 의뢰를 찾을 수 없습니다.": "The bank request was not found.",
    "현재 상태에서 해당 의뢰 상태로 변경할 수 없습니다.": "This request cannot be moved to that status.",
    "텍스트 채널을 찾지 못했습니다. 자동완성 목록에서 선택하거나 채널 이름을 확인해 주세요.": "Text channel not found. Select one from autocomplete or check the channel name.",
    "해당 길드의 지정 관계자는 자기 종목 평가에 참여할 수 없습니다.": "A designated stock officer cannot evaluate their own stock.",
    "오늘 공지할 미게시 평가가 없습니다.": "There are no unpublished evaluations to announce today.",
    "같은 이름의 종목이 이미 있습니다.": "A stock with that name already exists.",
    "아이템 이름을 입력하세요.": "Enter an item name.",
    "아이템·재료 이름을 입력하세요.": "Enter an item or material name.",
    "담보 아이템 이름을 입력하세요.": "Enter the name of the collateral item.",
    "20:30~21:00 시세 산정 시간에는 주문할 수 없습니다.": "Orders are unavailable during the 20:30–21:00 market pricing window (KST).",
    "평가는 한국 시간 20:30~21:00 사이에만 등록할 수 있습니다.": "Evaluations can only be submitted between 20:30 and 21:00 KST.",
    "서버에서만 공지 채널을 설정할 수 있습니다.": "Announcement channels can only be configured in a server.",
    "주문 금액이 너무 큽니다.": "The order amount is too large.",
    "주문 금액을 지갑에서 확보할 수 없습니다.": "The order amount could not be reserved from your wallet.",
    "매도 가능한 보유 주식 수가 부족합니다.": "You do not hold enough shares to place this sell order.",
    "미체결 매도 주문을 제외한 보유 주식이 부족합니다.": "You do not have enough shares after excluding open sell orders.",
    "신용 대출 한도를 초과합니다.": "This exceeds the credit loan limit.",
    "신용 대출 신청이 한도를 초과합니다.": "This credit loan application exceeds the limit.",
    "담보 가치가 부족합니다.": "The collateral value is insufficient.",
    "대출 연장 기간과 횟수가 아직 설정되지 않았습니다.": "Loan extension settings have not been configured yet.",
    "처리하지 못했습니다.": "The action could not be completed.",
    "종목별 관계자는 최대 2명까지 지정할 수 있습니다.": "Each stock can have up to 2 designated officers.",
    "해당 종목의 관계자 지정을 찾을 수 없습니다.": "No officer assignment was found for that stock.",
    "평가 점수가 허용 범위를 벗어났습니다.": "The evaluation score is outside the allowed range.",
    "이 확인 버튼은 요청한 관리자만 사용할 수 있습니다.": "Only the administrator who started this action can use these buttons.",
    "이 메뉴는 명령을 실행한 사용자만 사용할 수 있습니다.": "Only the user who opened this menu can use it.",
    "잔액이 없습니다.": "No balances were found.",
    "작업을 취소했습니다.": "Action canceled.",
    "처리하지 못했습니다:": "Could not complete the action:",
    "확인": "Confirm",
    "취소": "Cancel",
    "도움말": "Help",
    "메뉴": "Menu",
    "주식 목록": "Stock list",
    "언어 전환": "Switch language",
    "아래에서 일반 이용자 명령과 관리자 전용 명령을 구분했습니다.": "Commands are grouped into user and administrator sections below.",
    "일반 이용자 명령어": "User commands",
    "관리자 전용 명령어": "Administrator commands",
    "계속": "continued",
    "관리자 전용": "Administrator only",
    "ROBELLANK 은행 봇 도움말": "ROBELLANK Bank Bot Help",
    "ROBELLANK 은행 봇": "ROBELLANK Bank Bot",
    "내 가상주식 포트폴리오": "My Virtual Stock Portfolio",
    "현재 기준가": "Current reference price",
    "발행·유통 규모": "Issued and circulating shares",
    "주문 호가": "Order book",
    "최근 세부 평가": "Latest evaluation",
    "평가 근거": "Evaluation evidence",
    "최근 체결": "Recent trades",
    "평가 전": "Not evaluated",
    "기준가": "Reference price",
    "일간 변동": "Daily change",
    "유통량": "Circulating shares",
    "시가총액": "Market cap",
    "최고 매수": "Best bid",
    "최저 매도": "Best ask",
    "없음": "None",
    "대기 중": "Open",
    "일부 체결": "Partially filled",
    "담보": "Collateral",
    "신용": "Credit",
    "원금": "Principal",
    "남은 원리금": "Remaining balance",
    "만기": "Due",
    "확인 가치": "Verified value",
    "지갑": "Wallet",
    "예금": "Deposit",
    "수락": "Accepted",
    "거절": "Declined",
    "완료": "Completed",
    "pending": "Pending",
    "accepted": "Accepted",
    "declined": "Declined",
    "fulfilled": "Fulfilled",
    "repaid": "Repaid",
    "approved": "Approved",
    "defaulted": "Defaulted",
    "rejected": "Rejected",
    "partial": "Partially filled",
    "open": "Open",
    "cancelled": "Canceled",
    "fulfilled": "Fulfilled",
    "pending": "Pending",
    "partial": "Partially filled",
    "open": "Open",
    "은행 계좌를 개설합니다": "Open a bank account",
    "지갑·예금 잔액을 확인합니다": "Check wallet and deposit balances",
    "다른 사용자에게 재화를 송금합니다": "Transfer currency to another user",
    "지갑에서 예금으로 옮깁니다": "Move funds from wallet to deposit",
    "예금에서 지갑으로 옮깁니다": "Move funds from deposit to wallet",
    "재화를 기본 환율로 환전합니다": "Exchange currency at the base rate",
    "재화별 잔액 순위를 확인합니다": "View the balance leaderboard by currency",
    "내 등급, 신용점수, 은행 혜택을 확인합니다": "View your tier, credit score, and bank benefits",
    "상장 종목 목록": "List listed stocks",
    "상장된 모든 종목을 표로 확인합니다": "View all listed stocks in a table",
    "종목 소개·시세·호가·평가를 자세히 확인합니다": "View stock details, prices, order book, and evaluations",
    "지정가 매수 주문을 냅니다": "Place a limit buy order",
    "보유 주식의 지정가 매도 주문을 냅니다": "Place a limit sell order for shares you own",
    "내 미체결 주문을 확인합니다": "View your open orders",
    "본인 미체결 주문을 취소합니다": "Cancel one of your open orders",
    "보유 주식과 현재 기준 평가액을 확인합니다": "View your stock holdings and current reference value",
    "은행 봇 사용법과 전체 명령어를 확인합니다": "View bank bot help and all commands",
    "은행 메뉴와 주식 목록을 엽니다": "Open the bank menu and stock list",
    "봇 응답 언어를 한국어 또는 English로 설정합니다": "Set the bot response language to Korean or English",
    "골드 이상: 벨 신용 대출을 신청합니다": "Gold tier and above: apply for a Bell credit loan",
    "실버 이상: 게임에서 확인받을 담보 대출을 신청합니다": "Silver tier and above: apply for an in-game collateral loan",
    "내 대출 목록": "List your loans",
    "대출을 상환합니다": "Repay a loan",
    "실버 이상: 대출 기간을 연장합니다": "Silver tier and above: extend a loan term",
    "관리자: 심사 대기 대출 목록": "Administrator: list pending loan applications",
    "신용 대출 신청을 승인합니다": "Approve a credit loan application",
    "게임 내 담보를 확인해 승인합니다": "Verify in-game collateral and approve the loan",
    "대출 신청을 거절합니다": "Decline a loan application",
    "상환 완료된 담보의 게임 내 반환을 기록합니다": "Record the in-game return of repaid collateral",
    "관리자 재량으로 신용점수를 직접 설정합니다": "Set a user's credit score at administrator discretion",
    "규정에 따른 신용점수 증감 사유를 선택합니다": "Adjust credit score using a policy reason",
    "활성 재화·환율·일일 이자율을 확인합니다": "View active currencies, exchange rates, and daily interest",
    "관리자: 재화를 생성하거나 설정을 갱신합니다": "Administrator: create a currency or update its settings",
    "관리자: 기본재화를 지정합니다": "Administrator: set the base currency",
    "관리자: 기본재화 기준 환전가치를 변경합니다": "Administrator: change the exchange value against the base currency",
    "관리자: 일일 예금·대출 이자율을 변경합니다": "Administrator: change daily deposit and loan interest rates",
    "관리자: 재화를 비활성화합니다": "Administrator: disable a currency",
    "관리자: 게임 내 인증을 마친 재화를 지급합니다": "Administrator: grant currency verified in-game",
    "관리자: 재화를 회수합니다": "Administrator: remove currency",
    "관리자: 계좌를 동결합니다": "Administrator: freeze an account",
    "관리자: 계좌 동결을 해제합니다": "Administrator: unfreeze an account",
    "관리자: 전체 계좌의 지갑·예금 통화량을 확인합니다": "Administrator: view total wallet and deposit supply",
    "플래티넘 이상 신용대출 추가 한도(벨)를 설정합니다": "Set the additional Bell credit limit for Platinum tier and above",
    "VIP 예금 추가 일일 이자율을 설정합니다": "Set the VIP additional daily deposit interest rate",
    "등급별 은행 아이템 보관 한도를 설정합니다": "Set the bank item storage limit for each tier",
    "신규 대출 기본 기간을 설정합니다(일, 0=기간 없음)": "Set the default term for new loans (days; 0 means no term)",
    "대출 연장 일수와 횟수를 설정합니다": "Set the number of days and limit for loan extensions",
    "내 은행 보관 아이템을 확인합니다": "View items stored at the bank",
    "관리자: 게임에서 확인한 아이템을 은행에 보관합니다": "Administrator: record items verified in-game as stored at the bank",
    "관리자: 게임에서 반환한 아이템을 기록에서 제거합니다": "Administrator: remove items returned in-game from the records",
    "아이템·재료를 은행에 찾아달라고 요청합니다": "Request that the bank find an item or material",
    "내 은행 의뢰 현황을 확인합니다": "View your bank request status",
    "관리자: 진행 중인 은행 의뢰를 확인합니다": "Administrator: view active bank requests",
    "관리자: 의뢰를 수락·거절·완료 처리합니다": "Administrator: accept, decline, or complete a request",
    "최근 시장 공지를 확인합니다": "View recent market announcements",
    "관리자: 가상 시장 찌라시를 공지합니다": "Administrator: post an unverified market rumor",
    "길드 주식을 상장합니다": "List a guild stock",
    "종목 소개를 등록하거나 수정합니다": "Create or update a stock description",
    "주식을 신규 발행하여 보유자에게 지급합니다": "Issue new shares to a holder",
    "보유 주식을 소각합니다": "Burn shares held by a user",
    "상장을 폐지하고 미체결 주문을 취소합니다": "Delist a stock and cancel its open orders",
    "종목의 세부 평가 점수와 근거를 등록합니다": "Submit a detailed stock score and supporting evidence",
    "오늘 평가와 새 주가를 공지합니다": "Announce today's evaluations and new prices",
    "관리자 전용 · 시세·뉴스 공지 채널을 설정합니다": "Administrator only · set the market and news announcement channel",
    "확인된 시장 소식을 등록합니다": "Post verified market news",
    "길드 관계자를 지정합니다 (종목별 최대 2명)": "Assign a guild officer (up to 2 per stock)",
    "길드 관계자 지정을 해제합니다": "Remove a guild officer assignment",
    "내 최근 은행·주식 거래내역을 확인합니다": "View your recent bank and stock transactions",
}

LABEL_EN = (
    ("평가일", "Evaluation date"),
    ("현재 기준가", "Current reference price"),
    ("전체 주식 시세표", "All stock prices"),
    ("길드 가상주식", "Guild stocks"),
    ("신규 상장", "New listing"),
    ("종목 소개 수정", "Stock description updated"),
    ("초기 발행", "Initial issue"),
    ("종목 이름", "Stock name"),
    ("발행·유통 규모", "Issued and circulating shares"),
    ("유통량", "Circulating shares"),
    ("시가총액", "Market cap"),
    ("기본재화", "base currency"),
    ("기준가", "Reference price"),
    ("일간 변동", "Daily change"),
    ("현재 평가액", "Current value"),
    ("즉시 체결", "Filled immediately"),
    ("미체결", "Remaining"),
    ("지정가", "Limit price"),
    ("최근 체결", "Recent trades"),
    ("최근 세부 평가", "Latest evaluation"),
    ("평가 근거", "Evaluation evidence"),
    ("주문 호가", "Order book"),
    ("최고 매수", "Best bid"),
    ("최저 매도", "Best ask"),
    ("원금", "Principal"),
    ("남은 원리금", "Remaining balance"),
    ("확인 가치", "Verified value"),
    ("시가", "Market price"),
    ("등급", "Tier"),
    ("신용점수", "Credit score"),
    ("신용대출 한도", "Credit limit"),
    ("남은 한도", "Remaining limit"),
    ("예금 이자", "Deposit interest"),
    ("대출 이자", "Loan interest"),
    ("보유 종목", "Holdings"),
    ("보유 현황", "Holdings"),
    ("지갑", "wallet"),
    ("예금", "deposit"),
)


PATTERNS = [
    (
        re.compile(
            r"^(?P<amount>[\d,]+) (?P<currency>.+)을 예금했습니다\. 이자는 매일 한국 시간 자정에 반영됩니다\.$",
            re.S,
        ),
        lambda m: f"Deposited {m['amount']} {m['currency']}. Interest is applied daily at midnight KST.",
    ),
    (
        re.compile(
            r"^(?P<amount>[\d,]+) (?P<currency>.+)을 예금에서 지갑으로 옮겼습니다\.$",
            re.S,
        ),
        lambda m: f"Moved {m['amount']} {m['currency']} from deposit to wallet.",
    ),
    (
        re.compile(
            r"^등급: \*\*(?P<tier>.+?)\*\* · 신용점수 (?P<score>\d+)/100\n혜택: (?P<benefits>.+)\n신용대출 한도 (?P<limit>[\d,]+)벨 · 사용 (?P<used>[\d,]+)벨 · 남은 한도 (?P<available>[\d,]+)벨\n아이템 보관함 (?P<stored>[\d,]+)/(?P<capacity>[\d,]+)개 · 신규 대출 기본 기간 (?P<term>[\d,]+)일 · 연장 (?P<extension_days>[\d,]+)일/(?P<extension_count>[\d,]+)회(?P<vip>\nVIP 예금 추가 이율: (?P<vip_rate>.+)%/일)?\n등급 역할은 관리자가 직접 부여하며 봇은 역할을 변경하지 않습니다\.$",
            re.S,
        ),
        lambda m: _translate_tier(m),
    ),
    (
        re.compile(
            r"^\*\*(?P<stock>.+) 평가 저장\*\*\n기본 (?P<base>-?\d+)점 \+ 무작위 (?P<random>[+-]?\d+)점 = 최종 (?P<final>-?\d+)점 · 변동률 (?P<change>[+-]?\d+)% · 기준가 (?P<old>[\d,]+) → (?P<new>[\d,]+)\n21:00 시세 공지 예정\. 평가 #(?P<id>\d+)\.$",
            re.S,
        ),
        lambda m: f"**{m['stock']} evaluation saved**\nBase {m['base']} + random {m['random']} = final {m['final']} · change {m['change']}% · reference price {m['old']} → {m['new']}\nMarket update scheduled for 21:00 KST. Evaluation #{m['id']}.",
    ),
    (
        re.compile(
            r"^기준가 (?P<old>[\d,]+) → (?P<new>[\d,]+) \((?P<change>[+-]?\d+)%\)\n점수 미등록 종목에 하루 -10%~\+10% 무작위 변동을 적용했습니다\.$",
            re.S,
        ),
        lambda m: f"Reference price {m['old']} → {m['new']} ({m['change']}%)\nA random daily price movement of -10% to +10% was applied to stocks without scores.",
    ),
    (
        re.compile(
            r"^오늘 가상주식 시세 발표\n(?P<rows>.*)$", re.S
        ),
        lambda m: "Today's virtual stock prices\n" + _translate_market_report(m["rows"]),
    ),
    (
        re.compile(r"^재화 '(?P<name>.+)'을\(를\) 찾을 수 없습니다\.$", re.S),
        lambda m: f"Currency '{m['name']}' was not found.",
    ),
    (
        re.compile(
            r"^종목 이름 '(?P<name>.+)'을\(를\) 찾을 수 없습니다\.$", re.S
        ),
        lambda m: f"Stock '{m['name']}' was not found.",
    ),
    (
        re.compile(
            r"^신용 대출 한도를 초과합니다\. 현재 한도 (?P<limit>[\d,]+)벨, 사용 중 (?P<used>[\d,]+)벨입니다\.$",
            re.S,
        ),
        lambda m: f"This exceeds your credit loan limit. Limit: {m['limit']} Bell; used: {m['used']} Bell.",
    ),
    (
        re.compile(
            r"^보관 한도를 초과합니다\. 현재 (?P<current>[\d,]+)개 / 한도 (?P<capacity>[\d,]+)개\.$",
            re.S,
        ),
        lambda m: f"This exceeds your storage limit. Current: {m['current']} / {m['capacity']} items.",
    ),
    (
        re.compile(r"^찌라시 제목은 (?P<range>.+)자로 입력하세요\.$", re.S),
        lambda m: f"Rumor titles must be {m['range']} characters long.",
    ),
    (
        re.compile(r"^찌라시 내용은 (?P<range>.+)자로 입력하세요\.$", re.S),
        lambda m: f"Rumor content must be {m['range']} characters long.",
    ),
    (
        re.compile(r"^종목 이름은 (?P<range>.+)자여야 합니다\.$", re.S),
        lambda m: f"Stock names must be {m['range']} characters long.",
    ),
    (
        re.compile(r"^종목 소개는 (?P<range>.+)자로 입력하세요\.$", re.S),
        lambda m: f"Stock descriptions must be {m['range']} characters long.",
    ),
    (
        re.compile(
            r"^계좌가 동결되어 거래할 수 없습니다\. 관리자에게 문의하세요\.$",
            re.S,
        ),
        lambda m: "This account is frozen and cannot make transactions. Contact a server administrator.",
    ),
    (
        re.compile(
            r"^계좌가 준비되었습니다\. 기본재화는 (?P<currency>.+)입니다\. 지갑 잔액은 0, 신용점수는 50점으로 시작합니다\. 게임 내 재화를 관리자가 인증한 뒤 지급합니다\.$",
            re.S,
        ),
        lambda m: f"Your account is ready. The base currency is {m['currency']}. Your wallet starts at 0 and your credit score at 50. An administrator must verify in-game currency before issuing it.",
    ),
    (
        re.compile(r"^<@(?P<user>\d+)> 잔액\n(?P<rows>.*)$", re.S),
        lambda m: f"Balance for <@{m['user']}>\n{_translate_rows(m['rows'])}",
    ),
    (
        re.compile(
            r"^(?P<amount>[\d,]+) (?P<currency>.+) 송금했습니다\.$", re.S
        ),
        lambda m: f"Transferred {m['amount']} {m['currency']}.",
    ),
    (
        re.compile(
            r"^<@(?P<user>\d+)>에게 (?P<amount>[\d,]+) (?P<currency>.+) 송금했습니다\.$",
            re.S,
        ),
        lambda m: f"Transferred {m['amount']} {m['currency']} to <@{m['user']}>.",
    ),
    (
        re.compile(
            r"^(?P<amount>[\d,]+) (?P<from>.+) → (?P<received>[\d,]+) (?P<to>.+) 환전했습니다\. 소수점 이하 결과는 버림 처리됩니다\.$",
            re.S,
        ),
        lambda m: f"Exchanged {m['amount']} {m['from']} → {m['received']} {m['to']}. Fractional results are rounded down.",
    ),
    (
        re.compile(r"^\*\*(?P<currency>.+) 부자 순위\*\*\n(?P<rows>.*)$", re.S),
        lambda m: f"**{m['currency']} Leaderboard**\n{_translate_rows(m['rows'])}",
    ),
    (
        re.compile(
            r"^\*\*(?P<stock>.+)\*\* 주문 #(?P<id>\d+) · (?P<side>매수|매도) (?P<shares>[\d,]+)주\n지정가 (?P<price>[\d,]+) · 즉시 체결 (?P<filled>[\d,]+)주 · 미체결 (?P<remaining>[\d,]+)주\.$",
            re.S,
        ),
        lambda m: f"**{m['stock']}** order #{m['id']} · {'Buy' if m['side'] == '매수' else 'Sell'} {m['shares']} shares\nLimit price {m['price']} · Filled immediately {m['filled']} shares · Remaining {m['remaining']} shares.",
    ),
    (
        re.compile(
            r"^주문 #(?P<id>\d+)을 취소했습니다\.(?: 확보해 둔 (?P<refund>[\d,]+)을 지갑으로 돌려드렸습니다\.)?$",
            re.S,
        ),
        lambda m: f"Order #{m['id']} canceled."
        + (f" Refunded {m['refund']} to your wallet." if m['refund'] else ""),
    ),
    (
        re.compile(
            r"^신용 대출 신청 #(?P<id>\d+)을 접수했습니다\. 한도 (?P<limit>[\d,]+)벨 중 신청 후 남은 한도 (?P<available>[\d,]+)벨입니다\. 관리자 승인을 기다려 주세요\.$",
            re.S,
        ),
        lambda m: f"Credit loan application #{m['id']} submitted. Remaining limit after this request: {m['available']} Bell out of {m['limit']}. Waiting for administrator approval.",
    ),
    (
        re.compile(
            r"^담보 대출 신청 #(?P<id>\d+)을 접수했습니다: (?P<item>.+) (?P<quantity>[\d,]+)개 · (?P<amount>[\d,]+)벨\. 관리자가 게임 내 담보와 가치를 확인한 뒤 승인합니다\.$",
            re.S,
        ),
        lambda m: f"Collateral loan application #{m['id']} submitted: {m['quantity']} × {m['item']} · {m['amount']} Bell. An administrator will verify the in-game collateral and value before approval.",
    ),
    (
        re.compile(r"^(?P<amount>[\d,]+) 상환했습니다\. 남은 원리금: (?P<remaining>[\d,]+)\.$", re.S),
        lambda m: f"Repaid {m['amount']}. Remaining loan balance: {m['remaining']}.",
    ),
    (
        re.compile(
            r"^대출 #(?P<id>\d+) 만기를 (?P<days>\d+)일 연장했습니다\. 새 만기: (?P<date>.+)$",
            re.S,
        ),
        lambda m: f"Extended loan #{m['id']} by {m['days']} days. New due date: {m['date']}",
    ),
    (
        re.compile(r"^대출 #(?P<id>\d+)을 승인하고 지급했습니다\.$", re.S),
        lambda m: f"Loan #{m['id']} approved and paid.",
    ),
    (
        re.compile(
            r"^대출 #(?P<id>\d+) 신청을 거절했습니다\.$", re.S
        ),
        lambda m: f"Loan application #{m['id']} declined.",
    ),
    (
        re.compile(
            r"^담보 대출 #(?P<id>\d+)을 확인된 가치 (?P<value>[\d,]+)벨로 승인했습니다\.$",
            re.S,
        ),
        lambda m: f"Collateral loan #{m['id']} approved with a verified value of {m['value']} Bell.",
    ),
    (
        re.compile(
            r"^대출 #(?P<id>\d+) 담보 반환을 기록했습니다: (?P<item>.+) (?P<quantity>[\d,]+)개 · <@(?P<user>\d+)>$",
            re.S,
        ),
        lambda m: f"Recorded the return of collateral for loan #{m['id']}: {m['quantity']} × {m['item']} from <@{m['user']}>.",
    ),
    (
        re.compile(
            r"^시세·뉴스 공지 채널을 (?P<channel>.+)로 설정했습니다\.$", re.S
        ),
        lambda m: f"Market and news announcements will be posted in {m['channel']}.",
    ),
    (
        re.compile(r"^시장을 공지했습니다\.$", re.S),
        lambda m: "The market announcement has been posted.",
    ),
    (
        re.compile(
            r"^(?P<name>.+) 재화를 비활성화했습니다\. 사유: (?P<reason>.*)$",
            re.S,
        ),
        lambda m: f"Disabled currency {m['name']}. Reason: {m['reason']}",
    ),
    (
        re.compile(
            r"^재화 (?P<name>.+) \((?P<symbol>.+)\) 설정을 저장했습니다\. 환전가치 (?P<value>.+) · 예금 이자 (?P<deposit>.+)% · 대출 이자 (?P<loan>.+)%\.$",
            re.S,
        ),
        lambda m: f"Saved settings for {m['name']} ({m['symbol']}). Exchange value: {m['value']} · deposit interest: {m['deposit']}% · loan interest: {m['loan']}%.",
    ),
    (
        re.compile(
            r"^(?P<name>.+)을 기본재화로 지정했습니다\.$", re.S
        ),
        lambda m: f"Set {m['name']} as the base currency.",
    ),
    (
        re.compile(
            r"^(?P<name>.+) 환전가치를 (?P<value>.+)로 변경했습니다\.$",
            re.S,
        ),
        lambda m: f"Changed the exchange value of {m['name']} to {m['value']}.",
    ),
    (
        re.compile(
            r"^(?P<name>.+) 일일 예금 이자 (?P<deposit>.+)% · 대출 이자 (?P<loan>.+)%로 변경했습니다\.$",
            re.S,
        ),
        lambda m: f"Updated {m['name']} daily rates: deposit {m['deposit']}% · loan {m['loan']}%.",
    ),
    (
        re.compile(
            r"^<@(?P<user>\d+)> 신용점수? ?(?P<old>\d+)점(?:에서|에서 ) (?P<new>\d+)점으로 변경했습니다\. 사유: (?P<reason>.*)$",
            re.S,
        ),
        lambda m: f"Changed <@{m['user']}>'s credit score from {m['old']} to {m['new']}. Reason: {m['reason']}",
    ),
    (
        re.compile(
            r"^<@(?P<user>\d+)> 신용점수를 (?P<old>\d+)점에서 (?P<new>\d+)점으로 변경했습니다\. 사유: (?P<reason>.*)$",
            re.S,
        ),
        lambda m: f"Changed <@{m['user']}>'s credit score from {m['old']} to {m['new']}. Reason: {m['reason']}",
    ),
    (
        re.compile(
            r"^<@(?P<user>\d+)> 신용점수 (?P<old>\d+)점 → (?P<new>\d+)점 \((?P<delta>[^)]+)점 반영\)\. 사유: (?P<reason>.*)$",
            re.S,
        ),
        lambda m: f"<@{m['user']}>'s credit score changed from {m['old']} to {m['new']} ({m['delta']}). Reason: {m['reason']}",
    ),
    (
        re.compile(
            r"^<@(?P<user>\d+)> 계좌를 (?P<state>.+)$", re.S
        ),
        lambda m: f"Account for <@{m['user']}> "
        + m["state"].replace("동결했습니다", "was frozen")
        .replace("해제했습니다", "was unfrozen")
        .replace("미체결 주식 주문", "open stock orders")
        .replace("건을 취소했습니다", "were canceled"),
    ),
    (
        re.compile(
            r"^(?P<currency>.+) 통화량: (?P<amount>[\d,]+) (?P<symbol>.+) \(전체 계좌의 지갑 \+ 예금 합계\)\.$",
            re.S,
        ),
        lambda m: f"{m['currency']} supply: {m['amount']} {m['symbol']} (wallet + deposit totals across all accounts).",
    ),
    (
        re.compile(
            r"^신규 대출 기본 기간을 (?P<days>\d+)일로 설정했습니다\.$",
            re.S,
        ),
        lambda m: f"Set the default term for new loans to {m['days']} days.",
    ),
    (
        re.compile(
            r"^대출 1회 연장 기간 (?P<days>\d+)일 · 최대 (?P<limit>\d+)회로 설정했습니다\.$",
            re.S,
        ),
        lambda m: f"Set each loan extension to {m['days']} days, up to {m['limit']} times.",
    ),
    (
        re.compile(
            r"^\*\*(?P<name>.+) 신규 상장\*\*\n(?P<description>.*?)\n기준가 (?P<price>[\d,]+) · 초기 발행 (?P<shares>[\d,]+)주$",
            re.S,
        ),
        lambda m: f"**{m['name']} new listing**\n{m['description']}\nReference price {m['price']} · Initial issue {m['shares']} shares",
    ),
    (
        re.compile(
            r"^\*\*(?P<name>.+) 종목 소개 수정\*\*\n(?P<description>.*)$",
            re.S,
        ),
        lambda m: f"**{m['name']} stock description updated**\n{m['description']}",
    ),
    (
        re.compile(
            r"^\*\*\[시장 뉴스(?P<stock> · .+)?\] (?P<title>.+)\*\*\n(?P<content>.*)$",
            re.S,
        ),
        lambda m: f"**[Market news{m['stock'] or ''}] {m['title']}**\n{m['content']}",
    ),
    (
        re.compile(
            r"^플래티넘 이상 신용대출 추가 한도를 (?P<amount>[\d,]+)벨로 설정했습니다\.$",
            re.S,
        ),
        lambda m: f"Set the additional credit limit for Platinum tier and above to {m['amount']} Bell.",
    ),
    (
        re.compile(
            r"^VIP 예금 추가 일일 이자율을 (?P<rate>.+)%p로 설정했습니다\.$",
            re.S,
        ),
        lambda m: f"Set the VIP additional daily deposit interest rate to {m['rate']} percentage points.",
    ),
    (
        re.compile(
            r"^(?P<tier>.+) 보관 한도를 (?P<capacity>[\d,]+)개로 설정했습니다\.$",
            re.S,
        ),
        lambda m: f"Set the {m['tier']} storage limit to {m['capacity']} items.",
    ),
    (
        re.compile(
            r"^대출 #(?P<id>\d+) 신청을 접수했습니다\. 총 한도 (?P<limit>[\d,]+)벨, 승인 대기 포함 남은 한도 (?P<available>[\d,]+)벨입니다\. 관리자 승인을 기다려 주세요\.$",
            re.S,
        ),
        lambda m: f"Loan application #{m['id']} submitted. Total limit: {m['limit']} Bell; remaining limit, including pending applications: {m['available']} Bell. Waiting for administrator approval.",
    ),
    (
        re.compile(
            r"^은행 의뢰 #(?P<id>\d+)을 접수했습니다: (?P<item>.+) (?P<quantity>[\d,]+)개\. 은행에서 확인 후 답변합니다\.$",
            re.S,
        ),
        lambda m: f"Bank request #{m['id']} submitted: {m['quantity']} × {m['item']}. The bank will review it and respond.",
    ),
    (
        re.compile(
            r"^은행 의뢰 #(?P<id>\d+) 상태를 (?P<status>.+)로 변경했습니다\. 사유: (?P<reason>.*)$",
            re.S,
        ),
        lambda m: f"Changed bank request #{m['id']} to {m['status']}. Reason: {m['reason']}",
    ),
    (
        re.compile(
            r"^<@(?P<user>\d+)>에게 (?P<amount>[\d,]+) (?P<currency>.+)를 (?P<operation>지급|회수)합니다\. 사유: (?P<reason>.*)$",
            re.S,
        ),
        lambda m: f"{'Granting' if m['operation'] == '지급' else 'Removing'} {m['amount']} {m['currency']} for <@{m['user']}>. Reason: {m['reason']}",
    ),
    (
        re.compile(
            r"^(?P<operation>지급|회수) 완료: <@(?P<user>\d+)> · (?P<amount>[\d,]+) (?P<currency>.+) · 사유: (?P<reason>.*)$",
            re.S,
        ),
        lambda m: f"{'Granted' if m['operation'] == '지급' else 'Removed'} {m['amount']} {m['currency']} for <@{m['user']}>. Reason: {m['reason']}",
    ),
    (
        re.compile(
            r"^<@(?P<user>\d+)> 은행 보관 아이템 (?P<operation>입고|반환) 기록 완료: (?P<item>.+) (?P<quantity>[\d,]+)개 · 사유: (?P<reason>.*)$",
            re.S,
        ),
        lambda m: f"Recorded {m['quantity']} × {m['item']} as {'stored' if m['operation'] == '입고' else 'returned'} at the bank for <@{m['user']}>. Reason: {m['reason']}",
    ),
    (
        re.compile(
            r"^(?P<item>.+) 재화를 비활성화합니다\. 사유: (?P<reason>.*)$",
            re.S,
        ),
        lambda m: f"Disable currency {m['item']}? Reason: {m['reason']}",
    ),
    (
        re.compile(
            r"^게임 내 확인된 (?P<item>.+) (?P<quantity>[\d,]+)개를 <@(?P<user>\d+)>의 은행 보관 기록에 추가합니다\. 사유: (?P<reason>.*)$",
            re.S,
        ),
        lambda m: f"Add {m['quantity']} × {m['item']} to <@{m['user']}>'s bank storage record, after in-game verification. Reason: {m['reason']}",
    ),
    (
        re.compile(
            r"^게임 내 반환을 확인한 (?P<item>.+) (?P<quantity>[\d,]+)개를 <@(?P<user>\d+)>의 은행 보관 기록에서 제거합니다\. 사유: (?P<reason>.*)$",
            re.S,
        ),
        lambda m: f"Remove {m['quantity']} × {m['item']} from <@{m['user']}>'s bank storage record after confirming the in-game return. Reason: {m['reason']}",
    ),
    (
        re.compile(
            r"^(?P<stock>.+) (?P<shares>[\d,]+)주를 <@(?P<user>\d+)>에게 발행합니다\. 사유: (?P<reason>.*)$",
            re.S,
        ),
        lambda m: f"Issue {m['shares']} shares of {m['stock']} to <@{m['user']}>? Reason: {m['reason']}",
    ),
    (
        re.compile(
            r"^(?P<stock>.+) <@(?P<user>\d+)> 보유분 (?P<shares>[\d,]+)주를 소각합니다\. 사유: (?P<reason>.*)$",
            re.S,
        ),
        lambda m: f"Burn {m['shares']} shares of {m['stock']} held by <@{m['user']}>? Reason: {m['reason']}",
    ),
    (
        re.compile(
            r"^(?P<stock>.+) 상장을 폐지하고 미체결 주문을 취소합니다\. 사유: (?P<reason>.*)$",
            re.S,
        ),
        lambda m: f"Delist {m['stock']} and cancel its open orders? Reason: {m['reason']}",
    ),
    (
        re.compile(
            r"^\*\*(?P<stock>.+?) 평가 저장\*\*\n기본 (?P<base>-?\d+)점 \+ 무작위 (?P<random>[+-]?\d+)점 = 최종 (?P<final>-?\d+)점 · 변동률 (?P<change>[+-]?\d+)% · 기준가 (?P<old>[\d,]+) → (?P<new>[\d,]+)\n21:00 시세 공지 예정\. 평가 #(?P<id>\d+)\.$",
            re.S,
        ),
        lambda m: f"**{m['stock']} evaluation saved**\nBase {m['base']} + random {m['random']} = final {m['final']} · change {m['change']}% · reference price {m['old']} → {m['new']}\nMarket update scheduled for 21:00 KST. Evaluation #{m['id']}.",
    ),
    (
        re.compile(
            r"^(?P<name>.+) 관계자를 지정했습니다\. 해당 관계자는 소속 종목 평가에서 제외됩니다\.$",
            re.S,
        ),
        lambda m: f"Assigned {m['name']} as a stock officer. They cannot evaluate stocks they represent.",
    ),
    (
        re.compile(
            r"^(?P<name>.+) 관계자 지정을 해제했습니다\.$", re.S
        ),
        lambda m: f"Removed the stock officer assignment for {m['name']}.",
    ),
    (
        re.compile(
            r"^(?P<name>.+) (?:상장을 폐지하고 미체결 주문을 취소했습니다\. 보유 주식과 기록은 보존됩니다\.|(?P<shares>[\d,]+)주를 <@(?P<user>\d+)>에게 발행했습니다\. 사유: (?P<reason>.*)|<@(?P<user2>\d+)> 보유분 (?P<burn>[\d,]+)주를 소각했습니다\. 사유: (?P<reason2>.*))$",
            re.S,
        ),
        lambda m: (
            f"Delisted {m['name']}; open orders were canceled. Holdings and records were preserved."
            if "상장을" in m[0]
            else f"Issued {m['shares']} shares of {m['name']} to <@{m['user']}>. Reason: {m['reason']}"
            if m["shares"]
            else f"Burned {m['burn']} shares of {m['name']} held by <@{m['user2']}>. Reason: {m['reason2']}"
        ),
    ),
    (
        re.compile(
            r"^시장을 공지했습니다\.$", re.S
        ),
        lambda m: "The market announcement has been posted.",
    ),
    (
        re.compile(r"^평가 점수가 허용 범위를 벗어났습니다\.$", re.S),
        lambda m: "The evaluation score is outside the allowed range.",
    ),
]


def _translate_tier(match: re.Match) -> str:
    tier_names = {
        "브론즈": "Bronze",
        "실버": "Silver",
        "골드": "Gold",
        "플래티넘": "Platinum",
        "에이스": "Ace",
        "VIP": "VIP",
    }
    benefit_text = {
        "입금·출금 가능 · 대출 신청 불가": "Deposits and withdrawals · no loan applications",
        "브론즈 혜택 · 아이템/재료 담보 대출 · 대출 기간 연장": "Bronze benefits · item/material collateral loans · loan extensions",
        "실버 혜택 · 신용점수 기반 신용 대출": "Silver benefits · credit-score-based credit loans",
        "골드 혜택 · 은행 아이템 의뢰 · 대출 한도·보관 한도 추가 설정": "Gold benefits · bank item requests · additional loan and storage limits",
        "플래티넘 혜택 · 대출 심사 우선순위 · 이벤트 우선 참여(운영진 관리)": "Platinum benefits · loan review priority · priority event access (managed by staff)",
        "에이스 혜택 · 예금 이자 추가율 및 추가 혜택(운영진 설정)": "Ace benefits · additional deposit interest and perks (set by staff)",
    }.get(match["benefits"], match["benefits"])
    output = (
        f"Tier: **{tier_names.get(match['tier'], match['tier'])}** · Credit score {match['score']}/100\n"
        f"Benefits: {benefit_text}\n"
        f"Credit limit {match['limit']} Bell · used {match['used']} Bell · remaining {match['available']} Bell\n"
        f"Bank storage {match['stored']}/{match['capacity']} items · default loan term {match['term']} days · "
        f"extension {match['extension_days']} days/{match['extension_count']} times"
    )
    if match["vip_rate"]:
        output += f"\nVIP additional deposit rate: {match['vip_rate']}%/day"
    return output + "\nTier roles are assigned by server administrators; the bot does not change roles."


def _translate_market_report(rows: str) -> str:
    translated_groups = []
    for group in rows.split("\n\n"):
        lines = group.splitlines()
        if not lines:
            continue
        first_line = re.fullmatch(
            r"\*\*(?P<stock>.+?)\*\* · (?P<old>[\d,]+) → (?P<new>[\d,]+) "
            r"\((?P<change>[+-]?\d+)%\) · (?P<score>.+)",
            lines[0],
        )
        if first_line:
            score = first_line["score"].replace(
                "점수 미등록 · 무작위 변동", "Unscored · random movement"
            )
            score = re.sub(r"평가 ([+-]?\d+)점", r"Score \1", score)
            lines[0] = (
                f"**{first_line['stock']}** · {first_line['old']} → {first_line['new']} "
                f"({first_line['change']}%) · {score}"
            )
        lines = [STATIC_EN.get(line, line) for line in lines]
        translated_groups.append("\n".join(lines))
    return "\n\n".join(translated_groups)


def _tier_name(name: str) -> str:
    return {
        "브론즈": "Bronze",
        "실버": "Silver",
        "골드": "Gold",
        "플래티넘": "Platinum",
        "에이스": "Ace",
        "VIP": "VIP",
    }.get(name, name)


def _translate_transaction_description(description: str) -> str:
    return {
        "지갑에서 예금": "Wallet to deposit",
        "예금에서 지갑": "Deposit to wallet",
        "송금": "Transfer",
        "환전": "Currency exchange",
        "주식 매수": "Stock purchase",
        "주식 매도": "Stock sale",
        "대출 지급": "Loan payout",
        "대출 상환": "Loan repayment",
        "예금 이자": "Deposit interest",
        "대출 이자": "Loan interest",
    }.get(description, description)


def _translate_rows(rows: str) -> str:
    line_patterns = [
        (
            re.compile(
                r"^\*\*(?P<stock>.+?)\*\* · #(?P<id>\d+) (?P<side>매수|매도) · 지정가 (?P<price>[\d,]+)$"
            ),
            lambda m: f"**{m['stock']}** · #{m['id']} {'Buy' if m['side'] == '매수' else 'Sell'} · limit {m['price']}",
        ),
        (
            re.compile(
                r"^(?P<status>일부 체결|대기 중) · 체결 (?P<filled>[\d,]+)/(?P<total>[\d,]+)주 · 잔량 (?P<remaining>[\d,]+)주$"
            ),
            lambda m: f"{'Partially filled' if m['status'] == '일부 체결' else 'Open'} · filled {m['filled']}/{m['total']} shares · remaining {m['remaining']} shares",
        ),
        (
            re.compile(
                r"^#(?P<id>\d+) (?P<kind>담보|신용) · 원금 (?P<principal>[\d,]+) · 남은 원리금 (?P<due>[\d,]+) · 일 (?P<rate>.+)% · (?P<status>[^·]+)(?P<extra>(?: · .*)?)$"
            ),
            lambda m: f"#{m['id']} {'Collateral' if m['kind'] == '담보' else 'Credit'} · principal {m['principal']} · remaining balance {m['due']} · daily {m['rate']}% · {STATIC_EN.get(m['status'].strip(), m['status'].strip())}"
            + m["extra"].replace("만기 ", "due ").replace("담보 ", "collateral ").replace("개 · 확인 가치 ", " items · verified value ").replace("개", " items").replace("벨", " Bell"),
        ),
        (
            re.compile(
                r"^#(?P<id>\d+) <@(?P<user>\d+)> · (?P<tier>[^·]+) · (?P<type>신용|담보(?: (?P<item>.+) (?P<quantity>[\d,]+)개)?) · (?P<amount>[\d,]+)벨$"
            ),
            lambda m: f"#{m['id']} <@{m['user']}> · {_tier_name(m['tier'])} · "
            + ("Credit" if m["type"] == "신용" else f"Collateral {m['quantity']} × {m['item']}")
            + f" · {m['amount']} Bell",
        ),
        (
            re.compile(
                r"^#(?P<id>\d+) <@(?P<user>\d+)> · (?P<item>.+) (?P<quantity>[\d,]+)개 · (?P<status>.+?)(?: · (?P<note>.*))?$"
            ),
            lambda m: f"#{m['id']} <@{m['user']}> · {m['quantity']} × {m['item']} · {STATIC_EN.get(m['status'], m['status'])}"
            + (f" · {m['note']}" if m['note'] else ""),
        ),
        (
            re.compile(
                r"^#(?P<id>\d+) · (?P<item>.+) (?P<quantity>[\d,]+)개 · (?P<status>.+?)(?: · (?P<note>.*))?$"
            ),
            lambda m: f"#{m['id']} · {m['quantity']} × {m['item']} · {STATIC_EN.get(m['status'], m['status'])}"
            + (f" · {m['note']}" if m['note'] else ""),
        ),
        (
            re.compile(
                r"^(?P<name>.+): (?P<quantity>[\d,]+)개$"
            ),
            lambda m: f"{m['name']}: {m['quantity']} items",
        ),
        (
            re.compile(
                r"^\*\*(?P<name>.+)\*\* \((?P<symbol>.+)\) · 환전가치 (?P<value>.+?)(?P<base> · 기본재화)? · 일 예금 (?P<deposit>.+)% · 일 대출 (?P<loan>.+)%$"
            ),
            lambda m: f"**{m['name']}** ({m['symbol']}) · exchange value {m['value']}{' · base currency' if m['base'] else ''} · daily deposit {m['deposit']}% · daily loan {m['loan']}%",
        ),
        (
            re.compile(
                r"^<t:(?P<timestamp>\d+):R> · (?P<description>.+) · (?P<amount>[\d,]+) (?P<currency>.+?)(?: \(수수료 (?P<fee>[\d,]+)\))?$"
            ),
            lambda m: f"<t:{m['timestamp']}:R> · {_translate_transaction_description(m['description'])} · {m['amount']} {m['currency']}"
            + (f" (fee {m['fee']})" if m['fee'] else ""),
        ),
    ]
    translated = []
    for row in rows.splitlines():
        for pattern, render in line_patterns:
            match = pattern.fullmatch(row)
            if match:
                row = render(match)
                break
        row = re.sub(
            r"\*\*(.+?)\*\* \((.+?)\) · 지갑 (.+?) · 예금 (.+)$",
            r"**\1** (\2) · wallet \3 · deposit \4",
            row,
        )
        row = re.sub(r"^(?P<rank>\d+)\. <@(?P<user>\d+)> · (?P<total>[\d,]+) (?P<symbol>.+)$",
                     r"\g<rank>. <@\g<user>> · \g<total> \g<symbol>", row)
        row = row.replace("등록된 계좌가 없습니다.", "No registered accounts were found.")
        translated.append(row)
    return "\n".join(translated)


def translate_known_text(text: str, language: str) -> str:
    if language != "en":
        return text
    exact = STATIC_EN.get(text)
    if exact is not None:
        return exact
    for pattern, render in PATTERNS:
        match = pattern.fullmatch(text)
        if match:
            return render(match)
    rows = _translate_rows(text)
    if rows != text:
        return rows
    translated = text
    for source, target in LABEL_EN:
        translated = translated.replace(source, target)
    return translated


def translate_message(text: str, language: str) -> str:
    translated = translate_known_text(text, language)
    if language != "en" or not re.search(r"[가-힣]", translated):
        return translated
    if text in STATIC_EN or any(pattern.fullmatch(text) for pattern, _ in PATTERNS):
        return translated
    if _translate_rows(text) != text:
        return translated
    if translated != text:
        return f"English translation is partial; original message:\n{text}"
    return f"English translation unavailable; original message:\n{text}"
