# ROBELLANK 은행 봇

Discord 슬래시 명령으로 운영하는 서버별 가상 은행과 길드 가상주식 시장입니다. 계좌, 통화, 대출, 주문, 체결, 일일 평가 기록은 PostgreSQL에 저장됩니다.

## 사용자 명령

계좌를 처음 쓸 때 `/register`를 먼저 실행하세요. 신규 계좌는 지갑 잔액 0, 신용점수 50점으로 시작합니다.

| 명령 | 설명 |
| --- | --- |
| `/register` | 계좌 개설 |
| `/help` | 봇 안에서 전체 사용법 확인 |
| `/balance [user]` | 본인 또는 다른 사용자의 지갑·예금 잔액 확인 |
| `/transfer user currency amount` | 등록된 사용자에게 지갑 재화 송금 |
| `/exchange from to amount` | 설정된 환전가치로 환전. 결과 소수점은 버림 |
| `/history` | 최근 은행·주식 거래내역 |
| `/leaderboard currency` | 지갑+예금 잔액 상위 10명 |
| `/deposit currency amount` | 지갑에서 예금으로 이동 |
| `/withdraw currency amount` | 예금에서 지갑으로 이동 |
| `/loan request currency amount` | 대출 신청. 관리자 승인 전에는 지급되지 않음 |
| `/loan repay loan_id amount` | 본인 대출 상환 |
| `/loan list` | 본인 대출 조회 |
| `/tier` | 현재 등급·신용점수·대출 한도·혜택 확인 |
| `/currency list` | 활성 재화, 환전가치, 일일 이자율 확인 |
| `/stock list` | 상장 종목과 현재 기준 주가 확인 |
| `/stock quote stock` | 종목 소개, 기준가, 시가총액, 호가, 최근 체결, 세부 평가 확인 |
| `/stock buy stock shares limit_price` | 종목 이름으로 지정가 매수. 주문 금액을 지갑에서 먼저 확보 |
| `/stock sell stock shares limit_price` | 종목 이름으로 보유 주식 지정가 매도 |
| `/stock orders` | 본인 미체결 주식 주문 확인 |
| `/stock cancel order_id` | 본인 미체결 주문 취소 |
| `/portfolio` | 보유 주식과 현재 기준 평가액 |
| `/market news` | 최근 시장 공지 |

## 관리자 명령

서버의 Discord **Administrator** 권한이 필요합니다. 계좌 동결/해제 외에 잔액·주식 수량·재화 상태를 바꾸는 주요 작업은 확인 버튼을 한 번 더 눌러야 합니다.

| 명령 | 설명 |
| --- | --- |
| `/currency create name symbol [value] [deposit_rate] [loan_rate]` | 재화 생성 또는 설정 갱신. 생략값은 가치 1, 예금·대출 이자 0% |
| `/currency setbase currency` | 기본재화 지정 |
| `/currency setvalue currency value` | 기본재화 기준 환전가치 변경 |
| `/currency setrate currency deposit_rate loan_rate` | 일일 예금·대출 이자율 변경 |
| `/currency remove currency reason` | 재화 비활성화. 기본재화·잔액·진행 중 대출이 있는 재화는 비활성화 불가 |
| `/mint user currency amount reason` | 재화 발행 지급 (확인 버튼) |
| `/confiscate user currency amount reason` | 지갑 재화 회수 (확인 버튼) |
| `/freeze user reason` | 계좌 동결 및 해당 사용자의 미체결 주식 주문 취소 |
| `/unfreeze user reason` | 계좌 동결 해제 |
| `/supply currency` | 전체 계좌의 지갑+예금 통화량 |
| `/credit adjust user adjustment detail` | 선택한 사유에 따라 신용점수 증감 (0~100점 범위, 변경 기록 저장) |
| `/credit set user score reason` | 관리자 재량으로 신용점수 직접 설정 |
| `/loan approve loan_id` | 대기 중 대출 승인 및 지급 (확인 버튼) |
| `/loan reject loan_id reason` | 대기 중 대출 거절 (확인 버튼) |
| `/market create name description price initial_shares holder reason` | 이름으로 종목 상장, 소개 등록 및 초기 주식 발행 |
| `/market describe stock description reason` | 종목 소개 수정. 이전 소개는 공지 내역에 보존 |
| `/market remove stock reason` | 이름으로 상장 폐지, 미체결 주문 취소. 보유 및 거래 기록은 보존 (확인 버튼) |
| `/market issue stock holder shares reason` | 주식 신규 발행 및 지정 사용자에게 지급 (확인 버튼) |
| `/market burn stock holder shares reason` | 지정 사용자의 주식 소각 (확인 버튼) |
| `/market officer-add stock officer` | 종목별 관계자 지정 (최대 2명) |
| `/market officer-remove stock officer` | 관계자 지정 해제 |
| `/market evaluate stock content activity membership events growth influence opinion evidence` | 이름으로 종목을 골라 세부 점수와 근거 입력 |
| `/market publish [stock]` | 오늘의 미게시 평가와 새 주가 발표 |
| `/market channel channel` | 시세·뉴스 자동 공지 채널 설정 |
| `/market note [stock] title content` | 종목 이름을 연결해 확인된 시장 소식을 공지 |

## 시장 운영 규칙

- 주문은 유저 간 지정가 주문끼리 가격이 맞을 때만 체결됩니다. 상대 주문이 없으면 미체결 상태로 남습니다.
- 티커는 사용하지 않습니다. 서버 안에서 중복되지 않는 종목 이름으로 조회·주문하고, 거래·보유 기록은 내부 종목 ID에 계속 연결해 이름 변경과 무관하게 보존합니다.
- 종목 상세에는 소개, 기준가, 유통 주식 수, 시가총액, 최고 매수·최저 매도 호가, 최근 체결 3건, 최근 평가 세부 점수와 근거를 표시합니다. 기존 종목은 관리자가 `/market describe`로 소개를 등록할 수 있습니다.
- 매수 수수료는 없습니다. 매도 수수료는 체결 금액의 7.5%이며, 재화가 정수라 수수료를 가장 가까운 정수로 반올림합니다.
- 매수 주문은 최대 주문 금액을 미리 확보하고, 취소·마감 때 미체결분을 돌려줍니다. 매도 주문은 보유 주식 수량 안에서만 낼 수 있습니다.
- 매일 한국 시간 20:30에 주문을 마감하고 미체결 주문을 취소합니다. 20:30~21:00에는 시세 산정, 21:00부터 새 기준 주가로 거래가 재개됩니다.
- 평가 구성은 콘텐츠 ±6, 활동 ±6, 인원 ±5, 주요 사건 ±8, 성장 ±5, 영향력 ±5, 유저 여론 ±5점입니다. 입력된 기본 점수에 -10~+10의 무작위 점수를 더하고, 점수 구간의 변동률을 적용합니다. 하루 최대 변동 폭은 ±20%이며 주당 최저가는 1입니다.
- `/market evaluate`에 입력하는 여론 점수는 무작위 유저 7명의 의견을 검토한 결과를 관리자가 입력합니다. 이 버전은 투표자 자동 추첨·투표 수집을 수행하지 않습니다. 지정 관계자는 본인 소속 종목 평가를 입력할 수 없습니다.
- 이자는 통화별 **일일** 비율이며 한국 시간 자정에 예금·승인 대출 원리금에 반영됩니다. 수수료와 이자는 정수 단위로 계산합니다.
- 신용점수는 0~100점이며 신규 계좌는 50점으로 시작합니다. 대출 한도 기본값은 점수 1점당 10,000벨입니다. 관리자 `/credit adjust` 선택지에 적금, 대출 상환, 연체, 규정 위반, 직원 선임 등 사유가 있으며, 적금 상태·게임 레벨은 봇이 자동 확인하지 않습니다. 처벌 회피 시 타임아웃은 관리자가 별도로 적용합니다.
- 등급 역할은 서버 관리자가 직접 부여합니다. 서버 인원 25명 이상(봇 제외)인 길드장은 플래티넘으로 시작하고, 동맹 길드장은 원하는 2명을 골드로 시작시킬 수 있습니다. 봇은 디스코드 역할을 자동으로 부여하거나 변경하지 않습니다.
- 게임 내 재화는 사용자가 직접 등록하지 않습니다. 관리자가 게임 내 보유를 확인한 뒤 `/mint`로 은행 잔액에 지급하며, 확인 버튼을 거쳐 기록합니다.
- 통화·주식 공급 변경과 시세 평가는 기록으로 보존합니다. 상장 주식은 이벤트용 가상 자산이며 실제 화폐, 지분 또는 소유권이 아닙니다. 원금·수익을 보장하지 않습니다.

## 실행

비밀값 `DISCORD_BOT_TOKEN`이 Replit Secrets에 저장되어 있어야 합니다. 데이터베이스 스키마는 `pnpm --filter @workspace/db run push`로 개발 DB에 반영합니다. 실행은 `ROBELLANK Bank Bot` 워크플로를 사용합니다.

Discord Developer Portal에서 봇을 서버에 초대할 때 `bot`과 `applications.commands` 스코프 및 서버에서 명령을 사용하고 공지를 보낼 권한을 부여하세요. 서버에 초대한 뒤 전역 슬래시 명령이 보이기까지 Discord 전파 시간이 걸릴 수 있습니다.
