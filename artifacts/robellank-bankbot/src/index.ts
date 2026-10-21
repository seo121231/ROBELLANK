import { randomUUID } from "node:crypto";
import {
  ActionRowBuilder,
  ButtonBuilder,
  ButtonStyle,
  ChannelType,
  Client,
  EmbedBuilder,
  Events,
  GatewayIntentBits,
  MessageFlags,
  PermissionFlagsBits,
  Routes,
  type ButtonInteraction,
  type ChatInputCommandInteraction,
  type TextChannel,
} from "discord.js";
import pino from "pino";
import { commands } from "./commands";
import * as store from "./store";

const logger = pino({ level: process.env.LOG_LEVEL ?? "info" });
const token = process.env.DISCORD_BOT_TOKEN;
if (!token) throw new Error("DISCORD_BOT_TOKEN Secret is required.");

type PendingAction =
  | {
      kind: "money";
      operation: "mint" | "confiscate";
      targetId: string;
      currency: string;
      amount: number;
      reason: string;
    }
  | { kind: "loan"; loanId: number; approve: boolean; reason?: string }
  | { kind: "currency-remove"; currency: string; reason: string }
  | {
      kind: "shares";
      operation: "issue" | "burn";
      ticker: string;
      holderId: string;
      shares: number;
      reason: string;
    }
  | { kind: "stock-remove"; ticker: string; reason: string };

const pendingActions = new Map<
  string,
  { userId: string; guildId: string; action: PendingAction; expiresAt: number }
>();

const client = new Client({ intents: [GatewayIntentBits.Guilds] });
let schedulerBusy = false;

const format = (value: string | number) =>
  new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 }).format(
    Number(value),
  );

const mention = (id: string) => `<@${id}>`;
const privateContent = (content: string) =>
  content.length <= 1900 ? content : `${content.slice(0, 1880)}\n…내용이 길어 일부를 생략했습니다.`;
const guildIdFrom = (interaction: ChatInputCommandInteraction) => {
  if (!interaction.guildId) throw new Error("서버 안에서만 사용할 수 있습니다.");
  return interaction.guildId;
};
const requireAdmin = (interaction: ChatInputCommandInteraction) => {
  if (!interaction.memberPermissions?.has(PermissionFlagsBits.Administrator)) {
    throw new Error("이 명령어는 서버 관리자만 사용할 수 있습니다.");
  }
};
const replyPrivate = (
  interaction: ChatInputCommandInteraction,
  content: string,
) =>
  interaction.reply({
    content: privateContent(content),
    flags: MessageFlags.Ephemeral,
  });

async function queueConfirmation(
  interaction: ChatInputCommandInteraction,
  action: PendingAction,
  summary: string,
) {
  const id = randomUUID();
  const guildId = guildIdFrom(interaction);
  for (const [pendingId, entry] of pendingActions) {
    if (entry.expiresAt < Date.now()) pendingActions.delete(pendingId);
  }
  pendingActions.set(id, {
    userId: interaction.user.id,
    guildId,
    action,
    expiresAt: Date.now() + 60_000,
  });
  const row = new ActionRowBuilder<ButtonBuilder>().addComponents(
    new ButtonBuilder()
      .setCustomId(`bank-confirm:${id}`)
      .setLabel("확인")
      .setStyle(ButtonStyle.Danger),
    new ButtonBuilder()
      .setCustomId(`bank-cancel:${id}`)
      .setLabel("취소")
      .setStyle(ButtonStyle.Secondary),
  );
  await interaction.reply({
    content: `${summary}\n실행 전 내용을 확인하세요. 60초 안에 확인 버튼을 눌러야 합니다.`,
    components: [row],
    flags: MessageFlags.Ephemeral,
  });
}

async function sendAnnouncement(
  guildId: string,
  content: string,
  embeds?: EmbedBuilder[],
) {
  const channelId = await store.getAnnouncementChannel(guildId);
  if (!channelId) return false;
  const channel = await client.channels.fetch(channelId).catch(() => null);
  if (!channel?.isTextBased() || !("send" in channel)) {
    logger.warn({ guildId, channelId }, "Market announcement channel is unavailable");
    return false;
  }
  try {
    const textChannel = channel as TextChannel;
    if (content.length <= 1900) {
      await textChannel.send({ content, embeds });
    } else {
      const chunks: string[] = [];
      let remaining = content;
      while (remaining.length > 1900) {
        let cut = remaining.lastIndexOf("\n", 1900);
        if (cut < 500) cut = 1900;
        chunks.push(remaining.slice(0, cut));
        remaining = remaining.slice(cut).trimStart();
      }
      chunks.push(remaining);
      for (let index = 0; index < chunks.length; index += 1) {
        await textChannel.send({
          content: chunks[index],
          embeds: index === 0 ? embeds : undefined,
        });
      }
    }
    return true;
  } catch (error) {
    logger.warn({ err: error, guildId, channelId }, "Market announcement failed");
    return false;
  }
}

async function handleConfirmation(interaction: ButtonInteraction) {
  const [kind, actionId] = interaction.customId.split(":");
  if (!actionId) return;
  const pending = pendingActions.get(actionId);
  if (!pending || pending.expiresAt < Date.now()) {
    pendingActions.delete(actionId);
    await interaction.update({
      content: "확인 시간이 지났습니다. 명령어를 다시 실행하세요.",
      components: [],
    });
    return;
  }
  if (pending.userId !== interaction.user.id) {
    await interaction.reply({
      content: "이 확인 버튼을 만든 사용자만 누를 수 있습니다.",
      flags: MessageFlags.Ephemeral,
    });
    return;
  }
  if (pending.guildId !== interaction.guildId) {
    await interaction.update({
      content: "서버 정보가 일치하지 않아 실행하지 않았습니다.",
      components: [],
    });
    pendingActions.delete(actionId);
    return;
  }
  if (!interaction.memberPermissions?.has(PermissionFlagsBits.Administrator)) {
    await interaction.update({
      content: "관리자 권한이 확인되지 않아 실행하지 않았습니다.",
      components: [],
    });
    pendingActions.delete(actionId);
    return;
  }
  pendingActions.delete(actionId);
  if (kind === "bank-cancel") {
    await interaction.update({ content: "취소했습니다.", components: [] });
    return;
  }

  await interaction.deferUpdate();
  try {
    const guildId = pending.guildId;
    const action = pending.action;
    let result = "완료했습니다.";
    if (action.kind === "money") {
      const currencyRow = await store.changeMoney(
        guildId,
        interaction.user.id,
        action.targetId,
        action.currency,
        action.amount,
        action.operation,
        action.reason,
      );
      result = `${action.operation === "mint" ? "발행 지급" : "몰수"} 완료: ${mention(action.targetId)} · ${format(action.amount)} ${currencyRow.symbol} · 사유: ${action.reason}`;
    } else if (action.kind === "loan") {
      const review = await store.reviewLoan(
        guildId,
        interaction.user.id,
        action.loanId,
        action.approve,
        action.reason,
      );
      result = `대출 #${review.loanId} ${review.approved ? "승인" : "거절"}을 완료했습니다.`;
    } else if (action.kind === "currency-remove") {
      const currencyRow = await store.removeCurrency(guildId, action.currency);
      result = `${currencyRow.name} 재화를 비활성화했습니다. 기록은 보존됩니다. 사유: ${action.reason}`;
    } else if (action.kind === "shares") {
      await store.alterShares(
        guildId,
        interaction.user.id,
        action.ticker,
        action.holderId,
        action.shares,
        action.operation,
        action.reason,
      );
      result = `${action.ticker} ${action.operation === "issue" ? "신규 발행" : "소각"} ${format(action.shares)}주 완료. ${mention(action.holderId)} · 사유: ${action.reason}`;
      await sendAnnouncement(guildId, result);
    } else if (action.kind === "stock-remove") {
      await store.removeStock(guildId, action.ticker, action.reason);
      result = `${action.ticker} 상장 폐지 완료. 주문은 취소했고 계좌·거래 기록은 보존했습니다.`;
      await sendAnnouncement(guildId, result);
    }
    await interaction.editReply({ content: result, components: [] });
  } catch (error) {
    const message = error instanceof Error ? error.message : "요청을 처리하지 못했습니다.";
    await interaction.editReply({ content: `처리하지 못했습니다: ${message}`, components: [] });
  }
}

function helpEmbed() {
  return new EmbedBuilder()
    .setColor(0x1f9d76)
    .setTitle("ROBELLANK 은행 봇 안내")
    .setDescription(
      [
        "계좌는 서버별로 관리되며, 거래·대출·주식 내역은 기록으로 보존됩니다.",
        "",
        "**기본·송금**",
        "`/register` 계좌 개설 · `/balance [user]` 잔액 · `/transfer user currency amount` 송금",
        "`/exchange from to amount` 환전 · `/history` 내역 · `/leaderboard currency` 순위",
        "`/currency list` 재화·환율·일일 이자율",
        "",
        "**예금·대출**",
        "`/deposit currency amount` 예금 · `/withdraw currency amount` 출금",
        "`/loan request currency amount` 신청 · `/loan repay loan_id amount` 상환 · `/loan list` 조회",
        "대출 신청은 관리자 승인 후 지급됩니다. 예금·대출 이자는 매일 한국 시간 자정에 계산됩니다.",
        "",
        "**길드 가상주식**",
        "`/stock list` 종목 · `/stock quote ticker` 시세 · `/stock buy ticker shares limit_price` 매수 주문",
        "`/stock sell ticker shares limit_price` 매도 주문 · `/stock orders` 주문 · `/stock cancel order_id` 취소",
        "`/portfolio` 보유 현황 · `/market news` 최근 공지",
        "주문은 유저 간 지정가로만 체결됩니다. 매수 수수료 0%, 매도 수수료 7.5%(정수 반올림)입니다.",
        "20:30 미체결 주문 취소, 20:30~21:00 평가, 21:00 새 시세 공지 후 거래를 재개합니다 (한국 시간).",
        "주가는 평가 점수 구간 안에서 변동하며 하루 최대 ±20%입니다. 주식은 이벤트용 가상자산이며 실제 소유권·현금 가치를 갖지 않습니다.",
        "",
        "**관리자**",
        "`/currency create|setbase|setvalue|setrate|remove` 재화 관리",
        "`/mint`, `/confiscate` 지급·몰수 (확인 버튼 필요) · `/freeze`, `/unfreeze`, `/supply`",
        "`/loan approve|reject` 대출 심사",
        "`/market create|remove|issue|burn|evaluate|publish|channel|note|officer-add|officer-remove`",
      ].join("\n"),
    )
    .setFooter({
      text: "상장 길드 주식은 실제 지분이 아닌 이벤트 콘텐츠입니다.",
    });
}

async function handleLoan(interaction: ChatInputCommandInteraction) {
  const guildId = guildIdFrom(interaction);
  const subcommand = interaction.options.getSubcommand();
  if (subcommand === "request") {
    const request = await store.createLoanRequest(
      guildId,
      interaction.user.id,
      interaction.options.getString("currency", true),
      interaction.options.getInteger("amount", true),
    );
    await replyPrivate(
      interaction,
      `대출 신청 #${request.loanId}을 접수했습니다. 관리자의 승인을 기다려 주세요.`,
    );
  } else if (subcommand === "repay") {
    const result = await store.repayLoan(
      guildId,
      interaction.user.id,
      interaction.options.getInteger("loan_id", true),
      interaction.options.getInteger("amount", true),
    );
    await replyPrivate(
      interaction,
      `${format(result.payment)} 상환했습니다. 남은 원리금: ${format(result.remaining)}.`,
    );
  } else if (subcommand === "list") {
    const rows = await store.listLoans(guildId, interaction.user.id);
    const description = rows.length
      ? rows
          .map(
            (loan) =>
              `#${loan.id} ${loan.currency} · 원금 ${format(loan.principal)} · 남은 원리금 ${format(loan.amount_due)} · 일 ${loan.rate}% · ${loan.status}`,
          )
          .join("\n")
      : "대출 내역이 없습니다.";
    await replyPrivate(interaction, description);
  } else if (subcommand === "approve" || subcommand === "reject") {
    requireAdmin(interaction);
    const loanId = interaction.options.getInteger("loan_id", true);
    const reason = interaction.options.getString("reason") ?? "";
    await queueConfirmation(
      interaction,
      {
        kind: "loan",
        loanId,
        approve: subcommand === "approve",
        reason,
      },
      `대출 #${loanId} 신청을 ${subcommand === "approve" ? "승인" : `거절합니다. 사유: ${reason}`}?`,
    );
  }
}

async function handleStock(interaction: ChatInputCommandInteraction) {
  const guildId = guildIdFrom(interaction);
  const subcommand = interaction.options.getSubcommand();
  if (subcommand === "list") {
    const rows = await store.listStocks(guildId);
    await replyPrivate(
      interaction,
      rows.length
        ? rows
            .map(
              (stock) =>
                `**${stock.ticker}** ${stock.name} · ${format(stock.current_price)} · 유통 ${format(stock.total_shares)}주`,
            )
            .join("\n")
        : "상장 종목이 없습니다.",
    );
  } else if (subcommand === "quote") {
    const stock = await store.quoteStock(
      guildId,
      interaction.options.getString("ticker", true),
    );
    const evaluation = stock.evaluation as
      | {
          final_score: number;
          change_percent: number;
          old_price: number;
          new_price: number;
          evidence: string;
        }
      | undefined;
    const embed = new EmbedBuilder()
      .setColor(0x207e66)
      .setTitle(`${stock.name} (${stock.ticker})`)
      .addFields(
        { name: "기준 주가", value: `${format(stock.current_price)} 기본재화`, inline: true },
        { name: "발행·유통 주식", value: `${format(stock.total_shares)}주`, inline: true },
        {
          name: "최근 평가",
          value: evaluation
            ? `${evaluation.final_score}점 · ${evaluation.change_percent >= 0 ? "+" : ""}${evaluation.change_percent}%\n${evaluation.evidence}`
            : "아직 발표된 평가가 없습니다.",
        },
      );
    await interaction.reply({ embeds: [embed], flags: MessageFlags.Ephemeral });
  } else if (subcommand === "buy" || subcommand === "sell") {
    const result = await store.placeOrder(
      guildId,
      interaction.user.id,
      interaction.options.getString("ticker", true),
      subcommand,
      interaction.options.getInteger("shares", true),
      interaction.options.getInteger("limit_price", true),
    );
    const message =
      `주문 #${result.orderId} 접수: ${result.stock.ticker} ${format(interaction.options.getInteger("shares", true))}주 ${subcommand === "buy" ? "매수" : "매도"}. ` +
      `즉시 체결 ${format(result.filled)}주 · 미체결 ${format(result.remaining)}주.`;
    await replyPrivate(interaction, message);
  } else if (subcommand === "orders") {
    const rows = await store.listOrders(guildId, interaction.user.id);
    await replyPrivate(
      interaction,
      rows.length
        ? rows
            .map(
              (order) =>
                `#${order.id} ${order.ticker} ${order.side === "buy" ? "매수" : "매도"} · ${format(order.limit_price)} × ${format(order.remaining)}/${format(order.quantity)}주`,
            )
            .join("\n")
        : "미체결 주문이 없습니다.",
    );
  } else if (subcommand === "cancel") {
    const orderId = interaction.options.getInteger("order_id", true);
    const order = await store.cancelOrder(guildId, interaction.user.id, orderId);
    await replyPrivate(
      interaction,
      `주문 #${orderId}을 취소했습니다.${order.side === "buy" ? ` 확보해 둔 ${format(order.remaining * order.limit_price)}을 지갑으로 돌려드렸습니다.` : ""}`,
    );
  }
}

async function handleCurrency(interaction: ChatInputCommandInteraction) {
  const guildId = guildIdFrom(interaction);
  const subcommand = interaction.options.getSubcommand();
  if (subcommand === "list") {
    const rows = await store.listCurrencies(guildId);
    await replyPrivate(
      interaction,
      rows
        .map(
          (row) =>
            `**${row.name}** (${row.symbol}) · ${row.is_base ? "기본재화" : `가치 ${row.exchange_value}`} · 예금 일 ${row.deposit_rate}% · 대출 일 ${row.loan_rate}%`,
        )
        .join("\n"),
    );
    return;
  }
  requireAdmin(interaction);
  const name = interaction.options.getString("currency") ?? "";
  if (subcommand === "create") {
    const result = await store.createCurrency(guildId, {
      name: interaction.options.getString("name", true),
      symbol: interaction.options.getString("symbol", true),
      value: interaction.options.getNumber("value") ?? 1,
      depositRate: interaction.options.getNumber("deposit_rate") ?? 0,
      loanRate: interaction.options.getNumber("loan_rate") ?? 0,
    });
    await replyPrivate(
      interaction,
      `${result.name} (${result.symbol}) 재화를 생성/수정했습니다. 기준 가치 ${result.exchange_value}, 예금 일 ${result.deposit_rate}%, 대출 일 ${result.loan_rate}%.`,
    );
  } else if (subcommand === "setbase") {
    const result = await store.setBaseCurrency(
      guildId,
      interaction.options.getString("currency", true),
    );
    await replyPrivate(interaction, `${result.name}을 기본재화로 지정했습니다.`);
  } else if (subcommand === "setvalue") {
    const result = await store.setCurrencyValue(
      guildId,
      interaction.options.getString("currency", true),
      interaction.options.getNumber("value", true),
    );
    await replyPrivate(
      interaction,
      `${result.name} 환전가치를 기본재화 ${result.exchange_value}로 변경했습니다.`,
    );
  } else if (subcommand === "setrate") {
    const result = await store.setCurrencyRates(
      guildId,
      interaction.options.getString("currency", true),
      interaction.options.getNumber("deposit_rate", true),
      interaction.options.getNumber("loan_rate", true),
    );
    await replyPrivate(
      interaction,
      `${result.name}의 일일 예금·대출 이자율을 변경했습니다.`,
    );
  } else if (subcommand === "remove") {
    const currency = interaction.options.getString("currency", true);
    const reason = interaction.options.getString("reason", true);
    await queueConfirmation(
      interaction,
      { kind: "currency-remove", currency, reason },
      `${currency} 재화를 비활성화합니다. 잔액·대출이 없어야 하며 기록은 삭제되지 않습니다. 사유: ${reason}`,
    );
  }
}

async function handleMarket(interaction: ChatInputCommandInteraction) {
  const guildId = guildIdFrom(interaction);
  const subcommand = interaction.options.getSubcommand();
  if (subcommand === "news") {
    const rows = await store.recentNews(guildId);
    await replyPrivate(
      interaction,
      rows.length
        ? rows
            .map(
              (item) =>
                `**${item.ticker ? `${item.ticker} · ` : ""}${item.title}**\n${item.content}`,
            )
            .join("\n\n")
        : "등록된 시장 공지가 없습니다.",
    );
    return;
  }
  requireAdmin(interaction);
  if (subcommand === "create") {
    const result = await store.createStock(
      guildId,
      interaction.user.id,
      interaction.options.getString("name", true),
      interaction.options.getString("ticker", true),
      interaction.options.getInteger("price", true),
      interaction.options.getInteger("initial_shares", true),
      interaction.options.getUser("holder", true).id,
      interaction.options.getString("reason", true),
    );
    const message = `${result.ticker} 신규 상장: 기준 주가 ${format(result.price)}, 초기 유통 ${format(result.initialShares)}주.`;
    await replyPrivate(interaction, message);
    await sendAnnouncement(guildId, message);
  } else if (subcommand === "remove") {
    const tickerValue = interaction.options.getString("ticker", true);
    const reason = interaction.options.getString("reason", true);
    await queueConfirmation(
      interaction,
      { kind: "stock-remove", ticker: tickerValue, reason },
      `${tickerValue} 상장을 폐지하고 미체결 주문을 취소합니다. 보유 주식과 거래 기록은 삭제되지 않습니다. 사유: ${reason}`,
    );
  } else if (subcommand === "issue" || subcommand === "burn") {
    const tickerValue = interaction.options.getString("ticker", true);
    const holderId = interaction.options.getUser("holder", true).id;
    const shares = interaction.options.getInteger("shares", true);
    const reason = interaction.options.getString("reason", true);
    await queueConfirmation(
      interaction,
      {
        kind: "shares",
        operation: subcommand,
        ticker: tickerValue,
        holderId,
        shares,
        reason,
      },
      `${tickerValue} ${subcommand === "issue" ? "신규 발행" : "소각"} ${format(shares)}주, 보유자 ${mention(holderId)}. 변경 사유와 수량을 확인하세요: ${reason}`,
    );
  } else if (subcommand === "evaluate") {
    const result = await store.saveEvaluation(
      guildId,
      interaction.user.id,
      interaction.options.getString("ticker", true),
      {
        content: interaction.options.getInteger("content", true),
        activity: interaction.options.getInteger("activity", true),
        membership: interaction.options.getInteger("membership", true),
        events: interaction.options.getInteger("events", true),
        growth: interaction.options.getInteger("growth", true),
        influence: interaction.options.getInteger("influence", true),
        opinion: interaction.options.getInteger("opinion", true),
        evidence: interaction.options.getString("evidence", true),
      },
      store.todayKst(),
    );
    const change =
      result.change_percent >= 0
        ? `+${result.change_percent}`
        : `${result.change_percent}`;
    await replyPrivate(
      interaction,
      `${result.stock.ticker} 오늘 평가 저장: 기본 ${result.base_score}점, 무작위 ${result.random_score >= 0 ? "+" : ""}${result.random_score}점, 최종 ${result.final_score}점. 변동률 ${change}% (주가 ${format(result.old_price)} → ${format(result.new_price)}). 21:00에 공지됩니다.`,
    );
  } else if (subcommand === "publish") {
    const tickerValue = interaction.options.getString("ticker") ?? undefined;
    const reports = await store.publishEvaluations(
      guildId,
      store.todayKst(),
      tickerValue,
    );
    const lines = reports.map(
      (report) =>
        `**${report.ticker}** ${format(report.old_price)} → ${format(report.new_price)} (${report.change_percent >= 0 ? "+" : ""}${report.change_percent}%) · 최종 ${report.final_score}점 · ${report.evidence}`,
    );
    const content = `오늘 가상주식 시세 발표\n${lines.join("\n")}`;
    await replyPrivate(interaction, content);
    await sendAnnouncement(guildId, content);
  } else if (subcommand === "channel") {
    const channel = interaction.options.getChannel("channel", true);
    if (channel.type !== ChannelType.GuildText) {
      throw new Error("텍스트 채널을 선택하세요.");
    }
    await store.setAnnouncementChannel(guildId, channel.id);
    await replyPrivate(interaction, `시세·뉴스 공지 채널을 ${channel}로 설정했습니다.`);
  } else if (subcommand === "note") {
    const tickerValue = interaction.options.getString("ticker") ?? undefined;
    const title = interaction.options.getString("title", true);
    const content = interaction.options.getString("content", true);
    const stock = await store.addMarketNews(
      guildId,
      interaction.user.id,
      title,
      content,
      tickerValue,
    );
    const message = `**[시장 뉴스${stock.ticker ? ` · ${stock.ticker}` : ""}] ${title}**\n${content}`;
    await replyPrivate(interaction, "시장을 공지했습니다.");
    await sendAnnouncement(guildId, message);
  } else if (subcommand === "officer-add") {
    const stock = await store.addOfficer(
      guildId,
      interaction.options.getString("ticker", true),
      interaction.options.getUser("officer", true).id,
    );
    await replyPrivate(
      interaction,
      `${stock.ticker} 관계자를 지정했습니다. 종목별 최대 2명이며 해당 관계자는 소속 종목 평가에서 제외됩니다.`,
    );
  } else if (subcommand === "officer-remove") {
    const stock = await store.removeOfficer(
      guildId,
      interaction.options.getString("ticker", true),
      interaction.options.getUser("officer", true).id,
    );
    await replyPrivate(interaction, `${stock.ticker} 관계자 지정을 해제했습니다.`);
  }
}

async function handleCommand(interaction: ChatInputCommandInteraction) {
  const guildId = guildIdFrom(interaction);
  switch (interaction.commandName) {
    case "register": {
      const result = await store.registerAccount(guildId, interaction.user.id);
      await replyPrivate(
        interaction,
        `계좌가 준비되었습니다. 기본재화는 ${result.currency.name}입니다. 지갑 잔액은 0이며, 서버 관리자에게 문의해 재화를 받을 수 있습니다.`,
      );
      break;
    }
    case "help":
      await interaction.reply({
        embeds: [helpEmbed()],
        flags: MessageFlags.Ephemeral,
      });
      break;
    case "balance": {
      const user = interaction.options.getUser("user") ?? interaction.user;
      const balances = await store.getBalances(guildId, user.id);
      const lines = balances.map(
        (row) =>
          `**${row.name}** (${row.symbol}) · 지갑 ${format(row.wallet ?? 0)} · 예금 ${format(row.deposit ?? 0)}`,
      );
      await interaction.reply({
        content: `${mention(user.id)} 잔액\n${lines.join("\n") || "잔액이 없습니다."}`,
        flags: MessageFlags.Ephemeral,
      });
      break;
    }
    case "transfer": {
      const recipient = interaction.options.getUser("user", true);
      const currency = interaction.options.getString("currency", true);
      const amount = interaction.options.getInteger("amount", true);
      const currencyRow = await store.transfer(
        guildId,
        interaction.user.id,
        recipient.id,
        currency,
        amount,
      );
      await replyPrivate(
        interaction,
        `${mention(recipient.id)}에게 ${format(amount)} ${currencyRow.symbol} 송금했습니다.`,
      );
      break;
    }
    case "exchange": {
      const result = await store.exchange(
        guildId,
        interaction.user.id,
        interaction.options.getString("from", true),
        interaction.options.getString("to", true),
        interaction.options.getInteger("amount", true),
      );
      await replyPrivate(
        interaction,
        `${format(interaction.options.getInteger("amount", true))} ${result.from.symbol} → ${format(result.received)} ${result.to.symbol} 환전했습니다. 소수점 이하 결과는 버림 처리됩니다.`,
      );
      break;
    }
    case "history": {
      const rows = await store.recentHistory(guildId, interaction.user.id);
      await replyPrivate(
        interaction,
        rows.length
          ? rows
              .map(
                (row) =>
                  `<t:${Math.floor(new Date(row.created_at).getTime() / 1000)}:R> · ${row.description || row.type} · ${format(row.amount)} ${row.currency}${Number(row.fee) ? ` (수수료 ${format(row.fee)})` : ""}`,
              )
              .join("\n")
          : "거래 내역이 없습니다.",
      );
      break;
    }
    case "leaderboard": {
      const result = await store.leaderboard(
        guildId,
        interaction.options.getString("currency", true),
      );
      const rows = result.rows.map(
        (row: { discord_user_id: string; total: string }, index: number) =>
          `${index + 1}. ${mention(row.discord_user_id)} · ${format(row.total)} ${result.currency.symbol}`,
      );
      await interaction.reply({
        content: `**${result.currency.name} 부자 순위**\n${rows.join("\n") || "등록된 계좌가 없습니다."}`,
        flags: MessageFlags.Ephemeral,
      });
      break;
    }
    case "deposit":
    case "withdraw": {
      const operation = interaction.commandName === "deposit" ? "deposit" : "withdraw";
      const currency = interaction.options.getString("currency", true);
      const amount = interaction.options.getInteger("amount", true);
      const currencyRow = await store.moveDeposit(
        guildId,
        interaction.user.id,
        currency,
        amount,
        operation,
      );
      await replyPrivate(
        interaction,
        `${format(amount)} ${currencyRow.symbol}을 ${operation === "deposit" ? "예금했습니다. 이자는 매일 한국 시간 자정에 반영됩니다." : "예금에서 지갑으로 옮겼습니다."}`,
      );
      break;
    }
    case "loan":
      await handleLoan(interaction);
      break;
    case "stock":
      await handleStock(interaction);
      break;
    case "portfolio": {
      const rows = await store.portfolio(guildId, interaction.user.id);
      await replyPrivate(
        interaction,
        rows.length
          ? rows
              .map(
                (row) =>
                  `**${row.ticker}** ${row.name} · ${format(row.shares)}주 × ${format(row.current_price)} = ${format(row.market_value)}${row.listed ? "" : " · 상장 폐지"}`,
              )
              .join("\n")
          : "보유 중인 가상주식이 없습니다.",
      );
      break;
    }
    case "currency":
      await handleCurrency(interaction);
      break;
    case "mint":
    case "confiscate": {
      requireAdmin(interaction);
      const operation = interaction.commandName;
      const target = interaction.options.getUser("user", true);
      const currency = interaction.options.getString("currency", true);
      const amount = interaction.options.getInteger("amount", true);
      const reason = interaction.options.getString("reason", true);
      await queueConfirmation(
        interaction,
        { kind: "money", operation, targetId: target.id, currency, amount, reason },
        `${mention(target.id)} ${format(amount)} ${currency} ${operation === "mint" ? "발행 지급" : "몰수"} · 사유: ${reason}`,
      );
      break;
    }
    case "freeze":
    case "unfreeze": {
      requireAdmin(interaction);
      const target = interaction.options.getUser("user", true);
      const frozen = interaction.commandName === "freeze";
      await store.setFrozen(
        guildId,
        interaction.user.id,
        target.id,
        frozen,
        interaction.options.getString("reason", true),
      );
      await replyPrivate(
        interaction,
        `${mention(target.id)} 계좌를 ${frozen ? "동결했습니다. 미체결 주문은 취소됩니다." : "해제했습니다."}`,
      );
      break;
    }
    case "supply": {
      requireAdmin(interaction);
      const result = await store.getSupply(
        guildId,
        interaction.options.getString("currency", true),
      );
      await replyPrivate(
        interaction,
        `${result.currency.name} 통화량: ${format(result.total)} ${result.currency.symbol} (전체 계좌의 지갑 + 예금 합계).`,
      );
      break;
    }
    case "market":
      await handleMarket(interaction);
      break;
  }
}

client.once(Events.ClientReady, async (readyClient) => {
  logger.info({ botUser: readyClient.user.tag }, "ROBELLANK bank bot connected");
  try {
    await readyClient.rest.put(
      Routes.applicationCommands(readyClient.user.id),
      { body: commands },
    );
    logger.info({ commandCount: commands.length }, "Discord slash commands registered");
    for (const guild of readyClient.guilds.cache.values()) {
      await store.ensureGuild(guild.id);
    }
  } catch (error) {
    logger.error({ err: error }, "Bot setup failed");
  }
});

client.on(Events.GuildCreate, (guild) => {
  void store.ensureGuild(guild.id).catch((error) => {
    logger.error({ err: error, guildId: guild.id }, "Could not initialize guild");
  });
});

client.on(Events.InteractionCreate, async (interaction) => {
  try {
    if (interaction.isButton()) {
      if (
        interaction.customId.startsWith("bank-confirm:") ||
        interaction.customId.startsWith("bank-cancel:")
      ) {
        await handleConfirmation(interaction);
      }
      return;
    }
    if (interaction.isChatInputCommand()) {
      await handleCommand(interaction);
    }
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "요청을 처리하지 못했습니다.";
    logger.warn(
      {
        err: error,
        command: interaction.isChatInputCommand()
          ? interaction.commandName
          : "button",
        guildId: interaction.guildId,
      },
      "Bank bot request failed",
    );
    if (!interaction.isRepliable()) return;
    if (interaction.deferred || interaction.replied) {
      await interaction.followUp({
        content: `처리하지 못했습니다: ${message}`,
        flags: MessageFlags.Ephemeral,
      });
    } else {
      await interaction.reply({
        content: `처리하지 못했습니다: ${message}`,
        flags: MessageFlags.Ephemeral,
      });
    }
  }
});

setInterval(() => {
  if (schedulerBusy || !client.isReady()) return;
  schedulerBusy = true;
  const minute = store.kstMinuteOfDay();
  const date = store.todayKst();
  void store
    .runMarketScheduler(
      client.guilds.cache.map((guild) => guild.id),
      date,
      minute,
    )
    .then(async (events) => {
      for (const event of events) {
        if (event.stage === "close") {
          await sendAnnouncement(
            event.guildId,
            `오늘 거래가 마감되었습니다. 미체결 주문 ${format(event.count)}건을 취소했습니다. 21:00 시세 발표 후 거래를 재개합니다.`,
          );
        } else if (event.stage === "publish" && event.count > 0) {
          const news = await store.recentNews(event.guildId);
          const published = news.filter((item) =>
            String(item.title).includes("일일 시세"),
          );
          const content = published
            .map((item) => `**${item.title}**\n${item.content}`)
            .join("\n\n");
          if (content) await sendAnnouncement(event.guildId, content);
        }
      }
    })
    .catch((error) => logger.error({ err: error }, "Market scheduler failed"))
    .finally(() => {
      schedulerBusy = false;
    });
}, 30_000);

client.login(token).catch((error) => {
  logger.error({ err: error }, "Discord login failed");
  process.exitCode = 1;
});
