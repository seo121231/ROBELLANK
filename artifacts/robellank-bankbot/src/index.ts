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
  type GuildMemberRoleManager,
  type TextChannel,
} from "discord.js";
import pino from "pino";
import { commands } from "./commands";
import { getCreditAdjustment } from "./credit-adjustments";
import * as store from "./store";
import { getTier, resolveTier, tierAtLeast } from "./tiers";
import type { TierKey } from "./tiers";

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
  | {
      kind: "loan";
      loanId: number;
      approve: boolean;
      reason?: string;
      verifiedCollateralValue?: number;
    }
  | { kind: "collateral-return"; loanId: number; reason: string }
  | {
      kind: "vault";
      operation: "add" | "remove";
      targetId: string;
      itemName: string;
      quantity: number;
      reason: string;
    }
  | {
      kind: "bank-request";
      requestId: number;
      status: "accepted" | "declined" | "fulfilled";
      reason: string;
    }
  | { kind: "currency-remove"; currency: string; reason: string }
  | {
      kind: "shares";
      operation: "issue" | "burn";
      stockName: string;
      holderId: string;
      shares: number;
      reason: string;
    }
  | { kind: "stock-remove"; stockName: string; reason: string };

const pendingActions = new Map<
  string,
  { userId: string; guildId: string; action: PendingAction; expiresAt: number }
>();

const client = new Client({ intents: [GatewayIntentBits.Guilds] });
let schedulerBusy = false;

const format = (value: string | number | bigint) => {
  const formattedValue =
    typeof value === "string" && /^-?\d+$/.test(value)
      ? BigInt(value)
      : Number(value);
  return new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 }).format(
    formattedValue,
  );
};
const signed = (value: number) => `${value > 0 ? "+" : ""}${value}`;
const formatKstDate = (value: string | Date) =>
  new Intl.DateTimeFormat("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(new Date(value));

const mention = (id: string) => `<@${id}>`;
const tierRequirements: Record<TierKey, string> = {
  bronze: "기본 등급",
  silver: "캐릭터 50레벨 이상 · 리더보드 25레벨 이상 · 신용점수 40점 이상",
  gold: "캐릭터 75레벨 이상 · 리더보드 50레벨 이상 · 계좌·재화 인증 완료 · 신용점수 50점 이상",
  platinum: "캐릭터 150레벨 이상 · 25만 벨 이상 저축 · 리더보드 85레벨 이상 · 다수의 은행 이용 · 신용점수 60점 이상 (또는 서버 인원 25명 이상인 길드장)",
  ace: "캐릭터 200레벨 이상 · 리더보드 120레벨 이상 · 신용점수 70점 이상",
  vip: "캐릭터 250레벨 이상 · 리더보드 150레벨 이상 · 신용점수 80점 이상",
};
const privateContent = (content: string) =>
  content.length <= 1900 ? content : `${content.slice(0, 1880)}\n…내용이 길어 일부를 생략했습니다.`;
const guildIdFrom = (interaction: ChatInputCommandInteraction) => {
  if (!interaction.guildId) throw new Error("서버 안에서만 사용할 수 있습니다.");
  return interaction.guildId;
};
const tierFromInteraction = (interaction: ChatInputCommandInteraction) => {
  const roles = interaction.member?.roles;
  if (Array.isArray(roles)) return resolveTier(roles);
  if (roles && typeof roles === "object" && "cache" in roles) {
    return resolveTier(
      [...(roles as GuildMemberRoleManager).cache.keys()],
    );
  }
  return resolveTier([]);
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
        action.verifiedCollateralValue,
      );
      result = `대출 #${review.loanId} ${review.approved ? "승인" : "거절"}을 완료했습니다.`;
    } else if (action.kind === "collateral-return") {
      const returned = await store.returnCollateral(
        guildId,
        interaction.user.id,
        action.loanId,
        action.reason,
      );
      result = `대출 #${action.loanId} 담보 반환을 기록했습니다: ${returned.itemName} ${format(returned.quantity ?? 0)}개 · ${mention(returned.discordUserId)}.`;
    } else if (action.kind === "vault") {
      await store.adjustVault(
        guildId,
        interaction.user.id,
        action.targetId,
        action.itemName,
        action.quantity,
        action.operation,
        action.reason,
      );
      result = `${mention(action.targetId)} 은행 보관 아이템 ${action.operation === "add" ? "입고" : "반환"} 기록 완료: ${action.itemName} ${format(action.quantity)}개 · 사유: ${action.reason}`;
    } else if (action.kind === "bank-request") {
      const request = await store.updateBankItemRequest(
        guildId,
        interaction.user.id,
        action.requestId,
        action.status,
        action.reason,
      );
      result = `은행 의뢰 #${request.id} 상태를 ${action.status}로 변경했습니다. ${mention(request.discord_user_id)} · ${request.item_name} ${format(request.quantity)}개 · 사유: ${action.reason}`;
    } else if (action.kind === "currency-remove") {
      const currencyRow = await store.removeCurrency(guildId, action.currency);
      result = `${currencyRow.name} 재화를 비활성화했습니다. 기록은 보존됩니다. 사유: ${action.reason}`;
    } else if (action.kind === "shares") {
      await store.alterShares(
        guildId,
        interaction.user.id,
        action.stockName,
        action.holderId,
        action.shares,
        action.operation,
        action.reason,
      );
      result = `${action.stockName} ${action.operation === "issue" ? "신규 발행" : "소각"} ${format(action.shares)}주 완료. ${mention(action.holderId)} · 사유: ${action.reason}`;
      await sendAnnouncement(guildId, result);
    } else if (action.kind === "stock-remove") {
      await store.removeStock(guildId, action.stockName, action.reason);
      result = `${action.stockName} 상장 폐지 완료. 주문은 취소했고 계좌·거래 기록은 보존했습니다.`;
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
        "`/currency list` 재화·환율·일일 이자율 · `/tier` 등급과 혜택 · `/vault list` 보관 아이템",
        "",
        "**예금·대출**",
        "`/deposit currency amount` 예금 · `/withdraw currency amount` 출금",
        "`/loan request currency amount` 신용 대출 · `/loan collateral-request item quantity amount` 담보 대출",
        "`/loan repay loan_id amount` 상환 · `/loan extend loan_id` 연장 · `/loan list` 조회",
        "골드부터 신용 대출(신용점수 1점당 10,000벨), 실버부터 담보 대출과 연장이 가능합니다. 관리자 승인 후 지급되며, 담보는 게임에서 확인합니다.",
        "VIP는 관리자가 설정한 추가 예금 이자를 받습니다. 등급 역할은 서버 관리자가 직접 부여하며 봇은 역할을 변경하지 않습니다.",
        "신규 계좌 신용점수는 50점입니다. 은행 이용·규정 준수에 따른 점수는 관리자가 `/credit adjust`에서 사유를 선택해 반영합니다.",
        "서버 인원 25명 이상(봇 제외)인 길드장은 플래티넘으로 시작하며, 동맹 길드장은 원하는 2명을 골드로 시작할 수 있습니다. 역할 부여는 관리자 담당입니다.",
        "예금·대출 이자는 매일 한국 시간 자정에 계산됩니다.",
        "",
        "**길드 가상주식**",
        "`/stock list` 종목 목록 · `/stock quote stock` 상세 정보 · `/stock buy stock shares limit_price` 매수",
        "`/stock sell stock shares limit_price` 매도 · `/stock orders` 주문 현황 · `/stock cancel order_id` 취소",
        "`/portfolio` 보유 현황 · `/market news` 최근 공지",
        "종목은 티커 없이 이름으로 찾습니다. 상세 정보에는 기준가, 시가총액, 최고 매수·매도 호가, 최근 체결, 세부 평가가 표시됩니다.",
        "주문은 유저 간 지정가로만 체결됩니다. 현재 기준가는 참고값이며 실제 체결가는 매칭된 주문 가격입니다. 매수 수수료 0%, 매도 수수료 7.5%(정수 반올림)입니다.",
        "20:30 미체결 주문 취소, 20:30~21:00 평가, 21:00 새 시세 공지 후 거래를 재개합니다 (한국 시간).",
        "주가는 평가 점수 구간 안에서 변동하며 하루 최대 ±20%입니다. 주식은 이벤트용 가상자산이며 실제 소유권·현금 가치를 갖지 않습니다.",
        "",
        "**관리자**",
        "`/currency create|setbase|setvalue|setrate|remove` 재화 관리",
        "`/mint` 게임 내 확인을 마친 재화 지급 · `/confiscate` 회수 (확인 버튼 필요)",
        "`/credit adjust` 사유별 신용점수 조정 · `/credit set` 재량 점수 설정 · `/tier-config` 한도·이자·보관·대출기간 설정",
        "`/vault add|remove` 게임에서 확인한 보관 아이템 기록 · `/freeze`, `/unfreeze`, `/supply`",
        "`/loan queue|approve|collateral-approve|collateral-return|reject` 대출 심사",
        "`/market create|describe|remove|issue|burn|evaluate|publish|channel|note|officer-add|officer-remove`",
      ].join("\n"),
    )
    .setFooter({
      text: "상장 길드 주식은 실제 지분이 아닌 이벤트 콘텐츠입니다.",
    });
}

async function handleLoan(
  interaction: ChatInputCommandInteraction,
  tierKey: TierKey,
) {
  const guildId = guildIdFrom(interaction);
  const subcommand = interaction.options.getSubcommand();
  if (subcommand === "request") {
    const request = await store.createCreditLoanRequest(
      guildId,
      interaction.user.id,
      interaction.options.getString("currency", true),
      interaction.options.getInteger("amount", true),
      tierKey,
    );
    await replyPrivate(
      interaction,
      `신용 대출 신청 #${request.loanId}을 접수했습니다. 총 한도 ${format(request.creditLimit)}벨, 승인 대기 포함 남은 한도 ${format(request.available)}벨입니다. 관리자 승인을 기다려 주세요.`,
    );
  } else if (subcommand === "collateral-request") {
    const request = await store.createCollateralLoanRequest(
      guildId,
      interaction.user.id,
      interaction.options.getString("item", true),
      interaction.options.getInteger("quantity", true),
      interaction.options.getInteger("amount", true),
      tierKey,
    );
    await replyPrivate(
      interaction,
      `담보 대출 신청 #${request.loanId}을 접수했습니다. 관리자가 게임에서 아이템과 로벨 상단 가치표 기준 가치를 확인한 뒤 승인합니다.`,
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
            (loan: {
              id: number;
              currency: string;
              principal: string;
              amount_due: string;
              rate: string;
              status: string;
              loan_type: string;
              collateral_item: string | null;
              collateral_quantity: number | null;
              collateral_value: string | null;
              collateral_status: string;
              due_at: Date | null;
              extension_count: number;
            }) => {
              const type = loan.loan_type === "collateral" ? "담보" : "신용";
              const collateral =
                loan.loan_type === "collateral"
                  ? ` · ${loan.collateral_item} ${format(loan.collateral_quantity ?? 0)}개 · 확인 가치 ${format(loan.collateral_value ?? 0)}벨 · 담보 ${loan.collateral_status}`
                  : "";
              const due = loan.due_at
                ? ` · 만기 <t:${Math.floor(new Date(loan.due_at).getTime() / 1000)}:d> · 연장 ${loan.extension_count}회`
                : "";
              return `#${loan.id} ${type} · 원금 ${format(loan.principal)} · 남은 원리금 ${format(loan.amount_due)} · 일 ${loan.rate}% · ${loan.status}${due}${collateral}`;
            },
          )
          .join("\n")
      : "대출 내역이 없습니다.";
    await replyPrivate(interaction, description);
  } else if (subcommand === "extend") {
    const result = await store.extendLoan(
      guildId,
      interaction.user.id,
      interaction.options.getInteger("loan_id", true),
      tierKey,
    );
    await replyPrivate(
      interaction,
      `대출 기간을 ${result.days}일 연장했습니다. 새 만기: <t:${Math.floor(new Date(result.dueAt).getTime() / 1000)}:d>.`,
    );
  } else if (subcommand === "queue") {
    requireAdmin(interaction);
    const rows = await store.listLoanQueue(guildId);
    await replyPrivate(
      interaction,
      rows.length
        ? rows
            .map(
              (loan: {
                id: number;
                discord_user_id: string;
                loan_type: string;
                requested_tier: string;
                principal: string;
                collateral_item: string | null;
                collateral_quantity: number | null;
                created_at: Date;
              }) =>
                `#${loan.id} ${mention(loan.discord_user_id)} · ${getTier(loan.requested_tier).name} · ${loan.loan_type === "collateral" ? `담보 ${loan.collateral_item} ${format(loan.collateral_quantity ?? 0)}개` : "신용"} · ${format(loan.principal)}벨${tierAtLeast(loan.requested_tier, "ace") ? " · 우선 심사" : ""}`,
            )
            .join("\n")
        : "심사 대기 중인 대출이 없습니다.",
    );
  } else if (
    subcommand === "approve" ||
    subcommand === "collateral-approve" ||
    subcommand === "collateral-return" ||
    subcommand === "reject"
  ) {
    requireAdmin(interaction);
    const loanId = interaction.options.getInteger("loan_id", true);
    const reason = interaction.options.getString("reason") ?? "";
    if (subcommand === "collateral-return") {
      await queueConfirmation(
        interaction,
        { kind: "collateral-return", loanId, reason },
        `대출 #${loanId} 담보를 게임에서 반환한 것으로 기록합니다. 사유: ${reason}`,
      );
      return;
    }
    await queueConfirmation(
      interaction,
      {
        kind: "loan",
        loanId,
        approve: subcommand === "approve" || subcommand === "collateral-approve",
        reason,
        verifiedCollateralValue:
          subcommand === "collateral-approve"
            ? interaction.options.getInteger("verified_value", true)
            : undefined,
      },
      subcommand === "collateral-approve"
        ? `대출 #${loanId} 담보를 게임에서 확인했습니다. 담보 총 가치 ${format(interaction.options.getInteger("verified_value", true))}벨로 승인합니다.`
        : `대출 #${loanId} 신청을 ${subcommand === "approve" ? "승인" : `거절합니다. 사유: ${reason}`}?`,
    );
  }
}

async function handleTier(interaction: ChatInputCommandInteraction, tierKey: TierKey) {
  const guildId = guildIdFrom(interaction);
  const profile = await store.getTierSummary(
    guildId,
    interaction.user.id,
    tierKey,
  );
  const settings = profile.settings;
  const platinumBonus = Number(settings.platinum_loan_bonus);
  const vipRate = Number(settings.vip_deposit_rate_bonus);
  const capacityKey = `${tierKey}_storage_limit` as keyof typeof settings;
  const storageCapacity = Number(settings[capacityKey]);
  const benefits = [
    "계좌 입금·출금",
    tierAtLeast(tierKey, "silver") ? "게임 확인형 아이템 담보 대출" : "대출 불가",
    tierAtLeast(tierKey, "gold")
      ? `신용 대출 최대 ${format(profile.creditLimit)}벨 (신용점수 × 10,000${tierAtLeast(tierKey, "platinum") ? ` + ${format(platinumBonus)}` : ""})`
      : "신용 대출 불가",
    tierAtLeast(tierKey, "silver") ? "관리자 설정 시 대출 기간 연장" : "",
    tierAtLeast(tierKey, "platinum")
      ? `은행 아이템 보관 한도 ${storageCapacity > 0 ? `${format(storageCapacity)}개` : "미설정"}`
      : "",
    tierAtLeast(tierKey, "ace") ? "신용 대출 우선 심사" : "",
    tierAtLeast(tierKey, "ace") ? "이벤트 우선 참여" : "",
    tierKey === "vip"
      ? `예금 일일 이자 추가 +${vipRate}%p (관리자 설정)`
      : "",
    tierAtLeast(tierKey, "platinum") ? "은행 의뢰 가능 · 아이템 보관 한도 확대" : "",
    tierKey === "vip" ? "추가 이권은 관리자 수동 운영" : "",
  ].filter(Boolean);
  const dueSettings =
    settings.loan_term_days > 0
      ? `기본 ${settings.loan_term_days}일 · 연장 ${settings.loan_extension_days}일 × 최대 ${settings.loan_extension_limit}회`
      : "대출 만기 미설정";
  await replyPrivate(
    interaction,
    [
      `현재 등급: **${profile.tier.name}** (서버 관리자가 부여한 역할 기준)`,
      `등급 기준 안내: ${tierRequirements[tierKey]} (게임 레벨·활동은 봇이 자동 확인하지 않습니다.)`,
      `신용점수: **${profile.creditScore}점** · 신용 한도 사용: ${format(profile.creditUsed)} / ${format(profile.creditLimit)}벨`,
      `대출 기간: ${dueSettings}`,
      "",
      "**적용 혜택**",
      ...benefits.map((benefit) => `• ${benefit}`),
      "",
      "동맹 길드장은 선택한 2명이 골드 등급으로 시작할 수 있습니다. 등급 역할은 봇이 부여하거나 변경하지 않습니다.",
    ].join("\n"),
  );
}

async function handleTierConfig(interaction: ChatInputCommandInteraction) {
  requireAdmin(interaction);
  const guildId = guildIdFrom(interaction);
  const subcommand = interaction.options.getSubcommand();
  const reason = interaction.options.getString("reason") ?? "관리자 등급 설정";
  if (subcommand === "limit") {
    const value = interaction.options.getInteger("bonus", true);
    await store.setTierSetting(
      guildId,
      interaction.user.id,
      "platinum_loan_bonus",
      value,
      reason,
    );
    await replyPrivate(interaction, `플레티넘 이상 신용대출 추가 한도를 ${format(value)}벨로 설정했습니다.`);
  } else if (subcommand === "interest") {
    const value = interaction.options.getNumber("rate", true);
    await store.setTierSetting(
      guildId,
      interaction.user.id,
      "vip_deposit_rate_bonus",
      value,
      reason,
    );
    await replyPrivate(interaction, `VIP 예금 일일 추가 이자율을 ${value}%p로 설정했습니다.`);
  } else if (subcommand === "storage") {
    const tierKey = interaction.options.getString("tier", true) as TierKey;
    const value = interaction.options.getInteger("capacity", true);
    await store.setTierSetting(
      guildId,
      interaction.user.id,
      `${tierKey}_storage_limit` as store.TierSettingKey,
      value,
      reason,
    );
    await replyPrivate(interaction, `${getTier(tierKey).name} 아이템 보관 한도를 ${format(value)}개로 설정했습니다.`);
  } else if (subcommand === "loan-term") {
    const value = interaction.options.getInteger("days", true);
    await store.setTierSetting(
      guildId,
      interaction.user.id,
      "loan_term_days",
      value,
      reason,
    );
    await replyPrivate(interaction, `신규 대출 기본 기간을 ${value === 0 ? "만기 없음" : `${value}일`}로 설정했습니다.`);
  } else if (subcommand === "extension") {
    const days = interaction.options.getInteger("days", true);
    const limit = interaction.options.getInteger("limit", true);
    await store.setTierSetting(
      guildId,
      interaction.user.id,
      "loan_extension_days",
      days,
      reason,
    );
    await store.setTierSetting(
      guildId,
      interaction.user.id,
      "loan_extension_limit",
      limit,
      reason,
    );
    await replyPrivate(interaction, `대출 연장 기준을 ${days}일씩 최대 ${limit}회로 설정했습니다.`);
  }
}

async function handleVault(interaction: ChatInputCommandInteraction) {
  const guildId = guildIdFrom(interaction);
  const subcommand = interaction.options.getSubcommand();
  if (subcommand === "list") {
    const result = await store.listVaultItems(guildId, interaction.user.id);
    const list = result.items.length
      ? result.items.map((item) => `${item.item_name}: ${format(item.quantity)}개`).join("\n")
      : "보관 중인 아이템이 없습니다.";
    await replyPrivate(
      interaction,
      `**${result.tier.name} 은행 보관함** · ${format(result.items.reduce((sum, item) => sum + Number(item.quantity), 0))}/${result.capacity}개\n${list}`,
    );
    return;
  }
  requireAdmin(interaction);
  const target = interaction.options.getUser("user", true);
  const itemName = interaction.options.getString("item", true);
  const quantity = interaction.options.getInteger("quantity", true);
  const reason = interaction.options.getString("reason", true);
  const operation = subcommand === "add" ? "add" : "remove";
  await queueConfirmation(
    interaction,
    {
      kind: "vault",
      operation,
      targetId: target.id,
      itemName,
      quantity,
      reason,
    },
    `${mention(target.id)} ${itemName} ${format(quantity)}개를 은행 보관함에서 ${operation === "add" ? "입고" : "반환"} 처리합니다. 게임에서 확인했는지 검토하세요. 사유: ${reason}`,
  );
}

async function handleBankRequest(
  interaction: ChatInputCommandInteraction,
  tierKey: TierKey,
) {
  const guildId = guildIdFrom(interaction);
  const subcommand = interaction.options.getSubcommand();
  if (subcommand === "submit") {
    const result = await store.createBankItemRequest(
      guildId,
      interaction.user.id,
      interaction.options.getString("item", true),
      interaction.options.getInteger("quantity", true),
      interaction.options.getString("note") ?? "",
      tierKey,
    );
    await replyPrivate(
      interaction,
      `은행 의뢰 #${result.requestId}을 접수했습니다. 운영진이 아이템을 확인해 수락·구매한 뒤 완료 처리합니다.`,
    );
  } else if (subcommand === "list") {
    const requests = await store.listBankItemRequests(
      guildId,
      interaction.user.id,
    );
    await replyPrivate(
      interaction,
      requests.length
        ? requests
            .map(
              (request: {
                id: number;
                item_name: string;
                quantity: number;
                status: string;
                review_note: string;
              }) =>
                `#${request.id} ${request.item_name} ${format(request.quantity)}개 · ${request.status}${request.review_note ? ` · ${request.review_note}` : ""}`,
            )
            .join("\n")
        : "은행 의뢰 내역이 없습니다.",
    );
  } else if (subcommand === "queue") {
    requireAdmin(interaction);
    const requests = await store.listBankItemRequests(guildId);
    await replyPrivate(
      interaction,
      requests.length
        ? requests
            .map(
              (request: {
                id: number;
                discord_user_id: string;
                item_name: string;
                quantity: number;
                note: string;
                status: string;
              }) =>
                `#${request.id} ${mention(request.discord_user_id)} · ${request.item_name} ${format(request.quantity)}개 · ${request.status}${request.note ? ` · ${request.note}` : ""}`,
            )
            .join("\n")
        : "진행 중인 은행 의뢰가 없습니다.",
    );
  } else if (subcommand === "update") {
    requireAdmin(interaction);
    const requestId = interaction.options.getInteger("request_id", true);
    const status = interaction.options.getString("status", true) as
      | "accepted"
      | "declined"
      | "fulfilled";
    const reason = interaction.options.getString("reason", true);
    await queueConfirmation(
      interaction,
      { kind: "bank-request", requestId, status, reason },
      `은행 의뢰 #${requestId} 상태를 ${status}로 변경합니다. 사유: ${reason}`,
    );
  }
}

async function handleStock(interaction: ChatInputCommandInteraction) {
  const guildId = guildIdFrom(interaction);
  const subcommand = interaction.options.getSubcommand();
  if (subcommand === "list") {
    const rows = await store.listStocks(guildId);
    if (!rows.length) {
      await replyPrivate(interaction, "상장 종목이 없습니다.");
      return;
    }
    const embed = new EmbedBuilder()
      .setColor(0x207e66)
      .setTitle("길드 가상주식")
      .setDescription(
        "종목 이름으로 검색·주문합니다. 기준가는 참고 가격이며 체결 가격은 주문 매칭 결과에 따릅니다.",
      );
    for (const stock of rows.slice(0, 24)) {
      embed.addFields({
        name: stock.name,
        value:
          `기준가 **${format(stock.current_price)}** · ` +
          `일간 ${stock.change_percent === null ? "평가 전" : `${signed(stock.change_percent)}%`}\n` +
          `유통 ${format(stock.total_shares)}주 · 시가총액 ${format(stock.market_cap)}`,
        inline: false,
      });
    }
    embed.setFooter({
      text:
        rows.length > 24
          ? `총 ${rows.length}종목 · 목록에는 이름순 24종목 표시`
          : `총 ${rows.length}종목 · 자세한 내용은 /stock quote`,
    });
    await interaction.reply({ embeds: [embed], flags: MessageFlags.Ephemeral });
  } else if (subcommand === "quote") {
    const stock = await store.quoteStock(
      guildId,
      interaction.options.getString("stock", true),
    );
    const evaluation = stock.evaluation as
      | {
          evaluation_date: string;
          content_score: number;
          activity_score: number;
          membership_score: number;
          events_score: number;
          growth_score: number;
          influence_score: number;
          opinion_score: number;
          base_score: number;
          random_score: number;
          final_score: number;
          change_percent: number;
          old_price: number;
          new_price: number;
          evidence: string;
        }
      | null;
    const orderBook = stock.orderBook as {
      best_bid: number | null;
      bid_shares: string | number;
      best_ask: number | null;
      ask_shares: string | number;
    };
    const recentTrades = stock.recentTrades as {
      shares: number;
      execution_price: number;
      created_at: string | Date;
    }[];
    const evaluationSummary = evaluation
      ? [
          `평가일 **${formatKstDate(evaluation.evaluation_date)}**`,
          `기본 ${signed(evaluation.base_score)}점 + 무작위 ${signed(evaluation.random_score)}점 = **${signed(evaluation.final_score)}점**`,
          `콘텐츠 ${signed(evaluation.content_score)}/6 · 활동 ${signed(evaluation.activity_score)}/6 · 인원 ${signed(evaluation.membership_score)}/5`,
          `주요 사건 ${signed(evaluation.events_score)}/8 · 성장 ${signed(evaluation.growth_score)}/5 · 영향력 ${signed(evaluation.influence_score)}/5 · 여론 ${signed(evaluation.opinion_score)}/5`,
          `가격 ${format(evaluation.old_price)} → ${format(evaluation.new_price)} (${signed(evaluation.change_percent)}%)`,
        ].join("\n")
      : "아직 공개된 평가가 없습니다.";
    const embed = new EmbedBuilder()
      .setColor(0x207e66)
      .setTitle(stock.name)
      .setDescription(stock.description || "종목 소개가 아직 등록되지 않았습니다.")
      .addFields(
        {
          name: "현재 기준가",
          value:
            `${format(stock.current_price)} 기본재화` +
            (evaluation ? ` · ${signed(evaluation.change_percent)}%` : ""),
          inline: true,
        },
        {
          name: "발행·유통 규모",
          value:
            `${format(stock.total_shares)}주\n` +
            `시가총액 ${format(stock.market_cap)} 기본재화`,
          inline: true,
        },
        {
          name: "주문 호가",
          value:
            `최고 매수: ${orderBook.best_bid === null ? "없음" : `${format(orderBook.best_bid)} · ${format(orderBook.bid_shares)}주`}\n` +
            `최저 매도: ${orderBook.best_ask === null ? "없음" : `${format(orderBook.best_ask)} · ${format(orderBook.ask_shares)}주`}`,
          inline: false,
        },
        {
          name: "최근 세부 평가",
          value: evaluationSummary,
          inline: false,
        },
        ...(evaluation
          ? [{ name: "평가 근거", value: evaluation.evidence, inline: false }]
          : []),
        {
          name: "최근 체결",
          value: recentTrades.length
            ? recentTrades
                .map(
                  (trade) =>
                    `<t:${Math.floor(new Date(trade.created_at).getTime() / 1000)}:R> · ${format(trade.shares)}주 × ${format(trade.execution_price)}`,
                )
                .join("\n")
            : "아직 체결된 거래가 없습니다.",
          inline: false,
        },
      );
    await interaction.reply({ embeds: [embed], flags: MessageFlags.Ephemeral });
  } else if (subcommand === "buy" || subcommand === "sell") {
    const result = await store.placeOrder(
      guildId,
      interaction.user.id,
      interaction.options.getString("stock", true),
      subcommand,
      interaction.options.getInteger("shares", true),
      interaction.options.getInteger("limit_price", true),
    );
    const message =
      `**${result.stock.name}** 주문 #${result.orderId} · ${subcommand === "buy" ? "매수" : "매도"} ${format(interaction.options.getInteger("shares", true))}주\n` +
      `지정가 ${format(interaction.options.getInteger("limit_price", true))} · 즉시 체결 ${format(result.filled)}주 · 미체결 ${format(result.remaining)}주.`;
    await replyPrivate(interaction, message);
  } else if (subcommand === "orders") {
    const rows = await store.listOrders(guildId, interaction.user.id);
    await replyPrivate(
      interaction,
      rows.length
        ? rows
            .map(
              (order) =>
                `**${order.name}** · #${order.id} ${order.side === "buy" ? "매수" : "매도"} · 지정가 ${format(order.limit_price)}\n${order.status === "partial" ? "일부 체결" : "대기 중"} · 체결 ${format(order.quantity - order.remaining)}/${format(order.quantity)}주 · 잔량 ${format(order.remaining)}주`,
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
                `**${item.stock_name ? `${item.stock_name} · ` : ""}${item.title}**\n${item.content}`,
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
      interaction.options.getString("description", true),
      interaction.options.getInteger("price", true),
      interaction.options.getInteger("initial_shares", true),
      interaction.options.getUser("holder", true).id,
      interaction.options.getString("reason", true),
    );
    const message =
      `**${result.name} 신규 상장**\n${result.description}\n` +
      `기준가 ${format(result.price)} · 초기 발행 ${format(result.initialShares)}주`;
    await replyPrivate(interaction, message);
    await sendAnnouncement(guildId, message);
  } else if (subcommand === "remove") {
    const stockName = interaction.options.getString("stock", true);
    const reason = interaction.options.getString("reason", true);
    await queueConfirmation(
      interaction,
      { kind: "stock-remove", stockName, reason },
      `${stockName} 상장을 폐지하고 미체결 주문을 취소합니다. 보유 주식과 거래 기록은 삭제되지 않습니다. 사유: ${reason}`,
    );
  } else if (subcommand === "issue" || subcommand === "burn") {
    const stockName = interaction.options.getString("stock", true);
    const holderId = interaction.options.getUser("holder", true).id;
    const shares = interaction.options.getInteger("shares", true);
    const reason = interaction.options.getString("reason", true);
    await queueConfirmation(
      interaction,
      {
        kind: "shares",
        operation: subcommand,
        stockName,
        holderId,
        shares,
        reason,
      },
      `${stockName} ${subcommand === "issue" ? "신규 발행" : "소각"} ${format(shares)}주, 보유자 ${mention(holderId)}. 변경 사유와 수량을 확인하세요: ${reason}`,
    );
  } else if (subcommand === "evaluate") {
    const result = await store.saveEvaluation(
      guildId,
      interaction.user.id,
      interaction.options.getString("stock", true),
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
      `**${result.stock.name} 평가 저장**\n` +
        `콘텐츠 ${signed(interaction.options.getInteger("content", true))}/6 · 활동 ${signed(interaction.options.getInteger("activity", true))}/6 · 인원 ${signed(interaction.options.getInteger("membership", true))}/5 · 사건 ${signed(interaction.options.getInteger("events", true))}/8 · 성장 ${signed(interaction.options.getInteger("growth", true))}/5 · 영향력 ${signed(interaction.options.getInteger("influence", true))}/5 · 여론 ${signed(interaction.options.getInteger("opinion", true))}/5\n` +
        `기본 ${result.base_score}점 + 무작위 ${signed(result.random_score)}점 = 최종 ${result.final_score}점 · 변동률 ${change}% · 기준가 ${format(result.old_price)} → ${format(result.new_price)}\n` +
        `21:00 시세 공지 예정. 근거: ${interaction.options.getString("evidence", true)}`,
    );
  } else if (subcommand === "publish") {
    const stockName = interaction.options.getString("stock") ?? undefined;
    const reports = await store.publishEvaluations(
      guildId,
      store.todayKst(),
      stockName,
    );
    const lines = reports.map(
      (report) =>
        `**${report.name}** · 기준가 ${format(report.old_price)} → ${format(report.new_price)} (${signed(report.change_percent)}%)\n` +
        `평가 ${signed(report.final_score)}점 (콘텐츠 ${signed(report.content_score)}, 활동 ${signed(report.activity_score)}, 인원 ${signed(report.membership_score)}, 사건 ${signed(report.events_score)}, 성장 ${signed(report.growth_score)}, 영향력 ${signed(report.influence_score)}, 여론 ${signed(report.opinion_score)}) · ${report.evidence}`,
    );
    const content = `오늘 가상주식 시세 발표\n${lines.join("\n\n")}`;
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
    const stockName = interaction.options.getString("stock") ?? undefined;
    const title = interaction.options.getString("title", true);
    const content = interaction.options.getString("content", true);
    const stock = await store.addMarketNews(
      guildId,
      interaction.user.id,
      title,
      content,
      stockName,
    );
    const message = `**[시장 뉴스${stock.stockName ? ` · ${stock.stockName}` : ""}] ${title}**\n${content}`;
    await replyPrivate(interaction, "시장을 공지했습니다.");
    await sendAnnouncement(guildId, message);
  } else if (subcommand === "describe") {
    const stock = await store.updateStockDescription(
      guildId,
      interaction.user.id,
      interaction.options.getString("stock", true),
      interaction.options.getString("description", true),
      interaction.options.getString("reason", true),
    );
    const message = `**${stock.name} 종목 소개 수정**\n${stock.description}`;
    await replyPrivate(interaction, message);
    await sendAnnouncement(guildId, message);
  } else if (subcommand === "officer-add") {
    const stock = await store.addOfficer(
      guildId,
      interaction.options.getString("stock", true),
      interaction.options.getUser("officer", true).id,
    );
    await replyPrivate(
      interaction,
      `${stock.name} 관계자를 지정했습니다. 종목별 최대 2명이며 해당 관계자는 소속 종목 평가에서 제외됩니다.`,
    );
  } else if (subcommand === "officer-remove") {
    const stock = await store.removeOfficer(
      guildId,
      interaction.options.getString("stock", true),
      interaction.options.getUser("officer", true).id,
    );
    await replyPrivate(interaction, `${stock.name} 관계자 지정을 해제했습니다.`);
  }
}

async function handleCommand(interaction: ChatInputCommandInteraction) {
  const guildId = guildIdFrom(interaction);
  const memberTier = tierFromInteraction(interaction);
  await store.syncTierSnapshot(
    guildId,
    interaction.user.id,
    memberTier.key,
  );
  switch (interaction.commandName) {
    case "register": {
      const result = await store.registerAccount(guildId, interaction.user.id);
      await store.syncTierSnapshot(guildId, interaction.user.id, memberTier.key);
      await replyPrivate(
        interaction,
        `계좌가 준비되었습니다. 기본재화는 ${result.currency.name}입니다. 지갑 잔액은 0, 신용점수는 50점으로 시작합니다. 게임 내 재화를 관리자에게 인증한 뒤 관리자가 /mint로 지급합니다.`,
      );
      break;
    }
    case "help":
      await interaction.reply({
        embeds: [helpEmbed()],
        flags: MessageFlags.Ephemeral,
      });
      break;
    case "tier":
      await handleTier(interaction, memberTier.key);
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
                  `<t:${Math.floor(new Date(row.created_at).getTime() / 1000)}:R> · ` +
                  `${row.stock_name ? `${row.type === "stock_buy" ? "주식 매수" : "주식 매도"} · ${row.stock_name} ${format(row.shares)}주 @ ${format(row.execution_price)}` : row.description || row.type} · ` +
                  `${format(row.amount)} ${row.currency}${Number(row.fee) ? ` (수수료 ${format(row.fee)})` : ""}`,
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
      await handleLoan(interaction, memberTier.key);
      break;
    case "credit": {
      requireAdmin(interaction);
      const target = interaction.options.getUser("user", true);
      if (interaction.options.getSubcommand() === "adjust") {
        const adjustment = getCreditAdjustment(
          interaction.options.getString("adjustment", true),
        );
        if (!adjustment) throw new Error("신용점수 변경 사유를 찾을 수 없습니다.");
        const detail = interaction.options.getString("detail", true);
        const reason = `${adjustment.label} · ${detail}`;
        const change = await store.adjustCreditScore(
          guildId,
          interaction.user.id,
          target.id,
          adjustment.delta,
          reason,
        );
        const actual = change.adjustment > 0 ? `+${change.adjustment}` : `${change.adjustment}`;
        await replyPrivate(
          interaction,
          `${mention(target.id)} 신용점수 ${change.oldScore}점 → ${change.score}점 (${actual}점 반영). 사유: ${reason}`,
        );
      } else {
        const score = interaction.options.getInteger("score", true);
        const reason = interaction.options.getString("reason", true);
        const change = await store.setCreditScore(
          guildId,
          interaction.user.id,
          target.id,
          score,
          reason,
        );
        await replyPrivate(
          interaction,
          `${mention(target.id)} 신용점수를 ${change.oldScore}점에서 ${change.score}점으로 변경했습니다. 사유: ${reason}`,
        );
      }
      break;
    }
    case "tier-config":
      await handleTierConfig(interaction);
      break;
    case "vault":
      await handleVault(interaction);
      break;
    case "bank-request":
      await handleBankRequest(interaction, memberTier.key);
      break;
    case "stock":
      await handleStock(interaction);
      break;
    case "portfolio": {
      const rows = await store.portfolio(guildId, interaction.user.id);
      if (!rows.length) {
        await replyPrivate(interaction, "보유 중인 가상주식이 없습니다.");
        break;
      }
      const embed = new EmbedBuilder()
        .setColor(0x207e66)
        .setTitle("내 가상주식 포트폴리오")
        .setDescription("현재 기준가로 계산한 참고 평가액입니다. 실제 매도 금액과 다를 수 있습니다.");
      for (const row of rows.slice(0, 24)) {
        embed.addFields({
          name: row.name,
          value:
            `${format(row.shares)}주 × 기준가 ${format(row.current_price)}\n` +
            `현재 평가액 **${format(row.market_value)}**${row.listed ? "" : " · 상장 폐지"}`,
          inline: false,
        });
      }
      embed.setFooter({
        text:
          rows.length > 24
            ? `총 ${rows.length}종목 · 이름순 24종목 표시`
            : `보유 종목 ${rows.length}개`,
      });
      await interaction.reply({ embeds: [embed], flags: MessageFlags.Ephemeral });
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
