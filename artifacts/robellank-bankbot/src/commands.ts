import {
  SlashCommandBuilder,
  SlashCommandIntegerOption,
  SlashCommandStringOption,
  SlashCommandUserOption,
} from "discord.js";

const currency = (option: SlashCommandStringOption, name = "currency") =>
  option
    .setName(name)
    .setDescription("재화 이름")
    .setRequired(true)
    .setMaxLength(32);

const amount = (option: SlashCommandIntegerOption, name = "amount") =>
  option
    .setName(name)
    .setDescription("금액 또는 수량")
    .setRequired(true)
    .setMinValue(1)
    .setMaxValue(2_147_483_647);

const ticker = (option: SlashCommandStringOption, name = "ticker") =>
  option
    .setName(name)
    .setDescription("종목 티커")
    .setRequired(true)
    .setMaxLength(12);

const user = (option: SlashCommandUserOption, name = "user") =>
  option
    .setName(name)
    .setDescription("디스코드 사용자")
    .setRequired(true);

const adminReason = (option: SlashCommandStringOption) =>
  option
    .setName("reason")
    .setDescription("변경 사유 (기록·공지에 남습니다)")
    .setRequired(true)
    .setMaxLength(500);

export const commands = [
  new SlashCommandBuilder()
    .setName("register")
    .setDescription("은행 계좌를 개설합니다"),
  new SlashCommandBuilder()
    .setName("help")
    .setDescription("은행 봇 사용법과 전체 명령어를 확인합니다"),
  new SlashCommandBuilder()
    .setName("balance")
    .setDescription("지갑·예금 잔액을 확인합니다")
    .addUserOption((option) =>
      option.setName("user").setDescription("조회할 사용자 (생략하면 본인)"),
    ),
  new SlashCommandBuilder()
    .setName("transfer")
    .setDescription("다른 사용자에게 재화를 송금합니다")
    .addUserOption((option) => user(option))
    .addStringOption((option) => currency(option))
    .addIntegerOption((option) => amount(option)),
  new SlashCommandBuilder()
    .setName("exchange")
    .setDescription("재화를 기본 환율로 환전합니다")
    .addStringOption((option) =>
      currency(option, "from").setDescription("보낼 재화"),
    )
    .addStringOption((option) =>
      currency(option, "to").setDescription("받을 재화"),
    )
    .addIntegerOption((option) => amount(option)),
  new SlashCommandBuilder()
    .setName("history")
    .setDescription("내 최근 은행·주식 거래내역을 확인합니다"),
  new SlashCommandBuilder()
    .setName("leaderboard")
    .setDescription("재화별 잔액 순위를 확인합니다")
    .addStringOption((option) => currency(option)),
  new SlashCommandBuilder()
    .setName("deposit")
    .setDescription("지갑에서 예금으로 옮깁니다 (이자는 매일 계산)")
    .addStringOption((option) => currency(option))
    .addIntegerOption((option) => amount(option)),
  new SlashCommandBuilder()
    .setName("withdraw")
    .setDescription("예금에서 지갑으로 옮깁니다")
    .addStringOption((option) => currency(option))
    .addIntegerOption((option) => amount(option)),
  new SlashCommandBuilder()
    .setName("tier")
    .setDescription("내 등급, 신용점수, 은행 혜택을 확인합니다"),
  new SlashCommandBuilder()
    .setName("loan")
    .setDescription("대출 신청·상환·조회 (승인형 대출)")
    .addSubcommand((sub) =>
      sub
        .setName("request")
        .setDescription("골드 이상: 신용 대출을 신청합니다 (벨)")
        .addStringOption((option) => currency(option))
        .addIntegerOption((option) => amount(option)),
    )
    .addSubcommand((sub) =>
      sub
        .setName("collateral-request")
        .setDescription("실버 이상: 게임에서 확인받을 담보 대출을 신청합니다")
        .addStringOption((option) =>
          option
            .setName("item")
            .setDescription("맡길 아이템·재료 이름")
            .setRequired(true)
            .setMaxLength(80),
        )
        .addIntegerOption((option) =>
          option
            .setName("quantity")
            .setDescription("담보 수량")
            .setRequired(true)
            .setMinValue(1)
            .setMaxValue(2_147_483_647),
        )
        .addIntegerOption((option) =>
          option
            .setName("amount")
            .setDescription("신청할 벨 금액")
            .setRequired(true)
            .setMinValue(1)
            .setMaxValue(2_147_483_647),
        ),
    )
    .addSubcommand((sub) =>
      sub
        .setName("repay")
        .setDescription("대출을 상환합니다")
        .addIntegerOption((option) =>
          option
            .setName("loan_id")
            .setDescription("대출 ID")
            .setRequired(true)
            .setMinValue(1),
        )
        .addIntegerOption((option) => amount(option)),
    )
    .addSubcommand((sub) => sub.setName("list").setDescription("내 대출 목록"))
    .addSubcommand((sub) =>
      sub
        .setName("extend")
        .setDescription("실버 이상: 대출 기간 연장 (관리자 설정 기준)")
        .addIntegerOption((option) =>
          option
            .setName("loan_id")
            .setDescription("대출 ID")
            .setRequired(true)
            .setMinValue(1),
        ),
    )
    .addSubcommand((sub) =>
      sub
        .setName("queue")
        .setDescription("관리자: 등급 우선순위가 적용된 심사 대기 목록"),
    )
    .addSubcommand((sub) =>
      sub
        .setName("approve")
        .setDescription("신용 대출 신청을 승인합니다 (관리자)")
        .addIntegerOption((option) =>
          option
            .setName("loan_id")
            .setDescription("대출 ID")
            .setRequired(true)
            .setMinValue(1),
        ),
    )
    .addSubcommand((sub) =>
      sub
        .setName("collateral-approve")
        .setDescription("담보를 게임에서 확인하고 대출을 승인합니다 (관리자)")
        .addIntegerOption((option) =>
          option
            .setName("loan_id")
            .setDescription("담보 대출 신청 ID")
            .setRequired(true)
            .setMinValue(1),
        )
        .addIntegerOption((option) =>
          option
            .setName("verified_value")
            .setDescription("게임에서 확인한 담보 총 가치 (벨)")
            .setRequired(true)
            .setMinValue(1)
            .setMaxValue(2_147_483_647),
        ),
    )
    .addSubcommand((sub) =>
      sub
        .setName("collateral-return")
        .setDescription("상환 완료 담보를 돌려준 뒤 보관 기록을 해제합니다 (관리자)")
        .addIntegerOption((option) =>
          option
            .setName("loan_id")
            .setDescription("상환 완료한 담보 대출 ID")
            .setRequired(true)
            .setMinValue(1),
        )
        .addStringOption((option) => adminReason(option)),
    )
    .addSubcommand((sub) =>
      sub
        .setName("reject")
        .setDescription("대출 신청을 거절합니다 (관리자)")
        .addIntegerOption((option) =>
          option
            .setName("loan_id")
            .setDescription("대출 ID")
            .setRequired(true)
            .setMinValue(1),
        )
        .addStringOption((option) => adminReason(option)),
    ),
  new SlashCommandBuilder()
    .setName("credit")
    .setDescription("관리자: 신용점수를 설정합니다")
    .addSubcommand((sub) =>
      sub
        .setName("set")
        .setDescription("사용자 신용점수 변경 (0~100)")
        .addUserOption((option) => user(option))
        .addIntegerOption((option) =>
          option
            .setName("score")
            .setDescription("신용점수")
            .setRequired(true)
            .setMinValue(0)
            .setMaxValue(100),
        )
        .addStringOption((option) => adminReason(option)),
    ),
  new SlashCommandBuilder()
    .setName("tier-config")
    .setDescription("관리자: 등급별 대출·이자·보관 혜택 설정")
    .addSubcommand((sub) =>
      sub
        .setName("limit")
        .setDescription("플레티넘 이상 신용대출 추가 한도 (벨)")
        .addIntegerOption((option) =>
          option
            .setName("bonus")
            .setDescription("추가 한도 금액")
            .setRequired(true)
            .setMinValue(0)
            .setMaxValue(2_147_483_647),
        ),
    )
    .addSubcommand((sub) =>
      sub
        .setName("interest")
        .setDescription("VIP 예금 추가 일일 이자율 (%p)")
        .addNumberOption((option) =>
          option
            .setName("rate")
            .setDescription("기본 예금이자율에 더할 일일 %p")
            .setRequired(true)
            .setMinValue(0)
            .setMaxValue(100),
        ),
    )
    .addSubcommand((sub) =>
      sub
        .setName("storage")
        .setDescription("등급별 아이템 보관 한도 설정 (개수)")
        .addStringOption((option) =>
          option
            .setName("tier")
            .setDescription("대상 등급")
            .setRequired(true)
            .addChoices(
              { name: "브론즈", value: "bronze" },
              { name: "실버", value: "silver" },
              { name: "골드", value: "gold" },
              { name: "플레티넘", value: "platinum" },
              { name: "에이스", value: "ace" },
              { name: "VIP", value: "vip" },
            ),
        )
        .addIntegerOption((option) =>
          option
            .setName("capacity")
            .setDescription("보관 가능한 총 아이템 개수")
            .setRequired(true)
            .setMinValue(0)
            .setMaxValue(2_147_483_647),
        ),
    )
    .addSubcommand((sub) =>
      sub
        .setName("loan-term")
        .setDescription("신규 대출 기본 기간을 설정합니다 (일, 0=기간 없음)")
        .addIntegerOption((option) =>
          option
            .setName("days")
            .setDescription("기본 대출 기간")
            .setRequired(true)
            .setMinValue(0)
            .setMaxValue(3650),
        ),
    )
    .addSubcommand((sub) =>
      sub
        .setName("extension")
        .setDescription("1회 연장 기간과 대출별 최대 연장 횟수를 설정합니다")
        .addIntegerOption((option) =>
          option
            .setName("days")
            .setDescription("1회 연장 일수 (0=연장 비활성화)")
            .setRequired(true)
            .setMinValue(0)
            .setMaxValue(3650),
        )
        .addIntegerOption((option) =>
          option
            .setName("limit")
            .setDescription("대출별 최대 연장 횟수")
            .setRequired(true)
            .setMinValue(0)
            .setMaxValue(10),
        ),
    ),
  new SlashCommandBuilder()
    .setName("vault")
    .setDescription("은행에 맡긴 아이템을 확인하거나 관리자 인증 후 기록합니다")
    .addSubcommand((sub) =>
      sub.setName("list").setDescription("내 은행 보관 아이템 확인"),
    )
    .addSubcommand((sub) =>
      sub
        .setName("add")
        .setDescription("관리자: 게임에서 확인한 아이템을 은행에 보관")
        .addUserOption((option) => user(option))
        .addStringOption((option) =>
          option
            .setName("item")
            .setDescription("아이템·재료 이름")
            .setRequired(true)
            .setMaxLength(80),
        )
        .addIntegerOption((option) =>
          option
            .setName("quantity")
            .setDescription("확인된 수량")
            .setRequired(true)
            .setMinValue(1)
            .setMaxValue(2_147_483_647),
        )
        .addStringOption((option) => adminReason(option)),
    )
    .addSubcommand((sub) =>
      sub
        .setName("remove")
        .setDescription("관리자: 게임에서 반환한 아이템을 보관 기록에서 제거")
        .addUserOption((option) => user(option))
        .addStringOption((option) =>
          option
            .setName("item")
            .setDescription("아이템·재료 이름")
            .setRequired(true)
            .setMaxLength(80),
        )
        .addIntegerOption((option) =>
          option
            .setName("quantity")
            .setDescription("반환한 수량")
            .setRequired(true)
            .setMinValue(1)
            .setMaxValue(2_147_483_647),
        )
        .addStringOption((option) => adminReason(option)),
    ),
  new SlashCommandBuilder()
    .setName("bank-request")
    .setDescription("플레티넘 이상 은행 의뢰·관리자 처리")
    .addSubcommand((sub) =>
      sub
        .setName("submit")
        .setDescription("아이템·재료를 은행에 찾아달라고 요청합니다")
        .addStringOption((option) =>
          option
            .setName("item")
            .setDescription("찾아달라는 아이템·재료")
            .setRequired(true)
            .setMaxLength(80),
        )
        .addIntegerOption((option) =>
          option
            .setName("quantity")
            .setDescription("필요한 수량")
            .setRequired(true)
            .setMinValue(1)
            .setMaxValue(2_147_483_647),
        )
        .addStringOption((option) =>
          option
            .setName("note")
            .setDescription("추가 설명 (선택)")
            .setMaxLength(300),
        ),
    )
    .addSubcommand((sub) =>
      sub.setName("list").setDescription("내 은행 의뢰 현황"),
    )
    .addSubcommand((sub) =>
      sub
        .setName("queue")
        .setDescription("관리자: 진행 중인 은행 의뢰 목록"),
    )
    .addSubcommand((sub) =>
      sub
        .setName("update")
        .setDescription("관리자: 의뢰를 수락·거절·완료 처리합니다")
        .addIntegerOption((option) =>
          option
            .setName("request_id")
            .setDescription("의뢰 ID")
            .setRequired(true)
            .setMinValue(1),
        )
        .addStringOption((option) =>
          option
            .setName("status")
            .setDescription("변경할 상태")
            .setRequired(true)
            .addChoices(
              { name: "수락", value: "accepted" },
              { name: "거절", value: "declined" },
              { name: "구매·전달 완료", value: "fulfilled" },
            ),
        )
        .addStringOption((option) => adminReason(option)),
    ),
  new SlashCommandBuilder()
    .setName("stock")
    .setDescription("길드 가상주식 조회·주문")
    .addSubcommand((sub) => sub.setName("list").setDescription("상장 종목 목록"))
    .addSubcommand((sub) =>
      sub
        .setName("quote")
        .setDescription("종목 시세·발행 주식 수를 확인합니다")
        .addStringOption((option) => ticker(option)),
    )
    .addSubcommand((sub) =>
      sub
        .setName("buy")
        .setDescription("지정가 매수 주문을 냅니다")
        .addStringOption((option) => ticker(option))
        .addIntegerOption((option) =>
          option
            .setName("shares")
            .setDescription("매수 주식 수")
            .setRequired(true)
            .setMinValue(1)
            .setMaxValue(2_147_483_647),
        )
        .addIntegerOption((option) =>
          option
            .setName("limit_price")
            .setDescription("주당 최대 매수가 (기본재화)")
            .setRequired(true)
            .setMinValue(1)
            .setMaxValue(2_147_483_647),
        ),
    )
    .addSubcommand((sub) =>
      sub
        .setName("sell")
        .setDescription("보유 주식의 지정가 매도 주문을 냅니다")
        .addStringOption((option) => ticker(option))
        .addIntegerOption((option) =>
          option
            .setName("shares")
            .setDescription("매도 주식 수")
            .setRequired(true)
            .setMinValue(1)
            .setMaxValue(2_147_483_647),
        )
        .addIntegerOption((option) =>
          option
            .setName("limit_price")
            .setDescription("주당 최소 매도가 (기본재화)")
            .setRequired(true)
            .setMinValue(1)
            .setMaxValue(2_147_483_647),
        ),
    )
    .addSubcommand((sub) =>
      sub.setName("orders").setDescription("내 미체결 주문을 확인합니다"),
    )
    .addSubcommand((sub) =>
      sub
        .setName("cancel")
        .setDescription("내 미체결 주문을 취소합니다")
        .addIntegerOption((option) =>
          option
            .setName("order_id")
            .setDescription("주문 ID")
            .setRequired(true)
            .setMinValue(1),
        ),
    ),
  new SlashCommandBuilder()
    .setName("portfolio")
    .setDescription("내 가상주식 보유 현황과 평가액을 확인합니다"),
  new SlashCommandBuilder()
    .setName("currency")
    .setDescription("재화·환율·이자율을 조회하거나 관리합니다")
    .addSubcommand((sub) => sub.setName("list").setDescription("재화 목록 조회"))
    .addSubcommand((sub) =>
      sub
        .setName("create")
        .setDescription("재화를 생성하거나 설정을 갱신합니다 (관리자)")
        .addStringOption((option) =>
          option
            .setName("name")
            .setDescription("재화 이름")
            .setRequired(true)
            .setMaxLength(32),
        )
        .addStringOption((option) =>
          option
            .setName("symbol")
            .setDescription("기호")
            .setRequired(true)
            .setMaxLength(8),
        )
        .addNumberOption((option) =>
          option
            .setName("value")
            .setDescription("기본재화 기준 환전가치 (기본 1)")
            .setMinValue(0.000001)
            .setMaxValue(1_000_000),
        )
        .addNumberOption((option) =>
          option
            .setName("deposit_rate")
            .setDescription("일일 예금이자 % (기본 0)")
            .setMinValue(0)
            .setMaxValue(100),
        )
        .addNumberOption((option) =>
          option
            .setName("loan_rate")
            .setDescription("일일 대출이자 % (기본 0)")
            .setMinValue(0)
            .setMaxValue(100),
        ),
    )
    .addSubcommand((sub) =>
      sub
        .setName("setbase")
        .setDescription("기본재화를 지정합니다 (관리자)")
        .addStringOption((option) => currency(option)),
    )
    .addSubcommand((sub) =>
      sub
        .setName("setvalue")
        .setDescription("재화의 기본재화 기준 가치를 변경합니다 (관리자)")
        .addStringOption((option) => currency(option))
        .addNumberOption((option) =>
          option
            .setName("value")
            .setDescription("기본재화 기준 가치")
            .setRequired(true)
            .setMinValue(0.000001)
            .setMaxValue(1_000_000),
        ),
    )
    .addSubcommand((sub) =>
      sub
        .setName("setrate")
        .setDescription("일일 예금·대출 이자율을 변경합니다 (관리자)")
        .addStringOption((option) => currency(option))
        .addNumberOption((option) =>
          option
            .setName("deposit_rate")
            .setDescription("일일 예금이자 %")
            .setRequired(true)
            .setMinValue(0)
            .setMaxValue(100),
        )
        .addNumberOption((option) =>
          option
            .setName("loan_rate")
            .setDescription("일일 대출이자 %")
            .setRequired(true)
            .setMinValue(0)
            .setMaxValue(100),
        ),
    )
    .addSubcommand((sub) =>
      sub
        .setName("remove")
        .setDescription("재화를 비활성화합니다 (관리자)")
        .addStringOption((option) => currency(option))
        .addStringOption((option) => adminReason(option)),
    ),
  new SlashCommandBuilder()
    .setName("mint")
    .setDescription("관리자: 게임 내 인증을 마친 재화를 지급합니다 (확인 필요)")
    .addUserOption((option) => user(option))
    .addStringOption((option) => currency(option))
    .addIntegerOption((option) => amount(option))
    .addStringOption((option) => adminReason(option)),
  new SlashCommandBuilder()
    .setName("confiscate")
    .setDescription("관리자: 재화를 회수합니다 (확인 버튼 필요)")
    .addUserOption((option) => user(option))
    .addStringOption((option) => currency(option))
    .addIntegerOption((option) => amount(option))
    .addStringOption((option) => adminReason(option)),
  new SlashCommandBuilder()
    .setName("freeze")
    .setDescription("관리자: 계좌를 동결합니다")
    .addUserOption((option) => user(option))
    .addStringOption((option) => adminReason(option)),
  new SlashCommandBuilder()
    .setName("unfreeze")
    .setDescription("관리자: 계좌 동결을 해제합니다")
    .addUserOption((option) => user(option))
    .addStringOption((option) => adminReason(option)),
  new SlashCommandBuilder()
    .setName("supply")
    .setDescription("관리자: 재화의 전체 지갑·예금 공급량을 확인합니다")
    .addStringOption((option) => currency(option)),
  new SlashCommandBuilder()
    .setName("market")
    .setDescription("관리자: 가상주식 시장·평가·상장 관리")
    .addSubcommand((sub) =>
      sub
        .setName("create")
        .setDescription("길드 주식을 상장합니다")
        .addStringOption((option) =>
          option
            .setName("name")
            .setDescription("상장 길드 이름")
            .setRequired(true)
            .setMaxLength(60),
        )
        .addStringOption((option) =>
          option
            .setName("ticker")
            .setDescription("종목 티커 (영문·숫자)")
            .setRequired(true)
            .setMaxLength(12),
        )
        .addIntegerOption((option) =>
          option
            .setName("price")
            .setDescription("기준 주가 (기본재화)")
            .setRequired(true)
            .setMinValue(1)
            .setMaxValue(2_147_483_647),
        )
        .addIntegerOption((option) =>
          option
            .setName("initial_shares")
            .setDescription("초기 발행·유통 주식 수")
            .setRequired(true)
            .setMinValue(1)
            .setMaxValue(2_147_483_647),
        )
        .addUserOption((option) =>
          option.setName("holder").setDescription("초기 주식 보유자").setRequired(true),
        )
        .addStringOption((option) => adminReason(option)),
    )
    .addSubcommand((sub) =>
      sub
        .setName("remove")
        .setDescription("상장을 폐지하고 미체결 주문을 취소합니다")
        .addStringOption((option) => ticker(option))
        .addStringOption((option) => adminReason(option)),
    )
    .addSubcommand((sub) =>
      sub
        .setName("issue")
        .setDescription("주식을 신규 발행하여 보유자에게 지급합니다")
        .addStringOption((option) => ticker(option))
        .addUserOption((option) => user(option, "holder"))
        .addIntegerOption((option) =>
          option
            .setName("shares")
            .setDescription("발행 수량")
            .setRequired(true)
            .setMinValue(1)
            .setMaxValue(2_147_483_647),
        )
        .addStringOption((option) => adminReason(option)),
    )
    .addSubcommand((sub) =>
      sub
        .setName("burn")
        .setDescription("보유 주식을 소각합니다")
        .addStringOption((option) => ticker(option))
        .addUserOption((option) => user(option, "holder"))
        .addIntegerOption((option) =>
          option
            .setName("shares")
            .setDescription("소각 수량")
            .setRequired(true)
            .setMinValue(1)
            .setMaxValue(2_147_483_647),
        )
        .addStringOption((option) => adminReason(option)),
    )
    .addSubcommand((sub) =>
      sub
        .setName("evaluate")
        .setDescription("오늘의 점수와 근거를 등록합니다")
        .addStringOption((option) => ticker(option))
        .addIntegerOption((option) =>
          option
            .setName("content")
            .setDescription("게임 콘텐츠 성과: -6~6")
            .setRequired(true)
            .setMinValue(-6)
            .setMaxValue(6),
        )
        .addIntegerOption((option) =>
          option
            .setName("activity")
            .setDescription("길드 활동·이벤트: -6~6")
            .setRequired(true)
            .setMinValue(-6)
            .setMaxValue(6),
        )
        .addIntegerOption((option) =>
          option
            .setName("membership")
            .setDescription("인원 변동: -5~5")
            .setRequired(true)
            .setMinValue(-5)
            .setMaxValue(5),
        )
        .addIntegerOption((option) =>
          option
            .setName("events")
            .setDescription("주요 사건·이슈: -8~8")
            .setRequired(true)
            .setMinValue(-8)
            .setMaxValue(8),
        )
        .addIntegerOption((option) =>
          option
            .setName("growth")
            .setDescription("성장 가능성·지속성: -5~5")
            .setRequired(true)
            .setMinValue(-5)
            .setMaxValue(5),
        )
        .addIntegerOption((option) =>
          option
            .setName("influence")
            .setDescription("커뮤니티 영향력·평판: -5~5")
            .setRequired(true)
            .setMinValue(-5)
            .setMaxValue(5),
        )
        .addIntegerOption((option) =>
          option
            .setName("opinion")
            .setDescription("무작위 유저 여론: -5~5 (7명 의견 검토)")
            .setRequired(true)
            .setMinValue(-5)
            .setMaxValue(5),
        )
        .addStringOption((option) =>
          option
            .setName("evidence")
            .setDescription("확인된 근거·변동 사유")
            .setRequired(true)
            .setMaxLength(500),
        ),
    )
    .addSubcommand((sub) =>
      sub
        .setName("publish")
        .setDescription("오늘 평가와 새 주가를 공지합니다")
        .addStringOption((option) =>
          option
            .setName("ticker")
            .setDescription("종목 (생략하면 오늘 평가 전체 공지)"),
        ),
    )
    .addSubcommand((sub) =>
      sub.setName("news").setDescription("최근 시장 공지를 확인합니다"),
    )
    .addSubcommand((sub) =>
      sub
        .setName("channel")
        .setDescription("시세·뉴스 공지 채널을 설정합니다")
        .addChannelOption((option) =>
          option
            .setName("channel")
            .setDescription("공지할 텍스트 채널")
            .setRequired(true),
        ),
    )
    .addSubcommand((sub) =>
      sub
        .setName("note")
        .setDescription("확인된 시장 소식을 등록합니다")
        .addStringOption((option) =>
          option
            .setName("title")
            .setDescription("뉴스 제목")
            .setRequired(true)
            .setMaxLength(100),
        )
        .addStringOption((option) =>
          option
            .setName("content")
            .setDescription("확인된 사실과 분석을 구분해 작성")
            .setRequired(true)
            .setMaxLength(1000),
        )
        .addStringOption((option) =>
          option
            .setName("ticker")
            .setDescription("관련 종목 티커 (생략 가능)")
            .setMaxLength(12),
        ),
    )
    .addSubcommand((sub) =>
      sub
        .setName("officer-add")
        .setDescription("길드 관계자를 지정합니다 (종목별 최대 2명)")
        .addStringOption((option) => ticker(option))
        .addUserOption((option) => user(option, "officer")),
    )
    .addSubcommand((sub) =>
      sub
        .setName("officer-remove")
        .setDescription("길드 관계자 지정을 해제합니다")
        .addStringOption((option) => ticker(option))
        .addUserOption((option) => user(option, "officer")),
    ),
].map((command) => command.toJSON());
