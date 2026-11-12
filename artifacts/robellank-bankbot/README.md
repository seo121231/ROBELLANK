# ROBELLANK 은행 봇

Discord 슬래시 명령으로 운영하는 서버별 가상 은행과 길드 가상주식 시장입니다. 계좌, 통화, 대출, 주문, 체결, 일일 평가 기록은 PostgreSQL에 저장됩니다. 모든 명령 응답과 확인 메시지는 채널에 공개되므로 민감한 정보를 입력하지 마세요.

## 명령 범주

계좌를 처음 쓸 때 `/profile register`를 실행하세요. 신규 계좌는 지갑 잔액 0, 신용점수 50점으로 시작합니다. `/profile menu`에서 범주를 확인하고 `/help`에서 명령어 목록만 볼 수 있습니다.

| 범주 | 주요 명령 |
| --- | --- |
| `/profile` | `register`, `balance`, `tier`, `history`, `leaderboard`, `menu`, `language` |
| `/storage` | `vault list`, `bank-request submit`, `bank-request list` |
| `/savings` | `currencies`, `transfer`, `exchange`, `deposit` (choose deposit or withdraw), `loan request`, `loan collateral-request`, `loan repay`, `loan list` |
| `/stocks` | `stock list`, `stock table`, `stock quote`, `stock buy`, `stock sell`, `stock orders`, `stock cancel`, `portfolio`, `market news` |
| `/other` | Administrator currency, credit, account, and tier settings |

Deposit and withdrawal share `/savings deposit`. Stock orders use the stock name; buy orders reserve the order amount from the wallet.

## 관리자 기능

관리자 기능은 서버의 Discord **Administrator** 권한이 필요합니다. 잔액·주식 수량·재화 상태를 바꾸는 주요 작업은 확인 버튼으로 한 번 더 확인합니다.

- `/other tier-benefits` opens a selector and input form for loan limits, VIP deposit bonus, tier storage limits, loan terms, and extensions. Changes and reasons are recorded.
- `/savings currencies` lists active currencies and rates. `/other currency` manages currencies, exchange values, rates, base currency, and deactivation.
- `/other mint`, `/other confiscate`, `/other freeze`, `/other unfreeze`, and `/other supply` manage accounts and money supply.
- `/other credit adjust` and `/other credit set` manage credit scores.
- `/storage vault add|remove` records game-verified items. `/storage bank-request queue|update` manages requests.
- `/savings loan queue|approve|reject|collateral-approve|collateral-return` handles loan review.
- `/stocks market create|describe|remove|issue|burn|evaluate|publish|channel|note|rumor|officer-add|officer-remove` manages the market.

## 시장 운영 규칙

- 주문은 유저 간 지정가 주문끼리 가격이 맞을 때만 체결됩니다. 상대 주문이 없으면 미체결 상태로 남습니다.
- 티커는 사용하지 않습니다. 서버 안에서 중복되지 않는 종목 이름으로 조회·주문하고, 거래·보유 기록은 내부 종목 ID에 계속 연결해 이름 변경과 무관하게 보존합니다.
- 종목 상세에는 소개, 기준가, 유통 주식 수, 시가총액, 최고 매수·최저 매도 호가, 최근 체결 3건, 최근 평가 세부 점수와 근거를 표시합니다. 기존 종목은 관리자가 `/stocks market describe`로 소개를 등록할 수 있습니다.
- 매수 수수료는 없습니다. 매도 수수료는 체결 금액의 7.5%이며, 재화가 정수라 수수료를 가장 가까운 정수로 반올림합니다.
- 매수 주문은 최대 주문 금액을 미리 확보하고, 취소·마감 때 미체결분을 돌려줍니다. 매도 주문은 보유 주식 수량 안에서만 낼 수 있습니다.
- 매일 한국 시간 20:30에 주문을 마감하고 미체결 주문을 취소합니다. 20:30~21:00에는 시세 산정, 21:00부터 새 기준 주가로 거래가 재개됩니다.
- 평가 구성은 콘텐츠 ±6, 활동 ±6, 인원 ±5, 주요 사건 ±8, 성장 ±5, 영향력 ±5, 유저 여론 ±5점입니다. 입력된 기본 점수에 -10~+10의 무작위 점수를 더하고, 점수 구간의 변동률을 적용합니다. 점수가 입력되지 않은 상장 종목은 매일 발표 시 -10%~+10% 범위에서 무작위 변동률을 적용하며, 주당 최저가는 1입니다.
- `/stocks market evaluate`에 입력하는 여론 점수는 무작위 유저 7명의 의견을 검토한 결과를 관리자가 입력합니다. 이 버전은 투표자 자동 추첨·투표 수집을 수행하지 않습니다. 지정 관계자는 본인 소속 종목 평가를 입력할 수 없습니다.
- 이자는 통화별 **일일** 비율이며 한국 시간 자정에 예금·승인 대출 원리금에 반영됩니다. 수수료와 이자는 정수 단위로 계산합니다.
- 신용점수는 0~100점이며 신규 계좌는 50점으로 시작합니다. 대출 한도 기본값은 점수 1점당 10,000벨입니다. 관리자 `/other credit adjust` 선택지에 적금, 대출 상환, 연체, 규정 위반, 직원 선임 등 사유가 있으며, 적금 상태·게임 레벨은 봇이 자동 확인하지 않습니다. 처벌 회피 시 타임아웃은 관리자가 별도로 적용합니다.
- 등급 역할은 서버 관리자가 직접 부여합니다. 서버 인원 25명 이상(봇 제외)인 길드장은 플래티넘으로 시작하고, 동맹 길드장은 원하는 2명을 골드로 시작시킬 수 있습니다. 봇은 디스코드 역할을 자동으로 부여하거나 변경하지 않습니다.
- 게임 내 재화는 사용자가 직접 등록하지 않습니다. 관리자가 게임 내 보유를 확인한 뒤 `/other mint`로 은행 잔액에 지급하며, 확인 버튼을 거쳐 기록합니다.
- 통화·주식 공급 변경과 시세 평가는 기록으로 보존합니다. 상장 주식은 이벤트용 가상 자산이며 실제 화폐, 지분 또는 소유권이 아닙니다. 원금·수익을 보장하지 않습니다. 찌라시는 운영진이 작성하는 미확인 정보로, 공식 사실이나 투자 권유로 간주하지 않습니다.

## 실행

비밀값 `DISCORD_TOKEN` 또는 `DISCORD_BOT_TOKEN` 중 하나와 `DATABASE_URL`이 설정되어 있어야 합니다. 데이터베이스 스키마는 `pnpm --filter @workspace/db run push`로 개발 DB에 반영합니다. Python 진입점은 프로젝트 루트의 `main.py`이며 `ROBELLANK Bank Bot` 워크플로가 `uv run python main.py`로 실행합니다.

Discord Developer Portal에서 봇을 서버에 초대할 때 `bot`과 `applications.commands` 스코프 및 서버에서 명령을 사용하고 공지를 보낼 권한을 부여하세요. 서버에 초대한 뒤 전역 슬래시 명령이 보이기까지 Discord 전파 시간이 걸릴 수 있습니다.
