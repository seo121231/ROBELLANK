from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import random
import unicodedata
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import asyncpg
import discord
from discord import app_commands
from discord.ext import tasks

from localization import SUPPORTED_LANGUAGES, translate_known_text, translate_message


TOKEN = os.environ.get("DISCORD_BOT_TOKEN")
DATABASE_URL = os.environ.get("DATABASE_URL")

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("robellank-bankbot")
pool: asyncpg.Pool

ADMIN_DESCRIPTION_PREFIX = "관리자 전용 · "
ADMIN_ONLY_GROUPS = {"credit", "tier-config"}
BANK_GOLD = 0xD7B43B
MIXED_GROUP_DESCRIPTIONS = {
    "loan": "대출 신청·상환·조회 (심사 하위 명령은 관리자 전용)",
    "currency": "재화·환율·이자 (설정 하위 명령은 관리자 전용)",
    "vault": "은행 보관 아이템 (입고·반환은 관리자 전용)",
    "bank-request": "은행 아이템 의뢰 (처리 하위 명령은 관리자 전용)",
    "market": "가상주식·시장 공지 (운영 하위 명령은 관리자 전용)",
}


def configure_command_registry(tree: app_commands.CommandTree) -> None:
    for command in tree.walk_commands():
        if not getattr(command, "checks", ()):
            continue

        description = command.description
        if description.startswith("관리자:"):
            description = description.removeprefix("관리자:").strip()
        if not description.startswith(ADMIN_DESCRIPTION_PREFIX):
            max_detail_length = 100 - len(ADMIN_DESCRIPTION_PREFIX)
            command.description = (
                ADMIN_DESCRIPTION_PREFIX + description[:max_detail_length]
            )

        if command.parent is None:
            app_commands.default_permissions(administrator=True)(command)

    for group_name in ADMIN_ONLY_GROUPS:
        group = tree.get_command(group_name)
        if isinstance(group, app_commands.Group):
            description = group.description.removeprefix("관리자:").strip()
            group.description = ADMIN_DESCRIPTION_PREFIX + description[:85]
            app_commands.default_permissions(administrator=True)(group)

    for group_name, description in MIXED_GROUP_DESCRIPTIONS.items():
        group = tree.get_command(group_name)
        if isinstance(group, app_commands.Group):
            group.description = description


TIERS = [
    ("bronze", "브론즈", 0, "1524024521999253514"),
    ("silver", "실버", 1, "1524024634213929031"),
    ("gold", "골드", 2, "1524024821808369765"),
    ("platinum", "플레티넘", 3, "1524398392606855269"),
    ("ace", "에이스", 4, "1524024941438304316"),
    ("vip", "VIP", 5, "1524024999973884066"),
]
TIER_ORDER = {key: rank for key, _, rank, _ in TIERS}
TIER_NAME = {key: label for key, label, _, _ in TIERS}
TIER_ROLE = {key: role_id for key, _, _, role_id in TIERS}
CREDIT_ADJUSTMENTS = {
    "savings_maturity": ("적금 만기 유지 (+2점)", 2),
    "savings_early": ("적금 중도 해지 (-1점)", -1),
    "collateral_on_time": ("담보대출 기한 내 상환 (+3점)", 3),
    "collateral_early": ("담보대출 조기 상환 추가 (+1점)", 1),
    "collateral_overdue": ("담보대출 연체 (-5점)", -5),
    "credit_on_time": ("신용대출 기한 내 상환 (+3점)", 3),
    "credit_early": ("신용대출 조기 상환 추가 (+1점)", 1),
    "credit_overdue": ("신용대출 연체 (-5점)", -5),
    "long_overdue": ("장기 연체 (-10점)", -10),
    "rule_violation": ("은행 규칙 위반 (-3점)", -3),
    "false_application": ("허위 신청·인증 (-10점)", -10),
    "rule_abuse": ("규칙 악용 (-5점)", -5),
    "fraud": ("사기·기만 행위 (-25점)", -25),
    "punishment_evasion": ("처벌 회피 시도 (-15점 · 타임아웃 별도)", -15),
    "bank_damage": ("은행 운영 피해 (-15점)", -15),
    "bank_staff": ("은행 직원 선임 (+10점)", 10),
}


def fmt(value: object) -> str:
    try:
        return f"{int(value or 0):,}"
    except (ValueError, TypeError):
        return str(value)


def signed(value: int | float) -> str:
    return f"+{value}" if value > 0 else str(value)


def normalize_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value.strip()).casefold()


def require_guild(interaction: discord.Interaction) -> str:
    if not interaction.guild_id:
        raise ValueError("서버 안에서만 사용할 수 있습니다.")
    return str(interaction.guild_id)


def tier_for(member: discord.abc.User | discord.Member) -> str:
    role_ids = {str(role.id) for role in getattr(member, "roles", [])}
    for key, _, _, role_id in reversed(TIERS):
        if role_id in role_ids:
            return key
    return "bronze"


def tier_at_least(tier: str, minimum: str) -> bool:
    return TIER_ORDER.get(tier, 0) >= TIER_ORDER[minimum]


async def base_currency(conn: asyncpg.Connection, guild_id: str) -> asyncpg.Record:
    row = await conn.fetchrow(
        """SELECT id, name, symbol, exchange_value, deposit_rate, loan_rate, is_base, active
             FROM bank_currencies WHERE guild_id=$1 AND is_base=true AND active=true LIMIT 1""",
        guild_id,
    )
    if row:
        return row
    return await conn.fetchrow(
        """INSERT INTO bank_currencies
             (guild_id,name,symbol,exchange_value,deposit_rate,loan_rate,is_base,active)
           VALUES ($1,'벨','벨',1,0,0,true,true)
           ON CONFLICT (guild_id,name) DO UPDATE SET active=true,is_base=true
           RETURNING id,name,symbol,exchange_value,deposit_rate,loan_rate,is_base,active""",
        guild_id,
    )


async def ensure_guild(guild_id: str) -> None:
    async with pool.acquire() as conn:
        await base_currency(conn, guild_id)
        await conn.execute(
            "INSERT INTO bank_tier_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING",
            guild_id,
        )


async def account(
    conn: asyncpg.Connection,
    guild_id: str,
    user_id: str,
    *,
    lock: bool = False,
    allow_frozen: bool = False,
) -> asyncpg.Record:
    row = await conn.fetchrow(
        f"""SELECT id,frozen,tier_key,credit_score FROM bank_accounts
             WHERE guild_id=$1 AND discord_user_id=$2 LIMIT 1{" FOR UPDATE" if lock else ""}""",
        guild_id,
        user_id,
    )
    if not row:
        raise ValueError("계좌가 없습니다. 먼저 /register를 사용하세요.")
    if row["frozen"] and not allow_frozen:
        raise ValueError("계좌가 동결되어 거래할 수 없습니다. 관리자에게 문의하세요.")
    return row


async def get_or_create_account(
    conn: asyncpg.Connection, guild_id: str, user_id: str
) -> asyncpg.Record:
    base = await base_currency(conn, guild_id)
    await conn.execute(
        """INSERT INTO bank_accounts (guild_id,discord_user_id) VALUES ($1,$2)
           ON CONFLICT (guild_id,discord_user_id) DO NOTHING""",
        guild_id,
        user_id,
    )
    row = await account(conn, guild_id, user_id, lock=True, allow_frozen=True)
    await conn.execute(
        """INSERT INTO bank_balances (account_id,currency_id) VALUES ($1,$2)
           ON CONFLICT (account_id,currency_id) DO NOTHING""",
        row["id"],
        base["id"],
    )
    return row


async def get_currency(
    conn: asyncpg.Connection,
    guild_id: str,
    name: str,
    *,
    lock: bool = False,
) -> asyncpg.Record:
    row = await conn.fetchrow(
        f"""SELECT id,name,symbol,exchange_value,deposit_rate,loan_rate,is_base,active
             FROM bank_currencies
             WHERE guild_id=$1 AND lower(name)=lower($2) AND active=true LIMIT 1
             {"FOR UPDATE" if lock else ""}""",
        guild_id,
        name,
    )
    if not row:
        raise ValueError(f"재화 '{name}'을(를) 찾을 수 없습니다.")
    return row


async def ensure_balance(
    conn: asyncpg.Connection, account_id: int, currency_id: int
) -> None:
    await conn.execute(
        """INSERT INTO bank_balances (account_id,currency_id) VALUES ($1,$2)
           ON CONFLICT (account_id,currency_id) DO NOTHING""",
        account_id,
        currency_id,
    )


async def record_transaction(
    conn: asyncpg.Connection,
    guild_id: str,
    transaction_type: str,
    currency_id: int,
    amount: int,
    *,
    actor_id: int | None = None,
    target_id: int | None = None,
    fee: int = 0,
    description: str = "",
    metadata: dict | None = None,
) -> None:
    await conn.execute(
        """INSERT INTO bank_transactions
             (guild_id,type,actor_account_id,target_account_id,currency_id,amount,fee,description,metadata)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9::jsonb)""",
        guild_id,
        transaction_type,
        actor_id,
        target_id,
        currency_id,
        amount,
        fee,
        description,
        json.dumps(metadata or {}),
    )


async def sync_tier(guild_id: str, user_id: str, tier_key: str) -> None:
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE bank_accounts SET tier_key=$1 WHERE guild_id=$2 AND discord_user_id=$3",
            tier_key,
            guild_id,
            user_id,
        )


class BankCommandTree(app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.guild_id and not interaction.user.bot:
            await sync_tier(
                str(interaction.guild_id),
                str(interaction.user.id),
                tier_for(interaction.user),
            )
        return True

    async def on_error(
        self,
        interaction: discord.Interaction,
        error: app_commands.AppCommandError,
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "이 명령어는 서버 관리자만 사용할 수 있습니다."
        elif isinstance(error, app_commands.CheckFailure):
            message = "이 명령어를 사용할 권한이 없습니다."
        elif isinstance(error, app_commands.TransformerError):
            logger.warning("Invalid application command input: %s", error)
            message = "입력값 형식을 확인해 주세요. 채널은 목록에서 선택하거나 채널 이름을 입력해 주세요."
        else:
            logger.error(
                "Application command failed",
                exc_info=(type(error), error, error.__traceback__),
            )
            message = "명령 처리 중 오류가 발생했습니다. 관리자에게 문의하세요."
        await send_public(interaction, message)


class BankBot(discord.Client):
    def __init__(self) -> None:
        super().__init__(intents=intents)
        self.tree = BankCommandTree(self)

    async def setup_hook(self) -> None:
        global pool
        if not TOKEN:
            raise RuntimeError("DISCORD_BOT_TOKEN Secret is required.")
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL must be set.")
        pool = await asyncpg.create_pool(DATABASE_URL, min_size=1, max_size=8)
        synced = await self.tree.sync()
        logger.info(
            "Connected setup complete; synced %s application commands", len(synced)
        )


async def send_private(interaction: discord.Interaction, content: str) -> None:
    """Legacy name retained for existing commands; replies are public."""
    await send_public(interaction, content)


async def get_user_language(user_id: str | int) -> str:
    try:
        async with pool.acquire() as conn:
            language = await conn.fetchval(
                "SELECT language FROM bank_user_preferences WHERE discord_user_id=$1",
                str(user_id),
            )
    except asyncpg.PostgresError:
        logger.warning("Could not load user language preference", exc_info=True)
        return "ko"
    return language if language in SUPPORTED_LANGUAGES else "ko"


async def set_user_language(user_id: str | int, language: str) -> None:
    if language not in SUPPORTED_LANGUAGES:
        raise ValueError("Unsupported language.")
    async with pool.acquire() as conn:
        await conn.execute(
            """INSERT INTO bank_user_preferences (discord_user_id,language)
               VALUES ($1,$2)
               ON CONFLICT (discord_user_id)
               DO UPDATE SET language=EXCLUDED.language""",
            str(user_id),
            language,
        )


def localize_embed(embed: discord.Embed, language: str) -> discord.Embed:
    localized = discord.Embed.from_dict(embed.to_dict())
    if localized.title:
        localized.title = translate_known_text(localized.title, language)
    if localized.description:
        localized.description = translate_known_text(localized.description, language)
    for field in localized.fields:
        field.name = translate_known_text(field.name, language)
        field.value = translate_known_text(field.value, language)
    if localized.footer.text:
        localized.set_footer(
            text=translate_known_text(localized.footer.text, language),
            icon_url=localized.footer.icon_url,
        )
    return localized


async def send_public(
    interaction: discord.Interaction,
    content: str | None = None,
    *,
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
    language: str | None = None,
) -> None:
    language = language or await get_user_language(interaction.user.id)
    if content is not None:
        content = translate_message(content, language)
        if len(content) > 1900:
            omitted = "…some content was omitted." if language == "en" else "…내용이 길어 일부를 생략했습니다."
            content = content[:1880] + "\n" + omitted
    if embed is not None:
        embed = localize_embed(embed, language)
    if interaction.response.is_done():
        await interaction.followup.send(
            content=content, embed=embed, view=view, ephemeral=False
        )
    else:
        await interaction.response.send_message(
            content=content, embed=embed, view=view, ephemeral=False
        )


async def safe_command(interaction: discord.Interaction, action) -> None:
    try:
        await action()
    except ValueError as error:
        logger.warning("Command failed: %s", error)
        await send_private(interaction, str(error) or "요청을 처리하지 못했습니다.")
    except asyncpg.PostgresError:
        logger.exception("Database command failed")
        await send_private(
            interaction,
            "데이터베이스 문제로 요청을 처리하지 못했습니다. 잠시 후 다시 시도해 주세요.",
        )
    except Exception:
        logger.exception("Unexpected command failure")
        await send_private(
            interaction, "요청 처리 중 오류가 발생했습니다. 관리자에게 문의하세요."
        )


intents = discord.Intents.none()
intents.guilds = True
bot = BankBot()


@bot.event
async def on_ready() -> None:
    logger.info("ROBELLANK bank bot connected as %s", bot.user)
    for guild in bot.guilds:
        await ensure_guild(str(guild.id))
    if not scheduled_tasks.is_running():
        scheduled_tasks.start()


@bot.event
async def on_guild_join(guild: discord.Guild) -> None:
    await ensure_guild(str(guild.id))


@bot.tree.command(name="register", description="은행 계좌를 개설합니다")
async def register(interaction: discord.Interaction) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            async with conn.transaction():
                base = await base_currency(conn, guild_id)
                row = await conn.fetchrow(
                    """INSERT INTO bank_accounts (guild_id,discord_user_id)
                       VALUES ($1,$2)
                       ON CONFLICT (guild_id,discord_user_id) DO UPDATE SET discord_user_id=EXCLUDED.discord_user_id
                       RETURNING id""",
                    guild_id,
                    str(interaction.user.id),
                )
                await ensure_balance(conn, row["id"], base["id"])
        await sync_tier(guild_id, str(interaction.user.id), tier_for(interaction.user))
        await send_private(
            interaction,
            f"계좌가 준비되었습니다. 기본재화는 {base['name']}입니다. "
            "지갑 잔액은 0, 신용점수는 50점으로 시작합니다. "
            "게임 내 재화를 관리자가 인증한 뒤 지급합니다.",
        )

    await safe_command(interaction, run)


def trim_embed_text(value: object, max_length: int) -> str:
    text = str(value)
    if len(text) <= max_length:
        return text
    return text[: max_length - 1].rstrip() + "…"


def build_account_embed(
    target: discord.User | discord.Member,
    rows: list[asyncpg.Record],
    frozen: bool,
    language: str,
) -> discord.Embed:
    english = language == "en"
    embed = discord.Embed(
        title=(
            f"{target.display_name}'s Account"
            if english
            else f"{target.display_name} 계좌"
        ),
        color=BANK_GOLD,
    )
    embed.set_thumbnail(url=target.display_avatar.url)
    description_lines = []
    if frozen:
        description_lines.append(
            "🔒 This account is frozen." if english else "🔒 동결된 계좌입니다."
        )

    for row in rows[:24]:
        symbol = trim_embed_text(row["symbol"], 20)
        currency_name = trim_embed_text(row["name"], 100)
        label = (
            f"🪙 {currency_name} · {symbol}"
            if row["is_base"]
            else f"🏦 {currency_name} · {symbol}"
        )
        wallet_label = "Wallet" if english else "지갑"
        savings_label = "Savings" if english else "예금"
        embed.add_field(
            name=label,
            value=(
                f"**{wallet_label}**\n{fmt(row['wallet'] or 0)} {symbol}\n"
                f"**{savings_label}**\n{fmt(row['deposit'] or 0)} {symbol}"
            ),
            inline=False,
        )

    if not rows:
        description_lines.append(
            "No active currencies are configured."
            if english
            else "사용 가능한 재화가 없습니다."
        )
    elif len(rows) > 24:
        embed.add_field(
            name="More" if english else "추가 재화",
            value=(
                f"{len(rows) - 24} more currencies omitted."
                if english
                else f"재화 {len(rows) - 24}개를 생략했습니다."
            ),
            inline=False,
        )
    if description_lines:
        embed.description = "\n".join(description_lines)

    embed.set_footer(
        text=(
            "ROBELLANK BANK · PERSONAL ACCOUNT"
            if english
            else "ROBELLANK BANK · 개인 계좌"
        )
    )
    return embed


@bot.tree.command(name="balance", description="지갑·예금 잔액을 확인합니다")
@app_commands.describe(user="조회할 사용자 (생략하면 본인)")
async def balance(
    interaction: discord.Interaction, user: discord.User | None = None
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        target = user or interaction.user
        async with pool.acquire() as conn:
            acct = await account(conn, guild_id, str(target.id), allow_frozen=True)
            rows = await conn.fetch(
                """SELECT c.name,c.symbol,b.wallet,b.deposit,c.is_base
                     FROM bank_currencies c LEFT JOIN bank_balances b
                       ON b.currency_id=c.id AND b.account_id=$2
                    WHERE c.guild_id=$1 AND c.active=true
                    ORDER BY c.is_base DESC,c.name""",
                guild_id,
                acct["id"],
            )
        language = await get_user_language(interaction.user.id)
        await send_public(
            interaction,
            embed=build_account_embed(target, rows, acct["frozen"], language),
            view=BankMenuView(interaction.user.id, language),
            language=language,
        )

    await safe_command(interaction, run)


@bot.tree.command(name="transfer", description="다른 사용자에게 재화를 송금합니다")
async def transfer(
    interaction: discord.Interaction,
    user: discord.User,
    currency: str,
    amount: app_commands.Range[int, 1, 2147483647],
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        sender_id, recipient_id = str(interaction.user.id), str(user.id)
        if sender_id == recipient_id:
            raise ValueError("본인에게 송금할 수 없습니다.")
        async with pool.acquire() as conn:
            async with conn.transaction():
                sender = await account(conn, guild_id, sender_id, lock=True)
                recipient = await account(conn, guild_id, recipient_id, lock=True)
                if recipient["frozen"]:
                    raise ValueError("동결된 계좌와는 송금할 수 없습니다.")
                currency_row = await get_currency(conn, guild_id, currency, lock=True)
                await ensure_balance(conn, sender["id"], currency_row["id"])
                await ensure_balance(conn, recipient["id"], currency_row["id"])
                rows = await conn.fetch(
                    """SELECT account_id,wallet FROM bank_balances
                       WHERE currency_id=$1 AND account_id=ANY($2::int[])
                       ORDER BY account_id FOR UPDATE""",
                    currency_row["id"],
                    sorted([sender["id"], recipient["id"]]),
                )
                sender_balance = next(
                    (row for row in rows if row["account_id"] == sender["id"]), None
                )
                if not sender_balance or int(sender_balance["wallet"]) < amount:
                    raise ValueError("지갑 잔액이 부족합니다.")
                await conn.execute(
                    "UPDATE bank_balances SET wallet=wallet-$1 WHERE account_id=$2 AND currency_id=$3",
                    amount,
                    sender["id"],
                    currency_row["id"],
                )
                await conn.execute(
                    "UPDATE bank_balances SET wallet=wallet+$1 WHERE account_id=$2 AND currency_id=$3",
                    amount,
                    recipient["id"],
                    currency_row["id"],
                )
                await record_transaction(
                    conn,
                    guild_id,
                    "transfer",
                    currency_row["id"],
                    amount,
                    actor_id=sender["id"],
                    target_id=recipient["id"],
                    description=f"{currency_row['name']} 송금",
                )
        await send_private(
            interaction,
            f"<@{user.id}>에게 {fmt(amount)} {currency_row['symbol']} 송금했습니다.",
        )

    await safe_command(interaction, run)


async def move_deposit(
    interaction: discord.Interaction, currency: str, amount: int, direction: str
) -> None:
    guild_id = require_guild(interaction)
    async with pool.acquire() as conn:
        async with conn.transaction():
            acct = await account(conn, guild_id, str(interaction.user.id), lock=True)
            currency_row = await get_currency(conn, guild_id, currency, lock=True)
            await ensure_balance(conn, acct["id"], currency_row["id"])
            row = await conn.fetchrow(
                "SELECT wallet,deposit FROM bank_balances WHERE account_id=$1 AND currency_id=$2 FOR UPDATE",
                acct["id"],
                currency_row["id"],
            )
            if direction == "deposit":
                if int(row["wallet"]) < amount:
                    raise ValueError("지갑 잔액이 부족합니다.")
                await conn.execute(
                    "UPDATE bank_balances SET wallet=wallet-$1,deposit=deposit+$1 WHERE account_id=$2 AND currency_id=$3",
                    amount,
                    acct["id"],
                    currency_row["id"],
                )
            else:
                if int(row["deposit"]) < amount:
                    raise ValueError("예금 잔액이 부족합니다.")
                await conn.execute(
                    "UPDATE bank_balances SET wallet=wallet+$1,deposit=deposit-$1 WHERE account_id=$2 AND currency_id=$3",
                    amount,
                    acct["id"],
                    currency_row["id"],
                )
            await record_transaction(
                conn,
                guild_id,
                direction,
                currency_row["id"],
                amount,
                actor_id=acct["id"],
                target_id=acct["id"],
                description="지갑에서 예금"
                if direction == "deposit"
                else "예금에서 지갑",
            )
    note = (
        "예금했습니다. 이자는 매일 한국 시간 자정에 반영됩니다."
        if direction == "deposit"
        else "예금에서 지갑으로 옮겼습니다."
    )
    await send_private(interaction, f"{fmt(amount)} {currency_row['symbol']}을 {note}")


@bot.tree.command(name="deposit", description="지갑에서 예금으로 옮깁니다")
async def deposit(
    interaction: discord.Interaction,
    currency: str,
    amount: app_commands.Range[int, 1, 2147483647],
) -> None:
    await safe_command(
        interaction, lambda: move_deposit(interaction, currency, amount, "deposit")
    )


@bot.tree.command(name="withdraw", description="예금에서 지갑으로 옮깁니다")
async def withdraw(
    interaction: discord.Interaction,
    currency: str,
    amount: app_commands.Range[int, 1, 2147483647],
) -> None:
    await safe_command(
        interaction, lambda: move_deposit(interaction, currency, amount, "withdraw")
    )


@bot.tree.command(name="exchange", description="재화를 기본 환율로 환전합니다")
async def exchange(
    interaction: discord.Interaction,
    from_currency: str,
    to: str,
    amount: app_commands.Range[int, 1, 2147483647],
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            async with conn.transaction():
                acct = await account(
                    conn, guild_id, str(interaction.user.id), lock=True
                )
                source = await get_currency(conn, guild_id, from_currency, lock=True)
                target = await get_currency(conn, guild_id, to, lock=True)
                if source["id"] == target["id"]:
                    raise ValueError("서로 다른 재화를 선택하세요.")
                await ensure_balance(conn, acct["id"], source["id"])
                await ensure_balance(conn, acct["id"], target["id"])
                balances = await conn.fetch(
                    """SELECT currency_id,wallet FROM bank_balances
                       WHERE account_id=$1 AND currency_id=ANY($2::int[])
                       ORDER BY currency_id FOR UPDATE""",
                    acct["id"],
                    sorted([source["id"], target["id"]]),
                )
                wallet = next(
                    row["wallet"]
                    for row in balances
                    if row["currency_id"] == source["id"]
                )
                if int(wallet) < amount:
                    raise ValueError("지갑 잔액이 부족합니다.")
                received = int(
                    (
                        Decimal(amount)
                        * Decimal(source["exchange_value"])
                        / Decimal(target["exchange_value"])
                    ).to_integral_value(rounding="ROUND_FLOOR")
                )
                if received < 1:
                    raise ValueError(
                        "환전 결과가 1 미만입니다. 더 큰 금액을 입력하세요."
                    )
                await conn.execute(
                    "UPDATE bank_balances SET wallet=wallet-$1 WHERE account_id=$2 AND currency_id=$3",
                    amount,
                    acct["id"],
                    source["id"],
                )
                await conn.execute(
                    "UPDATE bank_balances SET wallet=wallet+$1 WHERE account_id=$2 AND currency_id=$3",
                    received,
                    acct["id"],
                    target["id"],
                )
                await record_transaction(
                    conn,
                    guild_id,
                    "exchange",
                    source["id"],
                    amount,
                    actor_id=acct["id"],
                    target_id=acct["id"],
                    description=f"{source['name']} → {target['name']} {received}",
                    metadata={"received": received, "targetCurrencyId": target["id"]},
                )
        await send_private(
            interaction,
            f"{fmt(amount)} {source['symbol']} → {fmt(received)} "
            f"{target['symbol']} 환전했습니다. "
            "소수점 이하 결과는 버림 처리됩니다.",
        )

    await safe_command(interaction, run)


@bot.tree.command(name="leaderboard", description="재화별 잔액 순위를 확인합니다")
async def leaderboard(interaction: discord.Interaction, currency: str) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            currency_row = await get_currency(conn, guild_id, currency)
            rows = await conn.fetch(
                """SELECT a.discord_user_id,COALESCE(b.wallet,0) wallet,
                          COALESCE(b.deposit,0) deposit,
                          COALESCE(b.wallet,0)+COALESCE(b.deposit,0) total
                     FROM bank_accounts a LEFT JOIN bank_balances b
                       ON b.account_id=a.id AND b.currency_id=$2
                    WHERE a.guild_id=$1 ORDER BY total DESC,a.discord_user_id LIMIT 10""",
                guild_id,
                currency_row["id"],
            )
        lines = [
            f"{idx}. <@{row['discord_user_id']}> · {fmt(row['total'])} {currency_row['symbol']}"
            for idx, row in enumerate(rows, 1)
        ]
        await send_private(
            interaction,
            f"**{currency_row['name']} 부자 순위**\n"
            + ("\n".join(lines) or "등록된 계좌가 없습니다."),
        )

    await safe_command(interaction, run)


@bot.tree.command(name="tier", description="내 등급, 신용점수, 은행 혜택을 확인합니다")
async def tier(interaction: discord.Interaction) -> None:
    async def run():
        guild_id = require_guild(interaction)
        tier_key = tier_for(interaction.user)
        async with pool.acquire() as conn:
            acct = await account(
                conn, guild_id, str(interaction.user.id), allow_frozen=True
            )
            await conn.execute(
                "UPDATE bank_accounts SET tier_key=$1 WHERE id=$2", tier_key, acct["id"]
            )
            await conn.execute(
                "INSERT INTO bank_tier_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING",
                guild_id,
            )
            settings = await conn.fetchrow(
                "SELECT platinum_loan_bonus,loan_term_days,loan_extension_days,loan_extension_limit FROM bank_tier_settings WHERE guild_id=$1",
                guild_id,
            )
            currency_row = await get_currency(conn, guild_id, "벨")
            exposure = await conn.fetchval(
                """SELECT COALESCE(SUM(CASE WHEN status='approved' THEN amount_due ELSE principal END),0)
                     FROM bank_loans WHERE guild_id=$1 AND account_id=$2 AND currency_id=$3
                       AND loan_type='credit' AND status IN ('pending','approved')""",
                guild_id,
                acct["id"],
                currency_row["id"],
            )
            credit_limit = acct["credit_score"] * 10_000 + (
                int(settings["platinum_loan_bonus"])
                if tier_at_least(tier_key, "platinum")
                else 0
            )
            storage_limit = await conn.fetchval(
                f"SELECT {tier_key}_storage_limit FROM bank_tier_settings WHERE guild_id=$1",
                guild_id,
            )
            stored = await conn.fetchval(
                "SELECT COALESCE(SUM(quantity),0) FROM bank_vault_items WHERE account_id=$1",
                acct["id"],
            )
        benefits = {
            "bronze": "입금·출금 가능 · 대출 신청 불가",
            "silver": "브론즈 혜택 · 아이템/재료 담보 대출 · 대출 기간 연장",
            "gold": "실버 혜택 · 신용점수 기반 신용 대출",
            "platinum": (
                "골드 혜택 · 은행 아이템 의뢰 · 대출 한도·보관 한도 추가 설정"
            ),
            "ace": (
                "플래티넘 혜택 · 대출 심사 우선순위 · 이벤트 우선 참여(운영진 관리)"
            ),
            "vip": ("에이스 혜택 · 예금 이자 추가율 및 추가 혜택(운영진 설정)"),
        }[tier_key]
        vip_bonus = (
            f"\nVIP 예금 추가 이율: {settings['vip_deposit_rate_bonus']}%/일"
            if tier_key == "vip"
            else ""
        )
        await send_private(
            interaction,
            f"등급: **{TIER_NAME[tier_key]}** · 신용점수 {acct['credit_score']}/100\n"
            f"혜택: {benefits}\n"
            f"신용대출 한도 {fmt(credit_limit)}벨 · 사용 {fmt(exposure)}벨 · "
            f"남은 한도 {fmt(max(0, credit_limit - int(exposure)))}벨\n"
            f"아이템 보관함 {fmt(stored)}/{fmt(storage_limit)}개 · "
            f"신규 대출 기본 기간 {fmt(settings['loan_term_days'])}일"
            f" · 연장 {fmt(settings['loan_extension_days'])}일/{fmt(settings['loan_extension_limit'])}회"
            f"{vip_bonus}\n"
            "등급 역할은 관리자가 직접 부여하며 봇은 역할을 변경하지 않습니다.",
        )

    await safe_command(interaction, run)


stock_group = app_commands.Group(name="stock", description="길드 가상주식 조회·주문")


async def list_stocks(guild_id: str) -> list[asyncpg.Record]:
    async with pool.acquire() as conn:
        return await conn.fetch(
            """SELECT s.name,s.description,s.current_price,s.total_shares,
                      s.current_price::numeric*s.total_shares market_cap,e.change_percent
                 FROM bank_stocks s LEFT JOIN LATERAL (
                   SELECT change_percent FROM bank_stock_evaluations
                    WHERE stock_id=s.id AND status='published'
                    ORDER BY evaluation_date DESC LIMIT 1
                 ) e ON true
                WHERE s.guild_id=$1 AND s.listed=true
                ORDER BY lower(s.name),s.name""",
            guild_id,
        )


def table_embed(rows: list[asyncpg.Record], page: int) -> discord.Embed:
    page_size = 12
    start = page * page_size
    selected = rows[start : start + page_size]
    columns = [
        ("번호", [str(start + index + 1) for index in range(len(selected))], True),
        ("종목 이름", [row["name"] for row in selected], False),
        ("기준가", [fmt(row["current_price"]) for row in selected], True),
        (
            "일간 변동",
            [
                "평가 전"
                if row["change_percent"] is None
                else f"{signed(row['change_percent'])}%"
                for row in selected
            ],
            True,
        ),
        ("유통량", [f"{fmt(row['total_shares'])}주" for row in selected], True),
        ("시가총액", [fmt(row["market_cap"]) for row in selected], True),
    ]

    def width(text: str) -> int:
        return sum(
            2 if unicodedata.east_asian_width(char) in "WF" else 1 for char in text
        )

    widths = [
        max(width(header), *(width(value) for value in values))
        for header, values, _ in columns
    ]

    def cell(text: str, col: int, right: bool) -> str:
        space = " " * (widths[col] - width(text))
        return space + text if right else text + space

    lines = [
        "  ".join(
            cell(header, idx, right) for idx, (header, _, right) in enumerate(columns)
        ),
    ]
    for row in range(len(selected)):
        lines.append(
            "  ".join(
                cell(values[row], idx, right)
                for idx, (_, values, right) in enumerate(columns)
            )
        )
    page_count = (len(rows) + page_size - 1) // page_size
    embed = discord.Embed(
        title=f"전체 주식 시세표 · {page + 1}/{page_count}",
        description="```text\n"
        + "\n".join(lines)
        + "\n```\n"
        + "기준가·시가총액은 참고값이며 실제 체결가는 주문 매칭 결과에 따릅니다.",
        color=0x207E66,
    )
    embed.set_footer(text=f"상장 종목 {len(rows)}개 · 이름순 정렬")
    return embed


@stock_group.command(name="list", description="상장 종목 목록")
async def stock_list(interaction: discord.Interaction) -> None:
    async def run():
        rows = await list_stocks(require_guild(interaction))
        if not rows:
            await send_private(interaction, "상장 종목이 없습니다.")
            return
        embed = discord.Embed(
            title="길드 가상주식",
            description=(
                "종목 이름으로 검색·주문합니다. 기준가는 참고 가격이며 "
                "체결 가격은 주문 매칭 결과에 따릅니다."
            ),
            color=0x207E66,
        )
        for stock in rows[:24]:
            change = (
                "평가 전"
                if stock["change_percent"] is None
                else f"{signed(stock['change_percent'])}%"
            )
            embed.add_field(
                name=stock["name"],
                value=(
                    f"기준가 **{fmt(stock['current_price'])}** · 일간 {change}\n"
                    f"유통 {fmt(stock['total_shares'])}주 · "
                    f"시가총액 {fmt(stock['market_cap'])}"
                ),
                inline=False,
            )
        embed.set_footer(
            text=f"총 {len(rows)}종목 · 자세한 내용은 /stock quote"
            if len(rows) <= 24
            else f"총 {len(rows)}종목 · 목록에는 이름순 24종목 표시"
        )
        await send_public(interaction, embed=embed)

    await safe_command(interaction, run)


@stock_group.command(name="table", description="상장된 모든 종목을 표로 확인합니다")
async def stock_table(interaction: discord.Interaction) -> None:
    async def run():
        rows = await list_stocks(require_guild(interaction))
        if not rows:
            await send_private(interaction, "상장 종목이 없습니다.")
            return
        pages = (len(rows) + 11) // 12
        for page in range(pages):
            if page == 0:
                await send_public(interaction, embed=table_embed(rows, page))
            else:
                await interaction.followup.send(
                    embed=localize_embed(
                        table_embed(rows, page),
                        await get_user_language(interaction.user.id),
                    ),
                    ephemeral=False,
                )

    await safe_command(interaction, run)


@stock_group.command(
    name="quote", description="종목 소개·시세·호가·평가를 자세히 확인합니다"
)
async def stock_quote(interaction: discord.Interaction, stock: str) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id,name,description,current_price,total_shares,
                          current_price::numeric*total_shares market_cap
                     FROM bank_stocks
                    WHERE guild_id=$1
                      AND lower(trim(name))=lower(trim($2))
                      AND listed=true""",
                guild_id,
                stock,
            )
            if not row:
                raise ValueError(f"종목 이름 '{stock}'을(를) 찾을 수 없습니다.")
            evaluation = await conn.fetchrow(
                """SELECT evaluation_date,content_score,activity_score,membership_score,
                          events_score,growth_score,influence_score,opinion_score,
                          base_score,random_score,final_score,change_percent,
                          old_price,new_price,evidence,created_by
                     FROM bank_stock_evaluations WHERE stock_id=$1 AND status='published'
                    ORDER BY evaluation_date DESC LIMIT 1""",
                row["id"],
            )
            book = await conn.fetchrow(
                """SELECT
                   (SELECT limit_price
                      FROM bank_stock_orders
                     WHERE stock_id=$1 AND side='buy'
                       AND status IN ('open','partial')
                     ORDER BY limit_price DESC,created_at,id LIMIT 1) best_bid,
                   (SELECT COALESCE(SUM(remaining),0)
                      FROM bank_stock_orders
                     WHERE stock_id=$1 AND side='buy'
                       AND status IN ('open','partial')) bid_shares,
                   (SELECT limit_price
                      FROM bank_stock_orders
                     WHERE stock_id=$1 AND side='sell'
                       AND status IN ('open','partial')
                     ORDER BY limit_price,created_at,id LIMIT 1) best_ask,
                   (SELECT COALESCE(SUM(remaining),0)
                      FROM bank_stock_orders
                     WHERE stock_id=$1 AND side='sell'
                       AND status IN ('open','partial')) ask_shares""",
                row["id"],
            )
            trades = await conn.fetch(
                """SELECT shares,execution_price,created_at FROM bank_stock_trades
                    WHERE stock_id=$1 ORDER BY created_at DESC,id DESC LIMIT 3""",
                row["id"],
            )
        if evaluation:
            if is_unscored_market_evaluation(evaluation):
                eval_text = (
                    f"평가일 {evaluation['evaluation_date']}\n"
                    f"점수 미등록 · 무작위 변동 {signed(evaluation['change_percent'])}% "
                    "(하루 -10%~+10%)\n"
                    f"가격 {fmt(evaluation['old_price'])} → {fmt(evaluation['new_price'])}"
                )
            else:
                eval_text = (
                    f"평가일 {evaluation['evaluation_date']}\n기본 {signed(evaluation['base_score'])}점 + 무작위 {signed(evaluation['random_score'])}점 = **{signed(evaluation['final_score'])}점**\n"
                    f"콘텐츠 {signed(evaluation['content_score'])}/6 · "
                    f"활동 {signed(evaluation['activity_score'])}/6 · "
                    f"인원 {signed(evaluation['membership_score'])}/5\n"
                    f"사건 {signed(evaluation['events_score'])}/8 · "
                    f"성장 {signed(evaluation['growth_score'])}/5 · "
                    f"영향력 {signed(evaluation['influence_score'])}/5 · "
                    f"여론 {signed(evaluation['opinion_score'])}/5\n"
                    f"가격 {fmt(evaluation['old_price'])} → {fmt(evaluation['new_price'])} "
                    f"({signed(evaluation['change_percent'])}%)"
                )
        else:
            eval_text = "아직 공개된 평가가 없습니다."
        embed = discord.Embed(
            title=row["name"],
            description=row["description"] or "종목 소개가 아직 등록되지 않았습니다.",
            color=0x207E66,
        )
        embed.add_field(
            name="현재 기준가",
            value=f"{fmt(row['current_price'])} 기본재화"
            + (f" · {signed(evaluation['change_percent'])}%" if evaluation else ""),
            inline=True,
        )
        embed.add_field(
            name="발행·유통 규모",
            value=f"{fmt(row['total_shares'])}주\n시가총액 {fmt(row['market_cap'])} 기본재화",
            inline=True,
        )
        embed.add_field(
            name="주문 호가",
            value=(
                f"최고 매수: {fmt(book['best_bid']) if book['best_bid'] is not None else '없음'}"
                f" · {fmt(book['bid_shares'])}주\n"
                f"최저 매도: {fmt(book['best_ask']) if book['best_ask'] is not None else '없음'}"
                f" · {fmt(book['ask_shares'])}주"
            ),
            inline=False,
        )
        embed.add_field(name="최근 세부 평가", value=eval_text, inline=False)
        if evaluation:
            embed.add_field(
                name="평가 근거", value=evaluation["evidence"], inline=False
            )
        embed.add_field(
            name="최근 체결",
            value="\n".join(
                f"<t:{int(trade['created_at'].timestamp())}:R> · "
                f"{fmt(trade['shares'])}주 × {fmt(trade['execution_price'])}"
                for trade in trades
            )
            or "아직 체결된 거래가 없습니다.",
            inline=False,
        )
        await send_public(interaction, embed=embed)

    await safe_command(interaction, run)


bot.tree.add_command(stock_group)


async def find_stock(
    conn: asyncpg.Connection, guild_id: str, stock_name: str, *, lock: bool = False
) -> asyncpg.Record:
    row = await conn.fetchrow(
        f"""SELECT id,name,description,current_price,total_shares,
                   current_price::numeric*total_shares market_cap,listed
              FROM bank_stocks
             WHERE guild_id=$1 AND lower(trim(name))=lower(trim($2))
             LIMIT 1{" FOR UPDATE" if lock else ""}""",
        guild_id,
        stock_name,
    )
    if not row:
        raise ValueError(f"종목 이름 '{stock_name}'을(를) 찾을 수 없습니다.")
    if not row["listed"]:
        raise ValueError("상장 폐지된 종목입니다.")
    return row


async def place_order(
    guild_id: str,
    user_id: str,
    stock_name: str,
    side: str,
    quantity: int,
    limit_price: int,
) -> dict:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    if 1230 <= now.hour * 60 + now.minute < 1260:
        raise ValueError("20:30~21:00 시세 산정 시간에는 주문할 수 없습니다.")
    async with pool.acquire() as conn:
        async with conn.transaction():
            acct = await account(conn, guild_id, user_id, lock=True)
            stock = await find_stock(conn, guild_id, stock_name, lock=True)
            base = await base_currency(conn, guild_id)
            if side == "buy":
                cost = quantity * limit_price
                if cost > 9_007_199_254_740_991:
                    raise ValueError("주문 금액이 너무 큽니다.")
                await ensure_balance(conn, acct["id"], base["id"])
                balance_row = await conn.fetchrow(
                    "SELECT wallet FROM bank_balances WHERE account_id=$1 AND currency_id=$2 FOR UPDATE",
                    acct["id"],
                    base["id"],
                )
                if int(balance_row["wallet"]) < cost:
                    raise ValueError("주문 금액을 지갑에서 확보할 수 없습니다.")
                await conn.execute(
                    "UPDATE bank_balances SET wallet=wallet-$1 WHERE account_id=$2 AND currency_id=$3",
                    cost,
                    acct["id"],
                    base["id"],
                )
            else:
                holding = (
                    await conn.fetchval(
                        "SELECT shares FROM bank_stock_holdings WHERE stock_id=$1 AND account_id=$2",
                        stock["id"],
                        acct["id"],
                    )
                    or 0
                )
                reserved = await conn.fetchval(
                    """SELECT COALESCE(SUM(remaining),0) FROM bank_stock_orders
                        WHERE stock_id=$1 AND account_id=$2 AND side='sell' AND status IN ('open','partial')""",
                    stock["id"],
                    acct["id"],
                )
                if int(holding) - int(reserved) < quantity:
                    raise ValueError("매도 가능한 보유 주식 수가 부족합니다.")

            created = await conn.fetchrow(
                """INSERT INTO bank_stock_orders
                     (guild_id,stock_id,account_id,side,limit_price,quantity,remaining)
                   VALUES ($1,$2,$3,$4,$5,$6,$6) RETURNING id""",
                guild_id,
                stock["id"],
                acct["id"],
                side,
                limit_price,
                quantity,
            )
            remaining = quantity
            opposite = "sell" if side == "buy" else "buy"
            matches = await conn.fetch(
                """SELECT id,account_id,limit_price,remaining
                     FROM bank_stock_orders
                    WHERE stock_id=$1 AND side=$2 AND status IN ('open','partial')
                      AND account_id<>$3
                      AND (($4='buy' AND limit_price<=$5) OR ($4='sell' AND limit_price>=$5))
                    ORDER BY CASE WHEN $4='buy' THEN limit_price END ASC,
                             CASE WHEN $4='sell' THEN limit_price END DESC,
                             created_at,id
                    FOR UPDATE""",
                stock["id"],
                opposite,
                acct["id"],
                side,
                limit_price,
            )
            for resting in matches:
                if remaining <= 0:
                    break
                fill = min(remaining, int(resting["remaining"]))
                execution_price = int(resting["limit_price"])
                gross = fill * execution_price
                fee = (gross * 75 + 500) // 1000
                buyer_id = acct["id"] if side == "buy" else resting["account_id"]
                seller_id = acct["id"] if side == "sell" else resting["account_id"]
                if side == "buy" and limit_price > execution_price:
                    await conn.execute(
                        "UPDATE bank_balances SET wallet=wallet+$1 WHERE account_id=$2 AND currency_id=$3",
                        fill * (limit_price - execution_price),
                        acct["id"],
                        base["id"],
                    )
                await conn.execute(
                    """INSERT INTO bank_balances (account_id,currency_id,wallet)
                       VALUES ($1,$2,$3)
                       ON CONFLICT (account_id,currency_id)
                       DO UPDATE SET wallet=bank_balances.wallet+EXCLUDED.wallet""",
                    seller_id,
                    base["id"],
                    gross - fee,
                )
                await conn.execute(
                    """INSERT INTO bank_stock_holdings (stock_id,account_id,shares)
                       VALUES ($1,$2,$3)
                       ON CONFLICT (stock_id,account_id)
                       DO UPDATE SET shares=bank_stock_holdings.shares+EXCLUDED.shares""",
                    stock["id"],
                    buyer_id,
                    fill,
                )
                await conn.execute(
                    "UPDATE bank_stock_holdings SET shares=shares-$1 WHERE stock_id=$2 AND account_id=$3",
                    fill,
                    stock["id"],
                    seller_id,
                )
                await conn.execute(
                    """UPDATE bank_stock_orders
                          SET remaining=remaining-$1,
                              status=CASE WHEN remaining-$1=0 THEN 'filled' ELSE 'partial' END
                        WHERE id=$2""",
                    fill,
                    resting["id"],
                )
                await conn.execute(
                    """INSERT INTO bank_stock_trades
                         (guild_id,stock_id,buyer_account_id,seller_account_id,currency_id,
                          shares,execution_price,gross_amount,fee)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)""",
                    guild_id,
                    stock["id"],
                    buyer_id,
                    seller_id,
                    base["id"],
                    fill,
                    execution_price,
                    gross,
                    fee,
                )
                await record_transaction(
                    conn,
                    guild_id,
                    "stock_buy",
                    base["id"],
                    gross,
                    actor_id=buyer_id,
                    target_id=seller_id,
                    description=f"{stock['name']} {fill}주 매수",
                    metadata={
                        "stockId": stock["id"],
                        "shares": fill,
                        "price": execution_price,
                    },
                )
                await record_transaction(
                    conn,
                    guild_id,
                    "stock_sell",
                    base["id"],
                    gross - fee,
                    actor_id=seller_id,
                    target_id=buyer_id,
                    fee=fee,
                    description=f"{stock['name']} {fill}주 매도",
                    metadata={
                        "stockId": stock["id"],
                        "shares": fill,
                        "price": execution_price,
                    },
                )
                remaining -= fill
            await conn.execute(
                """UPDATE bank_stock_orders SET remaining=$1,
                     status=CASE WHEN $1=0 THEN 'filled' ELSE 'open' END WHERE id=$2""",
                remaining,
                created["id"],
            )
    return {
        "order_id": created["id"],
        "filled": quantity - remaining,
        "remaining": remaining,
        "stock": stock,
    }


@stock_group.command(name="buy", description="지정가 매수 주문을 냅니다")
async def stock_buy(
    interaction: discord.Interaction,
    stock: str,
    shares: app_commands.Range[int, 1, 2147483647],
    limit_price: app_commands.Range[int, 1, 2147483647],
) -> None:
    async def run():
        result = await place_order(
            require_guild(interaction),
            str(interaction.user.id),
            stock,
            "buy",
            shares,
            limit_price,
        )
        await send_private(
            interaction,
            f"**{result['stock']['name']}** 주문 #{result['order_id']} · 매수 {fmt(shares)}주\n지정가 {fmt(limit_price)} · 즉시 체결 {fmt(result['filled'])}주 · 미체결 {fmt(result['remaining'])}주.",
        )

    await safe_command(interaction, run)


@stock_group.command(name="sell", description="보유 주식의 지정가 매도 주문을 냅니다")
async def stock_sell(
    interaction: discord.Interaction,
    stock: str,
    shares: app_commands.Range[int, 1, 2147483647],
    limit_price: app_commands.Range[int, 1, 2147483647],
) -> None:
    async def run():
        result = await place_order(
            require_guild(interaction),
            str(interaction.user.id),
            stock,
            "sell",
            shares,
            limit_price,
        )
        await send_private(
            interaction,
            f"**{result['stock']['name']}** 주문 #{result['order_id']} · 매도 {fmt(shares)}주\n지정가 {fmt(limit_price)} · 즉시 체결 {fmt(result['filled'])}주 · 미체결 {fmt(result['remaining'])}주.",
        )

    await safe_command(interaction, run)


@stock_group.command(name="orders", description="내 미체결 주문을 확인합니다")
async def stock_orders(interaction: discord.Interaction) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            acct = await account(
                conn, guild_id, str(interaction.user.id), allow_frozen=True
            )
            rows = await conn.fetch(
                """SELECT o.id,s.name,o.side,o.limit_price,o.quantity,o.remaining,o.status
                     FROM bank_stock_orders o JOIN bank_stocks s ON s.id=o.stock_id
                    WHERE o.guild_id=$1 AND o.account_id=$2 AND o.status IN ('open','partial')
                    ORDER BY o.created_at,o.id""",
                guild_id,
                acct["id"],
            )
        text = (
            "\n".join(
                f"**{r['name']}** · #{r['id']} {'매수' if r['side'] == 'buy' else '매도'} · 지정가 {fmt(r['limit_price'])}\n"
                f"{'일부 체결' if r['status'] == 'partial' else '대기 중'} · 체결 {fmt(r['quantity'] - r['remaining'])}/{fmt(r['quantity'])}주 · 잔량 {fmt(r['remaining'])}주"
                for r in rows
            )
            or "미체결 주문이 없습니다."
        )
        await send_private(interaction, text)

    await safe_command(interaction, run)


@stock_group.command(name="cancel", description="본인 미체결 주문을 취소합니다")
async def stock_cancel(
    interaction: discord.Interaction, order_id: app_commands.Range[int, 1, 2147483647]
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        refund = 0
        async with pool.acquire() as conn:
            async with conn.transaction():
                acct = await account(
                    conn,
                    guild_id,
                    str(interaction.user.id),
                    lock=True,
                    allow_frozen=True,
                )
                order = await conn.fetchrow(
                    """SELECT id,side,remaining,limit_price FROM bank_stock_orders
                        WHERE id=$1 AND guild_id=$2 AND account_id=$3
                          AND status IN ('open','partial') FOR UPDATE""",
                    order_id,
                    guild_id,
                    acct["id"],
                )
                if not order:
                    raise ValueError("취소할 수 있는 본인 주문이 없습니다.")
                if order["side"] == "buy":
                    base = await base_currency(conn, guild_id)
                    refund = order["remaining"] * order["limit_price"]
                    await conn.execute(
                        """INSERT INTO bank_balances (account_id,currency_id,wallet) VALUES ($1,$2,$3)
                           ON CONFLICT (account_id,currency_id)
                           DO UPDATE SET wallet=bank_balances.wallet+EXCLUDED.wallet""",
                        acct["id"],
                        base["id"],
                        refund,
                    )
                await conn.execute(
                    "UPDATE bank_stock_orders SET status='cancelled',remaining=0 WHERE id=$1",
                    order_id,
                )
        await send_private(
            interaction,
            f"주문 #{order_id}을 취소했습니다."
            + (
                f" 확보해 둔 {fmt(refund)}을 지갑으로 돌려드렸습니다." if refund else ""
            ),
        )

    await safe_command(interaction, run)


@bot.tree.command(
    name="portfolio", description="보유 주식과 현재 기준 평가액을 확인합니다"
)
async def portfolio(interaction: discord.Interaction) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            acct = await account(
                conn, guild_id, str(interaction.user.id), allow_frozen=True
            )
            rows = await conn.fetch(
                """SELECT s.name,s.current_price,h.shares,h.shares*s.current_price market_value,s.listed
                     FROM bank_stock_holdings h JOIN bank_stocks s ON s.id=h.stock_id
                    WHERE s.guild_id=$1 AND h.account_id=$2 AND h.shares>0
                    ORDER BY s.listed DESC,lower(s.name),s.name""",
                guild_id,
                acct["id"],
            )
        if not rows:
            await send_private(interaction, "보유 중인 가상주식이 없습니다.")
            return
        embed = discord.Embed(
            title="내 가상주식 포트폴리오",
            description="현재 기준가로 계산한 참고 평가액입니다. 실제 매도 금액과 다를 수 있습니다.",
            color=0x207E66,
        )
        for row in rows[:24]:
            embed.add_field(
                name=row["name"],
                value=f"{fmt(row['shares'])}주 × 기준가 {fmt(row['current_price'])}\n현재 평가액 **{fmt(row['market_value'])}**"
                + ("" if row["listed"] else " · 상장 폐지"),
                inline=False,
            )
        embed.set_footer(
            text=f"보유 종목 {len(rows)}개"
            if len(rows) <= 24
            else f"총 {len(rows)}종목 · 이름순 24종목 표시"
        )
        await send_public(interaction, embed=embed)

    await safe_command(interaction, run)


@bot.tree.command(name="help", description="은행 봇 사용법과 전체 명령어를 확인합니다")
async def help_command(interaction: discord.Interaction) -> None:
    language = await get_user_language(interaction.user.id)
    await send_public(
        interaction,
        embed=build_help_embed(language),
        view=BankMenuView(interaction.user.id, language),
        language=language,
    )


def build_help_embed(language: str) -> discord.Embed:
    english = language == "en"
    embed = discord.Embed(
        title="ROBELLANK Bank Bot Help" if english else "ROBELLANK 은행 봇 도움말",
        color=BANK_GOLD,
    )
    embed.description = (
        "Commands are grouped into user and administrator sections below. "
        "Administrator-only commands require server administrator permissions.\n\n"
        "Rumors are unverified posts written by server staff. Game currency and tier roles "
        "are verified and managed by administrators."
        if english
        else "아래에서 일반 이용자 명령과 관리자 전용 명령을 구분했습니다. "
        "`관리자 전용` 표기가 있는 명령은 서버 관리자만 사용할 수 있습니다.\n\n"
        "찌라시는 운영진 작성 미확인 정보이며 사실 여부와 투자 결과를 보장하지 않습니다. "
        "게임 재화는 사용자가 직접 등록하지 않으며, 관리자가 게임에서 확인한 뒤 지급합니다. "
        "등급 역할도 관리자가 직접 부여하며 봇은 역할을 변경하지 않습니다."
    )
    leaf_commands = [
        command
        for command in bot.tree.walk_commands()
        if not isinstance(command, app_commands.Group)
    ]
    public_commands = [command for command in leaf_commands if not command.checks]
    admin_commands = [command for command in leaf_commands if command.checks]

    def add_command_fields(title: str, commands: list[app_commands.Command]) -> None:
        lines = [
            f"/{command.qualified_name} — "
            f"{translate_known_text(command.description, language)}"
            for command in commands
        ]
        chunks: list[list[str]] = []
        current: list[str] = []
        current_length = 0
        for line in lines:
            line_length = len(line) + (1 if current else 0)
            if current and current_length + line_length > 1000:
                chunks.append(current)
                current = []
                current_length = 0
                line_length = len(line)
            current.append(line)
            current_length += line_length
        if current:
            chunks.append(current)

        for index, chunk in enumerate(chunks):
            field_name = title if index == 0 else f"{title} (continued)"
            embed.add_field(name=field_name, value="\n".join(chunk), inline=False)

    add_command_fields(
        "User commands" if english else "일반 이용자 명령어", public_commands
    )
    add_command_fields(
        "Administrator commands" if english else "관리자 전용 명령어",
        admin_commands,
    )
    return embed


def build_main_menu_embed(language: str) -> discord.Embed:
    if language == "en":
        return discord.Embed(
            title="ROBELLANK Bank",
            description=(
                "Use the buttons below to open help, browse listed stocks, or switch "
                "your language. Your language choice is saved to your Discord account."
            ),
            color=BANK_GOLD,
        )
    return discord.Embed(
        title="ROBELLANK 은행",
        description=(
            "아래 버튼으로 도움말을 열고, 상장 종목을 보거나, 표시 언어를 바꿀 수 있습니다. "
            "언어 설정은 디스코드 사용자별로 저장됩니다."
        ),
        color=BANK_GOLD,
    )


def build_stock_list_embed(
    rows: list[asyncpg.Record], language: str
) -> discord.Embed:
    english = language == "en"
    embed = discord.Embed(
        title="Guild stocks" if english else "길드 가상주식",
        description=(
            "Reference prices are informational; trades execute at matched order prices."
            if english
            else "기준가는 참고 가격이며 실제 체결가는 주문 매칭 결과에 따릅니다."
        ),
        color=BANK_GOLD,
    )
    if not rows:
        embed.description = (
            "There are no listed stocks." if english else "상장 종목이 없습니다."
        )
    for stock in rows[:24]:
        change = (
            "Not evaluated"
            if stock["change_percent"] is None and english
            else "평가 전"
            if stock["change_percent"] is None
            else f"{signed(stock['change_percent'])}%"
        )
        embed.add_field(
            name=stock["name"],
            value=(
                f"Reference price **{fmt(stock['current_price'])}** · daily {change}\n"
                f"{fmt(stock['total_shares'])} shares · Market cap {fmt(stock['market_cap'])}"
                if english
                else f"기준가 **{fmt(stock['current_price'])}** · 일간 {change}\n"
                f"유통 {fmt(stock['total_shares'])}주 · 시가총액 {fmt(stock['market_cap'])}"
            ),
            inline=False,
        )
    if english:
        embed.set_footer(text=f"{len(rows)} listed stocks")
    else:
        embed.set_footer(text=f"총 {len(rows)}종목 · 자세한 내용은 /stock quote")
    return embed


class BankMenuView(discord.ui.View):
    def __init__(self, owner_id: int, language: str):
        super().__init__(timeout=300)
        self.owner_id = owner_id
        labels = (
            [
                ("menu", "Menu", discord.ButtonStyle.secondary),
                ("help", "Help", discord.ButtonStyle.primary),
                ("stocks", "Stocks", discord.ButtonStyle.primary),
                ("language", "Language: English", discord.ButtonStyle.success),
            ]
            if language == "en"
            else [
                ("menu", "메뉴", discord.ButtonStyle.secondary),
                ("help", "도움말", discord.ButtonStyle.primary),
                ("stocks", "주식 목록", discord.ButtonStyle.primary),
                ("language", "언어: 한국어", discord.ButtonStyle.success),
            ]
        )
        for action, label, style in labels:
            button = discord.ui.Button(
                label=label, style=style, custom_id=f"robellank-menu:{action}"
            )

            async def callback(
                interaction: discord.Interaction, selected_action: str = action
            ) -> None:
                await self.handle_action(interaction, selected_action)

            button.callback = callback
            self.add_item(button)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await send_public(
                interaction,
                "이 메뉴는 명령을 실행한 사용자만 사용할 수 있습니다.",
            )
            return False
        return True

    async def handle_action(
        self, interaction: discord.Interaction, action: str
    ) -> None:
        try:
            language = await get_user_language(interaction.user.id)
            if action == "language":
                language = "en" if language == "ko" else "ko"
                await set_user_language(interaction.user.id, language)
                embed = build_main_menu_embed(language)
            elif action == "help":
                embed = build_help_embed(language)
            elif action == "stocks":
                rows = await list_stocks(require_guild(interaction))
                embed = build_stock_list_embed(rows, language)
            else:
                embed = build_main_menu_embed(language)
            await interaction.response.edit_message(
                embed=localize_embed(embed, language),
                view=BankMenuView(interaction.user.id, language),
            )
        except Exception:
            logger.exception("Bank menu action failed")
            await send_public(
                interaction,
                "메뉴를 열지 못했습니다. 다시 시도하거나 관리자에게 문의하세요.",
            )


@bot.tree.command(name="menu", description="은행 메뉴와 주식 목록을 엽니다")
async def menu_command(interaction: discord.Interaction) -> None:
    language = await get_user_language(interaction.user.id)
    await send_public(
        interaction,
        embed=build_main_menu_embed(language),
        view=BankMenuView(interaction.user.id, language),
        language=language,
    )


@bot.tree.command(name="language", description="봇 응답 언어를 한국어 또는 English로 설정합니다")
@app_commands.choices(
    language=[
        app_commands.Choice(name="한국어", value="ko"),
        app_commands.Choice(name="English", value="en"),
    ]
)
async def language_command(
    interaction: discord.Interaction, language: app_commands.Choice[str]
) -> None:
    await set_user_language(interaction.user.id, language.value)
    confirmation = (
        "Your bot language is now English."
        if language.value == "en"
        else "봇 응답 언어를 한국어로 설정했습니다."
    )
    await send_public(interaction, confirmation, language=language.value)


loan_group = app_commands.Group(name="loan", description="대출 신청·상환·조회")


@loan_group.command(name="request", description="골드 이상: 벨 신용 대출을 신청합니다")
async def loan_request(
    interaction: discord.Interaction,
    currency: str,
    amount: app_commands.Range[int, 1, 2147483647],
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        tier_key = tier_for(interaction.user)
        if not tier_at_least(tier_key, "gold"):
            raise ValueError("신용 대출은 골드 등급 이상부터 신청할 수 있습니다.")
        async with pool.acquire() as conn:
            async with conn.transaction():
                acct = await account(
                    conn, guild_id, str(interaction.user.id), lock=True
                )
                await conn.execute(
                    "UPDATE bank_accounts SET tier_key=$1 WHERE id=$2",
                    tier_key,
                    acct["id"],
                )
                currency_row = await get_currency(conn, guild_id, currency, lock=True)
                if currency_row["name"] != "벨":
                    raise ValueError("신용 대출은 벨로만 신청할 수 있습니다.")
                await conn.execute(
                    "INSERT INTO bank_tier_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING",
                    guild_id,
                )
                settings = await conn.fetchrow(
                    "SELECT platinum_loan_bonus FROM bank_tier_settings WHERE guild_id=$1",
                    guild_id,
                )
                limit = acct["credit_score"] * 10000 + (
                    int(settings["platinum_loan_bonus"])
                    if tier_at_least(tier_key, "platinum")
                    else 0
                )
                used = await conn.fetchval(
                    """SELECT COALESCE(SUM(CASE WHEN status='approved' THEN amount_due ELSE principal END),0)
                         FROM bank_loans WHERE guild_id=$1 AND account_id=$2 AND currency_id=$3
                           AND loan_type='credit' AND status IN ('pending','approved')""",
                    guild_id,
                    acct["id"],
                    currency_row["id"],
                )
                available = limit - int(used)
                if amount > available:
                    raise ValueError(
                        f"신용 대출 한도를 초과합니다. 현재 한도 {fmt(limit)}벨, 사용 중 {fmt(used)}벨입니다."
                    )
                loan = await conn.fetchrow(
                    """INSERT INTO bank_loans
                         (guild_id,account_id,currency_id,principal,amount_due,rate,status,loan_type,requested_tier)
                       VALUES ($1,$2,$3,$4,$4,$5,'pending','credit',$6) RETURNING id""",
                    guild_id,
                    acct["id"],
                    currency_row["id"],
                    amount,
                    currency_row["loan_rate"],
                    tier_key,
                )
        await send_private(
            interaction,
            f"신용 대출 신청 #{loan['id']}을 접수했습니다. 한도 {fmt(limit)}벨 중 신청 후 남은 한도 {fmt(available - amount)}벨입니다. 관리자 승인을 기다려 주세요.",
        )

    await safe_command(interaction, run)


@loan_group.command(
    name="collateral-request",
    description="실버 이상: 게임에서 확인받을 담보 대출을 신청합니다",
)
async def collateral_request(
    interaction: discord.Interaction,
    item: str,
    quantity: app_commands.Range[int, 1, 2147483647],
    amount: app_commands.Range[int, 1, 2147483647],
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        tier_key = tier_for(interaction.user)
        if not tier_at_least(tier_key, "silver"):
            raise ValueError("담보 대출은 실버 등급 이상부터 신청할 수 있습니다.")
        item_name = unicodedata.normalize("NFKC", item.strip())
        if not item_name:
            raise ValueError("담보 아이템 이름을 입력하세요.")
        async with pool.acquire() as conn:
            async with conn.transaction():
                acct = await account(
                    conn, guild_id, str(interaction.user.id), lock=True
                )
                await conn.execute(
                    "UPDATE bank_accounts SET tier_key=$1 WHERE id=$2",
                    tier_key,
                    acct["id"],
                )
                currency_row = await get_currency(conn, guild_id, "벨", lock=True)
                loan = await conn.fetchrow(
                    """INSERT INTO bank_loans
                         (guild_id,account_id,currency_id,principal,amount_due,rate,status,loan_type,
                          requested_tier,collateral_item,collateral_quantity,collateral_status)
                       VALUES ($1,$2,$3,$4,$4,$5,'pending','collateral',$6,$7,$8,'pending')
                       RETURNING id""",
                    guild_id,
                    acct["id"],
                    currency_row["id"],
                    amount,
                    currency_row["loan_rate"],
                    tier_key,
                    item_name,
                    quantity,
                )
        await send_private(
            interaction,
            f"담보 대출 신청 #{loan['id']}을 접수했습니다: {item_name} {fmt(quantity)}개 · {fmt(amount)}벨. 관리자가 게임 내 담보와 가치를 확인한 뒤 승인합니다.",
        )

    await safe_command(interaction, run)


@loan_group.command(name="list", description="내 대출 목록")
async def loan_list(interaction: discord.Interaction) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            acct = await account(
                conn, guild_id, str(interaction.user.id), allow_frozen=True
            )
            rows = await conn.fetch(
                """SELECT l.id,c.name currency,l.principal,l.amount_due,l.rate,l.status,l.loan_type,
                          l.collateral_item,l.collateral_quantity,l.collateral_value,l.collateral_status,
                          l.due_at,l.extension_count,l.created_at
                     FROM bank_loans l JOIN bank_currencies c ON c.id=l.currency_id
                    WHERE l.guild_id=$1 AND l.account_id=$2 ORDER BY l.id DESC LIMIT 15""",
                guild_id,
                acct["id"],
            )

        def loan_line(row):
            kind = "담보" if row["loan_type"] == "collateral" else "신용"
            collateral = (
                f" · 담보 {row['collateral_item']} {fmt(row['collateral_quantity'])}개 · 확인 가치 {fmt(row['collateral_value'])}벨 · {row['collateral_status']}"
                if row["loan_type"] == "collateral"
                else ""
            )
            due = (
                f" · 만기 <t:{int(row['due_at'].timestamp())}:d>"
                if row["due_at"]
                else ""
            )
            return f"#{row['id']} {kind} · 원금 {fmt(row['principal'])} · 남은 원리금 {fmt(row['amount_due'])} · 일 {row['rate']}% · {row['status']}{due}{collateral}"

        await send_private(
            interaction,
            "\n".join(loan_line(row) for row in rows) or "대출 내역이 없습니다.",
        )

    await safe_command(interaction, run)


@loan_group.command(name="repay", description="대출을 상환합니다")
async def loan_repay(
    interaction: discord.Interaction,
    loan_id: app_commands.Range[int, 1, 2147483647],
    amount: app_commands.Range[int, 1, 2147483647],
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            async with conn.transaction():
                acct = await account(
                    conn, guild_id, str(interaction.user.id), lock=True
                )
                loan = await conn.fetchrow(
                    """SELECT id,account_id,currency_id,amount_due,status,loan_type
                         FROM bank_loans WHERE id=$1 AND guild_id=$2 FOR UPDATE""",
                    loan_id,
                    guild_id,
                )
                if (
                    not loan
                    or loan["account_id"] != acct["id"]
                    or loan["status"] != "approved"
                ):
                    raise ValueError("상환 가능한 본인 대출을 찾을 수 없습니다.")
                payment = min(amount, int(loan["amount_due"]))
                await ensure_balance(conn, acct["id"], loan["currency_id"])
                balance_row = await conn.fetchrow(
                    "SELECT wallet FROM bank_balances WHERE account_id=$1 AND currency_id=$2 FOR UPDATE",
                    acct["id"],
                    loan["currency_id"],
                )
                if int(balance_row["wallet"]) < payment:
                    raise ValueError("지갑 잔액이 부족합니다.")
                remaining = int(loan["amount_due"]) - payment
                await conn.execute(
                    "UPDATE bank_balances SET wallet=wallet-$1 WHERE account_id=$2 AND currency_id=$3",
                    payment,
                    acct["id"],
                    loan["currency_id"],
                )
                await conn.execute(
                    """UPDATE bank_loans SET amount_due=$1,status=$2,
                         collateral_status=CASE WHEN $2='repaid' AND loan_type='collateral' THEN 'return_due' ELSE collateral_status END
                       WHERE id=$3""",
                    remaining,
                    "repaid" if remaining == 0 else "approved",
                    loan_id,
                )
                await record_transaction(
                    conn,
                    guild_id,
                    "loan_repayment",
                    loan["currency_id"],
                    payment,
                    actor_id=acct["id"],
                    target_id=acct["id"],
                    description=f"대출 #{loan_id} 상환",
                )
        await send_private(
            interaction, f"{fmt(payment)} 상환했습니다. 남은 원리금: {fmt(remaining)}."
        )

    await safe_command(interaction, run)


@loan_group.command(name="extend", description="실버 이상: 대출 기간을 연장합니다")
async def loan_extend(
    interaction: discord.Interaction, loan_id: app_commands.Range[int, 1, 2147483647]
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        tier_key = tier_for(interaction.user)
        if not tier_at_least(tier_key, "silver"):
            raise ValueError("대출 기간 연장은 실버 등급 이상부터 사용할 수 있습니다.")
        async with pool.acquire() as conn:
            async with conn.transaction():
                acct = await account(
                    conn, guild_id, str(interaction.user.id), lock=True
                )
                loan = await conn.fetchrow(
                    "SELECT id,account_id,due_at,extension_count,status FROM bank_loans WHERE id=$1 AND guild_id=$2 FOR UPDATE",
                    loan_id,
                    guild_id,
                )
                if (
                    not loan
                    or loan["account_id"] != acct["id"]
                    or loan["status"] != "approved"
                    or not loan["due_at"]
                ):
                    raise ValueError("연장할 수 있는 본인 대출을 찾을 수 없습니다.")
                settings = await conn.fetchrow(
                    "SELECT loan_extension_days,loan_extension_limit FROM bank_tier_settings WHERE guild_id=$1",
                    guild_id,
                )
                days, limit = (
                    settings["loan_extension_days"],
                    settings["loan_extension_limit"],
                )
                if days <= 0 or limit <= 0:
                    raise ValueError(
                        "관리자가 대출 연장 기간과 횟수를 아직 설정하지 않았습니다."
                    )
                if loan["extension_count"] >= limit:
                    raise ValueError("이 대출은 설정된 연장 횟수를 모두 사용했습니다.")
                updated = await conn.fetchrow(
                    """UPDATE bank_loans SET due_at=GREATEST(due_at,now())+($1::int*INTERVAL '1 day'),
                         extension_count=extension_count+1 WHERE id=$2 RETURNING due_at""",
                    days,
                    loan_id,
                )
                await conn.execute(
                    "INSERT INTO bank_loan_extensions (loan_id,discord_user_id,days,old_due_at,new_due_at) VALUES ($1,$2,$3,$4,$5)",
                    loan_id,
                    str(interaction.user.id),
                    days,
                    loan["due_at"],
                    updated["due_at"],
                )
        await send_private(
            interaction,
            f"대출 #{loan_id} 만기를 {days}일 연장했습니다. 새 만기: <t:{int(updated['due_at'].timestamp())}:F>",
        )

    await safe_command(interaction, run)


@loan_group.command(name="queue", description="관리자: 심사 대기 대출 목록")
@app_commands.checks.has_permissions(administrator=True)
async def loan_queue(interaction: discord.Interaction) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT l.id,a.discord_user_id,l.loan_type,l.requested_tier,l.principal,
                          l.collateral_item,l.collateral_quantity,l.created_at
                     FROM bank_loans l JOIN bank_accounts a ON a.id=l.account_id
                    WHERE l.guild_id=$1 AND l.status='pending'
                    ORDER BY CASE l.requested_tier WHEN 'vip' THEN 0 WHEN 'ace' THEN 1 ELSE 2 END,l.created_at LIMIT 30""",
                guild_id,
            )
        text = (
            "\n".join(
                f"#{row['id']} <@{row['discord_user_id']}> · {TIER_NAME.get(row['requested_tier'], '브론즈')} · "
                f"{'담보 ' + str(row['collateral_item']) + ' ' + fmt(row['collateral_quantity']) + '개' if row['loan_type'] == 'collateral' else '신용'} · {fmt(row['principal'])}벨"
                for row in rows
            )
            or "심사 대기 대출이 없습니다."
        )
        await send_private(interaction, text)

    await safe_command(interaction, run)


async def review_loan(
    interaction: discord.Interaction,
    loan_id: int,
    approve: bool,
    reason: str = "",
    verified_value: int | None = None,
) -> None:
    guild_id = require_guild(interaction)
    async with pool.acquire() as conn:
        async with conn.transaction():
            actor = await get_or_create_account(
                conn, guild_id, str(interaction.user.id)
            )
            loan = await conn.fetchrow(
                """SELECT l.id,l.account_id,l.currency_id,l.principal,l.status,l.loan_type,l.requested_tier,
                          l.collateral_item,l.collateral_quantity,a.discord_user_id,a.credit_score,a.frozen
                     FROM bank_loans l JOIN bank_accounts a ON a.id=l.account_id
                    WHERE l.id=$1 AND l.guild_id=$2 FOR UPDATE""",
                loan_id,
                guild_id,
            )
            if not loan or loan["status"] != "pending":
                raise ValueError("대기 중인 대출 신청을 찾을 수 없습니다.")
            if approve:
                if loan["loan_type"] == "collateral":
                    if not verified_value or verified_value <= 0:
                        raise ValueError(
                            "관리자가 게임에서 확인한 담보 가치를 입력해야 합니다."
                        )
                    if int(loan["principal"]) > verified_value:
                        raise ValueError("신청 금액이 확인된 담보 가치보다 큽니다.")
                elif verified_value is not None:
                    raise ValueError(
                        "신용 대출 승인에는 담보 가치를 입력할 수 없습니다."
                    )
                if loan["frozen"]:
                    raise ValueError("동결된 계좌에는 대출을 지급할 수 없습니다.")
                if loan["loan_type"] == "credit":
                    if not tier_at_least(loan["requested_tier"], "gold"):
                        raise ValueError(
                            "신용 대출은 골드 등급 이상만 승인할 수 있습니다."
                        )
                    await conn.execute(
                        "INSERT INTO bank_tier_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING",
                        guild_id,
                    )
                    settings = await conn.fetchrow(
                        "SELECT platinum_loan_bonus,loan_term_days FROM bank_tier_settings WHERE guild_id=$1",
                        guild_id,
                    )
                    limit = loan["credit_score"] * 10000 + (
                        int(settings["platinum_loan_bonus"])
                        if tier_at_least(loan["requested_tier"], "platinum")
                        else 0
                    )
                    used = await conn.fetchval(
                        """SELECT COALESCE(SUM(CASE WHEN status='approved' THEN amount_due ELSE principal END),0)
                             FROM bank_loans WHERE guild_id=$1 AND account_id=$2 AND currency_id=$3
                               AND loan_type='credit' AND status IN ('pending','approved') AND id<>$4""",
                        guild_id,
                        loan["account_id"],
                        loan["currency_id"],
                        loan_id,
                    )
                    if int(used) + int(loan["principal"]) > limit:
                        raise ValueError(
                            "현재 신용 대출 한도를 초과해 승인할 수 없습니다."
                        )
                else:
                    await conn.execute(
                        "INSERT INTO bank_tier_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING",
                        guild_id,
                    )
                    settings = await conn.fetchrow(
                        "SELECT loan_term_days FROM bank_tier_settings WHERE guild_id=$1",
                        guild_id,
                    )
                term = settings["loan_term_days"]
                due_at = datetime.now(UTC) + timedelta(days=term) if term > 0 else None
                await ensure_balance(conn, loan["account_id"], loan["currency_id"])
                await conn.execute(
                    "UPDATE bank_balances SET wallet=wallet+$1 WHERE account_id=$2 AND currency_id=$3",
                    loan["principal"],
                    loan["account_id"],
                    loan["currency_id"],
                )
                await conn.execute(
                    """UPDATE bank_loans SET status='approved',reviewed_at=now(),due_at=$2,collateral_value=$3,
                         collateral_status=CASE WHEN loan_type='collateral' THEN 'held' ELSE 'none' END WHERE id=$1""",
                    loan_id,
                    due_at,
                    verified_value,
                )
                await record_transaction(
                    conn,
                    guild_id,
                    "loan_disbursement",
                    loan["currency_id"],
                    int(loan["principal"]),
                    actor_id=actor["id"],
                    target_id=loan["account_id"],
                    description=f"대출 #{loan_id} 승인",
                )
            else:
                await conn.execute(
                    """UPDATE bank_loans SET status='rejected',reviewed_at=now(),
                         collateral_status=CASE WHEN loan_type='collateral' THEN 'rejected' ELSE 'none' END WHERE id=$1""",
                    loan_id,
                )
                await record_transaction(
                    conn,
                    guild_id,
                    "loan_rejected",
                    loan["currency_id"],
                    0,
                    actor_id=actor["id"],
                    target_id=loan["account_id"],
                    description=reason or f"대출 #{loan_id} 거절",
                )


@loan_group.command(name="approve", description="신용 대출 신청을 승인합니다")
@app_commands.checks.has_permissions(administrator=True)
async def loan_approve(
    interaction: discord.Interaction, loan_id: app_commands.Range[int, 1, 2147483647]
) -> None:
    async def run():
        await review_loan(interaction, loan_id, True)
        await send_private(interaction, f"대출 #{loan_id}을 승인하고 지급했습니다.")

    await safe_command(interaction, run)


@loan_group.command(
    name="collateral-approve", description="게임 내 담보를 확인해 승인합니다"
)
@app_commands.checks.has_permissions(administrator=True)
async def collateral_approve(
    interaction: discord.Interaction,
    loan_id: app_commands.Range[int, 1, 2147483647],
    verified_value: app_commands.Range[int, 1, 2147483647],
) -> None:
    async def run():
        await review_loan(interaction, loan_id, True, verified_value=verified_value)
        await send_private(
            interaction,
            f"담보 대출 #{loan_id}을 확인된 가치 {fmt(verified_value)}벨로 승인했습니다.",
        )

    await safe_command(interaction, run)


@loan_group.command(name="reject", description="대출 신청을 거절합니다")
@app_commands.checks.has_permissions(administrator=True)
async def loan_reject(
    interaction: discord.Interaction,
    loan_id: app_commands.Range[int, 1, 2147483647],
    reason: str,
) -> None:
    async def run():
        await review_loan(interaction, loan_id, False, reason)
        await send_private(interaction, f"대출 #{loan_id} 신청을 거절했습니다.")

    await safe_command(interaction, run)


@loan_group.command(
    name="collateral-return", description="상환 완료된 담보의 게임 내 반환을 기록합니다"
)
@app_commands.checks.has_permissions(administrator=True)
async def collateral_return(
    interaction: discord.Interaction,
    loan_id: app_commands.Range[int, 1, 2147483647],
    reason: str,
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            async with conn.transaction():
                loan = await conn.fetchrow(
                    """SELECT l.id,a.discord_user_id,l.loan_type,l.status,l.collateral_item,
                              l.collateral_quantity,l.collateral_status
                         FROM bank_loans l JOIN bank_accounts a ON a.id=l.account_id
                        WHERE l.id=$1 AND l.guild_id=$2 FOR UPDATE""",
                    loan_id,
                    guild_id,
                )
                if (
                    not loan
                    or loan["loan_type"] != "collateral"
                    or loan["status"] != "repaid"
                    or loan["collateral_status"] != "return_due"
                ):
                    raise ValueError("반환 가능한 상환 완료 담보를 찾을 수 없습니다.")
                await conn.execute(
                    "UPDATE bank_loans SET collateral_status='returned' WHERE id=$1",
                    loan_id,
                )
                await conn.execute(
                    """INSERT INTO bank_vault_history
                         (guild_id,actor_discord_user_id,target_discord_user_id,item_name,quantity,operation,reason)
                       VALUES ($1,$2,$3,$4,$5,'collateral_return',$6)""",
                    guild_id,
                    str(interaction.user.id),
                    loan["discord_user_id"],
                    loan["collateral_item"],
                    loan["collateral_quantity"],
                    reason,
                )
        await send_private(
            interaction,
            f"대출 #{loan_id} 담보 반환을 기록했습니다: {loan['collateral_item']} {fmt(loan['collateral_quantity'])}개 · <@{loan['discord_user_id']}>",
        )

    await safe_command(interaction, run)


bot.tree.add_command(loan_group)


credit_group = app_commands.Group(
    name="credit", description="관리자: 신용점수를 조정합니다"
)


@credit_group.command(
    name="set", description="관리자 재량으로 신용점수를 직접 설정합니다"
)
@app_commands.checks.has_permissions(administrator=True)
async def credit_set(
    interaction: discord.Interaction,
    user: discord.User,
    score: app_commands.Range[int, 0, 100],
    reason: str,
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            async with conn.transaction():
                target = await account(
                    conn, guild_id, str(user.id), lock=True, allow_frozen=True
                )
                old_score = target["credit_score"]
                await conn.execute(
                    "UPDATE bank_accounts SET credit_score=$1 WHERE id=$2",
                    score,
                    target["id"],
                )
                await conn.execute(
                    """INSERT INTO bank_credit_score_history
                         (guild_id,actor_discord_user_id,target_discord_user_id,old_score,new_score,reason)
                       VALUES ($1,$2,$3,$4,$5,$6)""",
                    guild_id,
                    str(interaction.user.id),
                    str(user.id),
                    old_score,
                    score,
                    reason,
                )
        await send_private(
            interaction,
            f"<@{user.id}> 신용점수를 {old_score}점에서 {score}점으로 변경했습니다. 사유: {reason}",
        )

    await safe_command(interaction, run)


@credit_group.command(
    name="adjust", description="규정에 따른 신용점수 증감 사유를 선택합니다"
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(
    adjustment=[
        app_commands.Choice(name=label, value=key)
        for key, (label, _) in CREDIT_ADJUSTMENTS.items()
    ]
)
async def credit_adjust(
    interaction: discord.Interaction,
    user: discord.User,
    adjustment: app_commands.Choice[str],
    detail: str,
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        label, delta = CREDIT_ADJUSTMENTS[adjustment.value]
        reason = f"{label} · {detail}"
        async with pool.acquire() as conn:
            async with conn.transaction():
                target = await account(
                    conn, guild_id, str(user.id), lock=True, allow_frozen=True
                )
                old_score = target["credit_score"]
                score = max(0, min(100, old_score + delta))
                actual = score - old_score
                await conn.execute(
                    "UPDATE bank_accounts SET credit_score=$1 WHERE id=$2",
                    score,
                    target["id"],
                )
                await conn.execute(
                    """INSERT INTO bank_credit_score_history
                         (guild_id,actor_discord_user_id,target_discord_user_id,old_score,new_score,reason)
                       VALUES ($1,$2,$3,$4,$5,$6)""",
                    guild_id,
                    str(interaction.user.id),
                    str(user.id),
                    old_score,
                    score,
                    reason,
                )
        await send_private(
            interaction,
            f"<@{user.id}> 신용점수 {old_score}점 → {score}점 ({signed(actual)}점 반영). 사유: {reason}",
        )

    await safe_command(interaction, run)


bot.tree.add_command(credit_group)


currency_group = app_commands.Group(name="currency", description="재화·환율·이자 관리")


@currency_group.command(
    name="list", description="활성 재화·환율·일일 이자율을 확인합니다"
)
async def currency_list(interaction: discord.Interaction) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            await base_currency(conn, guild_id)
            rows = await conn.fetch(
                """SELECT name,symbol,exchange_value,deposit_rate,loan_rate,is_base
                     FROM bank_currencies WHERE guild_id=$1 AND active=true
                    ORDER BY is_base DESC,name""",
                guild_id,
            )
        text = (
            "\n".join(
                f"**{row['name']}** ({row['symbol']}) · 환전가치 {row['exchange_value']}"
                f"{' · 기본재화' if row['is_base'] else ''} · 일 예금 {row['deposit_rate']}% · 일 대출 {row['loan_rate']}%"
                for row in rows
            )
            or "활성 재화가 없습니다."
        )
        await send_private(interaction, text)

    await safe_command(interaction, run)


@currency_group.command(
    name="create", description="관리자: 재화를 생성하거나 설정을 갱신합니다"
)
@app_commands.checks.has_permissions(administrator=True)
async def currency_create(
    interaction: discord.Interaction,
    name: str,
    symbol: str,
    value: app_commands.Range[float, 0.000001, 1000000.0] = 1,
    deposit_rate: app_commands.Range[float, 0.0, 100.0] = 0,
    loan_rate: app_commands.Range[float, 0.0, 100.0] = 0,
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """INSERT INTO bank_currencies
                     (guild_id,name,symbol,exchange_value,deposit_rate,loan_rate,active)
                   VALUES ($1,$2,$3,$4,$5,$6,true)
                   ON CONFLICT (guild_id,name) DO UPDATE SET symbol=EXCLUDED.symbol,
                     exchange_value=EXCLUDED.exchange_value,deposit_rate=EXCLUDED.deposit_rate,
                     loan_rate=EXCLUDED.loan_rate,active=true
                   RETURNING name,symbol,exchange_value,deposit_rate,loan_rate""",
                guild_id,
                name.strip().lower(),
                symbol.strip(),
                value,
                deposit_rate,
                loan_rate,
            )
        await send_private(
            interaction,
            f"재화 {row['name']} ({row['symbol']}) 설정을 저장했습니다. 환전가치 {row['exchange_value']} · 예금 이자 {row['deposit_rate']}% · 대출 이자 {row['loan_rate']}%.",
        )

    await safe_command(interaction, run)


@currency_group.command(name="setbase", description="관리자: 기본재화를 지정합니다")
@app_commands.checks.has_permissions(administrator=True)
async def currency_setbase(interaction: discord.Interaction, currency: str) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            async with conn.transaction():
                selected = await get_currency(conn, guild_id, currency, lock=True)
                await conn.execute(
                    "UPDATE bank_currencies SET is_base=false WHERE guild_id=$1",
                    guild_id,
                )
                await conn.execute(
                    "UPDATE bank_currencies SET is_base=true WHERE id=$1",
                    selected["id"],
                )
        await send_private(
            interaction, f"{selected['name']}을 기본재화로 지정했습니다."
        )

    await safe_command(interaction, run)


@currency_group.command(
    name="setvalue", description="관리자: 기본재화 기준 환전가치를 변경합니다"
)
@app_commands.checks.has_permissions(administrator=True)
async def currency_setvalue(
    interaction: discord.Interaction,
    currency: str,
    value: app_commands.Range[float, 0.000001, 1000000.0],
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            selected = await get_currency(conn, guild_id, currency)
            await conn.execute(
                "UPDATE bank_currencies SET exchange_value=$1 WHERE id=$2",
                value,
                selected["id"],
            )
        await send_private(
            interaction, f"{selected['name']} 환전가치를 {value}로 변경했습니다."
        )

    await safe_command(interaction, run)


@currency_group.command(
    name="setrate", description="관리자: 일일 예금·대출 이자율을 변경합니다"
)
@app_commands.checks.has_permissions(administrator=True)
async def currency_setrate(
    interaction: discord.Interaction,
    currency: str,
    deposit_rate: app_commands.Range[float, 0.0, 100.0],
    loan_rate: app_commands.Range[float, 0.0, 100.0],
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            selected = await get_currency(conn, guild_id, currency)
            await conn.execute(
                "UPDATE bank_currencies SET deposit_rate=$1,loan_rate=$2 WHERE id=$3",
                deposit_rate,
                loan_rate,
                selected["id"],
            )
        await send_private(
            interaction,
            f"{selected['name']} 일일 예금 이자 {deposit_rate}% · 대출 이자 {loan_rate}%로 변경했습니다.",
        )

    await safe_command(interaction, run)


@currency_group.command(name="remove", description="관리자: 재화를 비활성화합니다")
@app_commands.checks.has_permissions(administrator=True)
async def currency_remove(
    interaction: discord.Interaction, currency: str, reason: str
) -> None:
    guild_id = require_guild(interaction)

    async def action():
        async with pool.acquire() as conn:
            async with conn.transaction():
                selected = await get_currency(conn, guild_id, currency, lock=True)
                if selected["is_base"]:
                    raise ValueError("기본재화는 삭제할 수 없습니다.")
                in_use = await conn.fetchval(
                    """SELECT 1 FROM bank_balances WHERE currency_id=$1 AND (wallet<>0 OR deposit<>0)
                       UNION ALL SELECT 1 FROM bank_loans WHERE currency_id=$1 AND status IN ('pending','approved') LIMIT 1""",
                    selected["id"],
                )
                if in_use:
                    raise ValueError(
                        "잔액 또는 대출이 남아 있어 비활성화할 수 없습니다."
                    )
                await conn.execute(
                    "UPDATE bank_currencies SET active=false WHERE id=$1",
                    selected["id"],
                )
        return f"{selected['name']} 재화를 비활성화했습니다. 사유: {reason}"

    await send_public(
        interaction,
        f"{currency} 재화를 비활성화합니다. 사유: {reason}",
        view=ConfirmActionView(interaction.user.id, action),
    )


bot.tree.add_command(currency_group)


class ConfirmActionView(discord.ui.View):
    def __init__(self, actor_id: int, action):
        super().__init__(timeout=120)
        self.actor_id = actor_id
        self.action = action

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.actor_id:
            await send_public(
                interaction, "이 확인 버튼은 요청한 관리자만 사용할 수 있습니다."
            )
            return False
        return True

    @discord.ui.button(label="확인 / Confirm", style=discord.ButtonStyle.success)
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        try:
            result = await self.action()
            language = await get_user_language(interaction.user.id)
            await interaction.response.edit_message(
                content=translate_message(result, language), view=None
            )
        except Exception:
            logger.exception("Confirmed action failed")
            language = await get_user_language(interaction.user.id)
            await interaction.response.edit_message(
                content=translate_message(
                    "작업을 완료하지 못했습니다. 관리자에게 문의하세요.",
                    language,
                ),
                view=None,
            )

    @discord.ui.button(label="취소 / Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.edit_message(
            content="작업을 취소했습니다.", view=None
        )


async def change_money(
    guild_id: str,
    actor_user_id: str,
    target_user_id: str,
    currency_name: str,
    amount: int,
    operation: str,
    reason: str,
) -> asyncpg.Record:
    async with pool.acquire() as conn:
        async with conn.transaction():
            actor = await get_or_create_account(conn, guild_id, actor_user_id)
            target = await account(
                conn, guild_id, target_user_id, lock=True, allow_frozen=True
            )
            currency_row = await get_currency(conn, guild_id, currency_name, lock=True)
            await ensure_balance(conn, target["id"], currency_row["id"])
            balance_row = await conn.fetchrow(
                "SELECT wallet FROM bank_balances WHERE account_id=$1 AND currency_id=$2 FOR UPDATE",
                target["id"],
                currency_row["id"],
            )
            if operation == "confiscate" and int(balance_row["wallet"]) < amount:
                raise ValueError("대상 사용자의 지갑 잔액이 부족합니다.")
            if operation == "mint":
                await conn.execute(
                    "UPDATE bank_balances SET wallet=wallet+$1 WHERE account_id=$2 AND currency_id=$3",
                    amount,
                    target["id"],
                    currency_row["id"],
                )
            else:
                await conn.execute(
                    "UPDATE bank_balances SET wallet=wallet-$1 WHERE account_id=$2 AND currency_id=$3",
                    amount,
                    target["id"],
                    currency_row["id"],
                )
            await record_transaction(
                conn,
                guild_id,
                operation,
                currency_row["id"],
                amount,
                actor_id=actor["id"],
                target_id=target["id"],
                description=reason,
            )
    return currency_row


async def request_money_change(
    interaction: discord.Interaction,
    operation: str,
    user: discord.User,
    currency: str,
    amount: int,
    reason: str,
) -> None:
    guild_id = require_guild(interaction)

    async def action():
        currency_row = await change_money(
            guild_id,
            str(interaction.user.id),
            str(user.id),
            currency,
            amount,
            operation,
            reason,
        )
        return f"{'지급' if operation == 'mint' else '회수'} 완료: <@{user.id}> · {fmt(amount)} {currency_row['symbol']} · 사유: {reason}"

    await send_public(
        interaction,
        f"<@{user.id}>에게 {fmt(amount)} {currency}를 "
        f"{'지급' if operation == 'mint' else '회수'}합니다. 사유: {reason}",
        view=ConfirmActionView(interaction.user.id, action),
    )


@bot.tree.command(
    name="mint", description="관리자: 게임 내 인증을 마친 재화를 지급합니다"
)
@app_commands.checks.has_permissions(administrator=True)
async def mint(
    interaction: discord.Interaction,
    user: discord.User,
    currency: str,
    amount: app_commands.Range[int, 1, 2147483647],
    reason: str,
) -> None:
    await request_money_change(interaction, "mint", user, currency, amount, reason)


@bot.tree.command(name="confiscate", description="관리자: 재화를 회수합니다")
@app_commands.checks.has_permissions(administrator=True)
async def confiscate(
    interaction: discord.Interaction,
    user: discord.User,
    currency: str,
    amount: app_commands.Range[int, 1, 2147483647],
    reason: str,
) -> None:
    await request_money_change(
        interaction, "confiscate", user, currency, amount, reason
    )


async def cancel_user_orders(
    conn: asyncpg.Connection,
    guild_id: str,
    account_id: int,
    stock_id: int | None = None,
) -> int:
    base = await base_currency(conn, guild_id)
    orders = await conn.fetch(
        """SELECT id,side,remaining,limit_price FROM bank_stock_orders
            WHERE guild_id=$1 AND account_id=$2 AND status IN ('open','partial')
              AND ($3::int IS NULL OR stock_id=$3) FOR UPDATE""",
        guild_id,
        account_id,
        stock_id,
    )
    for order in orders:
        if order["side"] == "buy":
            refund = order["remaining"] * order["limit_price"]
            await conn.execute(
                """INSERT INTO bank_balances (account_id,currency_id,wallet) VALUES ($1,$2,$3)
                   ON CONFLICT (account_id,currency_id)
                   DO UPDATE SET wallet=bank_balances.wallet+EXCLUDED.wallet""",
                account_id,
                base["id"],
                refund,
            )
        await conn.execute(
            "UPDATE bank_stock_orders SET status='cancelled',remaining=0 WHERE id=$1",
            order["id"],
        )
    return len(orders)


@bot.tree.command(name="freeze", description="관리자: 계좌를 동결합니다")
@app_commands.checks.has_permissions(administrator=True)
async def freeze(
    interaction: discord.Interaction, user: discord.User, reason: str
) -> None:
    await set_frozen(interaction, user, True, reason)


@bot.tree.command(name="unfreeze", description="관리자: 계좌 동결을 해제합니다")
@app_commands.checks.has_permissions(administrator=True)
async def unfreeze(
    interaction: discord.Interaction, user: discord.User, reason: str
) -> None:
    await set_frozen(interaction, user, False, reason)


async def set_frozen(
    interaction: discord.Interaction, user: discord.User, frozen: bool, reason: str
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            async with conn.transaction():
                actor = await get_or_create_account(
                    conn, guild_id, str(interaction.user.id)
                )
                target = await account(
                    conn, guild_id, str(user.id), lock=True, allow_frozen=True
                )
                if actor["id"] == target["id"]:
                    raise ValueError("본인 계좌 상태는 변경할 수 없습니다.")
                await conn.execute(
                    "UPDATE bank_accounts SET frozen=$1 WHERE id=$2",
                    frozen,
                    target["id"],
                )
                cancelled = (
                    await cancel_user_orders(conn, guild_id, target["id"])
                    if frozen
                    else 0
                )
                base = await base_currency(conn, guild_id)
                await record_transaction(
                    conn,
                    guild_id,
                    "account_frozen" if frozen else "account_unfrozen",
                    base["id"],
                    0,
                    actor_id=actor["id"],
                    target_id=target["id"],
                    description=reason,
                )
        await send_private(
            interaction,
            f"<@{user.id}> 계좌를 {'동결했습니다. 미체결 주식 주문 ' + str(cancelled) + '건을 취소했습니다.' if frozen else '해제했습니다.'}",
        )

    await safe_command(interaction, run)


@bot.tree.command(
    name="supply", description="관리자: 전체 계좌의 지갑·예금 통화량을 확인합니다"
)
@app_commands.checks.has_permissions(administrator=True)
async def supply(interaction: discord.Interaction, currency: str) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            currency_row = await get_currency(conn, guild_id, currency)
            total = await conn.fetchval(
                "SELECT COALESCE(SUM(wallet+deposit),0) FROM bank_balances WHERE currency_id=$1",
                currency_row["id"],
            )
        await send_private(
            interaction,
            f"{currency_row['name']} 통화량: {fmt(total)} {currency_row['symbol']} (전체 계좌의 지갑 + 예금 합계).",
        )

    await safe_command(interaction, run)


tier_config_group = app_commands.Group(
    name="tier-config", description="관리자: 등급 혜택을 설정합니다"
)
TIER_SETTING_COLUMNS = {
    "platinum_loan_bonus": "platinum_loan_bonus",
    "vip_deposit_rate_bonus": "vip_deposit_rate_bonus",
    "bronze_storage_limit": "bronze_storage_limit",
    "silver_storage_limit": "silver_storage_limit",
    "gold_storage_limit": "gold_storage_limit",
    "platinum_storage_limit": "platinum_storage_limit",
    "ace_storage_limit": "ace_storage_limit",
    "vip_storage_limit": "vip_storage_limit",
    "loan_term_days": "loan_term_days",
    "loan_extension_days": "loan_extension_days",
    "loan_extension_limit": "loan_extension_limit",
}


async def set_tier_setting(
    guild_id: str, actor_id: str, key: str, value: int | float, reason: str
) -> None:
    column = TIER_SETTING_COLUMNS[key]
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "INSERT INTO bank_tier_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING",
                guild_id,
            )
            old_value = await conn.fetchval(
                f"SELECT {column} FROM bank_tier_settings WHERE guild_id=$1", guild_id
            )
            await conn.execute(
                f"UPDATE bank_tier_settings SET {column}=$1,created_at=now() WHERE guild_id=$2",
                value,
                guild_id,
            )
            await conn.execute(
                """INSERT INTO bank_tier_setting_history
                     (guild_id,actor_discord_user_id,setting_key,old_value,new_value,reason)
                   VALUES ($1,$2,$3,$4,$5,$6)""",
                guild_id,
                actor_id,
                key,
                str(old_value),
                str(value),
                reason,
            )


@tier_config_group.command(
    name="limit", description="플래티넘 이상 신용대출 추가 한도(벨)를 설정합니다"
)
@app_commands.checks.has_permissions(administrator=True)
async def tier_limit(
    interaction: discord.Interaction, bonus: app_commands.Range[int, 0, 2147483647]
) -> None:
    async def run():
        await set_tier_setting(
            require_guild(interaction),
            str(interaction.user.id),
            "platinum_loan_bonus",
            bonus,
            "관리자 등급 혜택 설정",
        )
        await send_private(
            interaction,
            f"플래티넘 이상 신용대출 추가 한도를 {fmt(bonus)}벨로 설정했습니다.",
        )

    await safe_command(interaction, run)


@tier_config_group.command(
    name="interest", description="VIP 예금 추가 일일 이자율을 설정합니다"
)
@app_commands.checks.has_permissions(administrator=True)
async def tier_interest(
    interaction: discord.Interaction, rate: app_commands.Range[float, 0.0, 100.0]
) -> None:
    async def run():
        await set_tier_setting(
            require_guild(interaction),
            str(interaction.user.id),
            "vip_deposit_rate_bonus",
            rate,
            "관리자 등급 혜택 설정",
        )
        await send_private(
            interaction, f"VIP 예금 추가 일일 이자율을 {rate}%p로 설정했습니다."
        )

    await safe_command(interaction, run)


@tier_config_group.command(
    name="storage", description="등급별 은행 아이템 보관 한도를 설정합니다"
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(
    tier=[app_commands.Choice(name=label, value=key) for key, label, _, _ in TIERS]
)
async def tier_storage(
    interaction: discord.Interaction,
    tier: app_commands.Choice[str],
    capacity: app_commands.Range[int, 0, 2147483647],
) -> None:
    async def run():
        await set_tier_setting(
            require_guild(interaction),
            str(interaction.user.id),
            f"{tier.value}_storage_limit",
            capacity,
            "관리자 등급 혜택 설정",
        )
        await send_private(
            interaction,
            f"{TIER_NAME[tier.value]} 보관 한도를 {fmt(capacity)}개로 설정했습니다.",
        )

    await safe_command(interaction, run)


@tier_config_group.command(
    name="loan-term", description="신규 대출 기본 기간을 설정합니다(일, 0=기간 없음)"
)
@app_commands.checks.has_permissions(administrator=True)
async def tier_loan_term(
    interaction: discord.Interaction, days: app_commands.Range[int, 0, 3650]
) -> None:
    async def run():
        await set_tier_setting(
            require_guild(interaction),
            str(interaction.user.id),
            "loan_term_days",
            days,
            "관리자 등급 혜택 설정",
        )
        await send_private(
            interaction, f"신규 대출 기본 기간을 {days}일로 설정했습니다."
        )

    await safe_command(interaction, run)


@tier_config_group.command(
    name="extension", description="대출 연장 일수와 횟수를 설정합니다"
)
@app_commands.checks.has_permissions(administrator=True)
async def tier_extension(
    interaction: discord.Interaction,
    days: app_commands.Range[int, 0, 3650],
    limit: app_commands.Range[int, 0, 10],
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        await set_tier_setting(
            guild_id,
            str(interaction.user.id),
            "loan_extension_days",
            days,
            "관리자 대출 연장 설정",
        )
        await set_tier_setting(
            guild_id,
            str(interaction.user.id),
            "loan_extension_limit",
            limit,
            "관리자 대출 연장 설정",
        )
        await send_private(
            interaction, f"대출 1회 연장 기간 {days}일 · 최대 {limit}회로 설정했습니다."
        )

    await safe_command(interaction, run)


bot.tree.add_command(tier_config_group)


vault_group = app_commands.Group(name="vault", description="은행 보관 아이템")


@vault_group.command(name="list", description="내 은행 보관 아이템을 확인합니다")
async def vault_list(interaction: discord.Interaction) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            acct = await account(
                conn, guild_id, str(interaction.user.id), allow_frozen=True
            )
            rows = await conn.fetch(
                "SELECT item_name,quantity FROM bank_vault_items WHERE account_id=$1 AND quantity>0 ORDER BY lower(item_name)",
                acct["id"],
            )
            await conn.execute(
                "INSERT INTO bank_tier_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING",
                guild_id,
            )
            capacity = await conn.fetchval(
                f"SELECT {acct['tier_key']}_storage_limit FROM bank_tier_settings WHERE guild_id=$1",
                guild_id,
            )
        total = sum(row["quantity"] for row in rows)
        text = (
            "\n".join(f"{row['item_name']}: {fmt(row['quantity'])}개" for row in rows)
            or "보관 중인 아이템이 없습니다."
        )
        await send_private(
            interaction,
            f"**{TIER_NAME.get(acct['tier_key'], '브론즈')} 은행 보관함** · {fmt(total)}/{fmt(capacity)}개\n{text}",
        )

    await safe_command(interaction, run)


async def adjust_vault(
    interaction: discord.Interaction,
    user: discord.User,
    item: str,
    quantity: int,
    operation: str,
    reason: str,
) -> str:
    guild_id = require_guild(interaction)
    item_name = unicodedata.normalize("NFKC", item.strip())
    if not item_name:
        raise ValueError("아이템 이름을 입력하세요.")
    item_key = item_name.casefold()
    async with pool.acquire() as conn:
        async with conn.transaction():
            acct = await account(
                conn, guild_id, str(user.id), lock=True, allow_frozen=True
            )
            await conn.execute(
                "INSERT INTO bank_tier_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING",
                guild_id,
            )
            capacity = await conn.fetchval(
                f"SELECT {acct['tier_key']}_storage_limit FROM bank_tier_settings WHERE guild_id=$1",
                guild_id,
            )
            current = await conn.fetchval(
                "SELECT COALESCE(SUM(quantity),0) FROM bank_vault_items WHERE account_id=$1",
                acct["id"],
            )
            if operation == "add":
                if capacity <= 0:
                    raise ValueError("이 등급의 보관 한도가 설정되지 않았습니다.")
                if int(current) + quantity > capacity:
                    raise ValueError(
                        f"보관 한도를 초과합니다. 현재 {fmt(current)}개 / 한도 {fmt(capacity)}개."
                    )
                await conn.execute(
                    """INSERT INTO bank_vault_items (account_id,item_key,item_name,quantity)
                       VALUES ($1,$2,$3,$4)
                       ON CONFLICT (account_id,item_key) DO UPDATE SET item_name=EXCLUDED.item_name,
                         quantity=bank_vault_items.quantity+EXCLUDED.quantity,created_at=now()""",
                    acct["id"],
                    item_key,
                    item_name,
                    quantity,
                )
            else:
                stored = await conn.fetchrow(
                    "SELECT id,quantity FROM bank_vault_items WHERE account_id=$1 AND item_key=$2 FOR UPDATE",
                    acct["id"],
                    item_key,
                )
                if not stored or stored["quantity"] < quantity:
                    raise ValueError("은행 보관 수량이 부족합니다.")
                if stored["quantity"] == quantity:
                    await conn.execute(
                        "DELETE FROM bank_vault_items WHERE id=$1", stored["id"]
                    )
                else:
                    await conn.execute(
                        "UPDATE bank_vault_items SET quantity=quantity-$1,created_at=now() WHERE id=$2",
                        quantity,
                        stored["id"],
                    )
            await conn.execute(
                """INSERT INTO bank_vault_history
                     (guild_id,actor_discord_user_id,target_discord_user_id,item_name,quantity,operation,reason)
                   VALUES ($1,$2,$3,$4,$5,$6,$7)""",
                guild_id,
                str(interaction.user.id),
                str(user.id),
                item_name,
                quantity,
                operation,
                reason,
            )
    return f"<@{user.id}> 은행 보관 아이템 {'입고' if operation == 'add' else '반환'} 기록 완료: {item_name} {fmt(quantity)}개 · 사유: {reason}"


@vault_group.command(
    name="add", description="관리자: 게임에서 확인한 아이템을 은행에 보관합니다"
)
@app_commands.checks.has_permissions(administrator=True)
async def vault_add(
    interaction: discord.Interaction,
    user: discord.User,
    item: str,
    quantity: app_commands.Range[int, 1, 2147483647],
    reason: str,
) -> None:
    async def action():
        return await adjust_vault(interaction, user, item, quantity, "add", reason)

    await send_public(
        interaction,
        f"게임 내 확인된 {item} {fmt(quantity)}개를 <@{user.id}>의 은행 보관 기록에 추가합니다. 사유: {reason}",
        view=ConfirmActionView(interaction.user.id, action),
    )


@vault_group.command(
    name="remove", description="관리자: 게임에서 반환한 아이템을 기록에서 제거합니다"
)
@app_commands.checks.has_permissions(administrator=True)
async def vault_remove(
    interaction: discord.Interaction,
    user: discord.User,
    item: str,
    quantity: app_commands.Range[int, 1, 2147483647],
    reason: str,
) -> None:
    async def action():
        return await adjust_vault(interaction, user, item, quantity, "remove", reason)

    await send_public(
        interaction,
        f"게임 내 반환을 확인한 {item} {fmt(quantity)}개를 <@{user.id}>의 은행 보관 기록에서 제거합니다. 사유: {reason}",
        view=ConfirmActionView(interaction.user.id, action),
    )


bot.tree.add_command(vault_group)


request_group = app_commands.Group(name="bank-request", description="은행 아이템 의뢰")


@request_group.command(
    name="submit", description="아이템·재료를 은행에 찾아달라고 요청합니다"
)
async def request_submit(
    interaction: discord.Interaction,
    item: str,
    quantity: app_commands.Range[int, 1, 2147483647],
    note: str = "",
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        tier_key = tier_for(interaction.user)
        if not tier_at_least(tier_key, "platinum"):
            raise ValueError("은행 의뢰는 플레티넘 등급 이상부터 이용할 수 있습니다.")
        item_name = unicodedata.normalize("NFKC", item.strip())
        if not item_name:
            raise ValueError("아이템·재료 이름을 입력하세요.")
        async with pool.acquire() as conn:
            async with conn.transaction():
                acct = await account(
                    conn, guild_id, str(interaction.user.id), lock=True
                )
                await conn.execute(
                    "UPDATE bank_accounts SET tier_key=$1 WHERE id=$2",
                    tier_key,
                    acct["id"],
                )
                active = await conn.fetchval(
                    "SELECT COUNT(*) FROM bank_item_requests WHERE guild_id=$1 AND discord_user_id=$2 AND status IN ('pending','accepted')",
                    guild_id,
                    str(interaction.user.id),
                )
                if active >= 5:
                    raise ValueError(
                        "진행 중인 은행 의뢰는 사용자당 최대 5건까지 가능합니다."
                    )
                row = await conn.fetchrow(
                    """INSERT INTO bank_item_requests (guild_id,discord_user_id,item_name,quantity,note)
                       VALUES ($1,$2,$3,$4,$5) RETURNING id""",
                    guild_id,
                    str(interaction.user.id),
                    item_name,
                    quantity,
                    note.strip(),
                )
        await send_private(
            interaction,
            f"은행 의뢰 #{row['id']}을 접수했습니다: {item_name} {fmt(quantity)}개. 은행에서 확인 후 답변합니다.",
        )

    await safe_command(interaction, run)


@request_group.command(name="list", description="내 은행 의뢰 현황을 확인합니다")
async def request_list(interaction: discord.Interaction) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id,item_name,quantity,note,status,review_note,created_at
                     FROM bank_item_requests WHERE guild_id=$1 AND discord_user_id=$2
                    ORDER BY created_at DESC LIMIT 20""",
                guild_id,
                str(interaction.user.id),
            )
        text = (
            "\n".join(
                f"#{row['id']} · {row['item_name']} {fmt(row['quantity'])}개 · {row['status']}{' · ' + row['review_note'] if row['review_note'] else ''}"
                for row in rows
            )
            or "은행 의뢰 내역이 없습니다."
        )
        await send_private(interaction, text)

    await safe_command(interaction, run)


@request_group.command(
    name="queue", description="관리자: 진행 중인 은행 의뢰를 확인합니다"
)
@app_commands.checks.has_permissions(administrator=True)
async def request_queue(interaction: discord.Interaction) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT id,discord_user_id,item_name,quantity,note,status
                     FROM bank_item_requests WHERE guild_id=$1 AND status IN ('pending','accepted')
                    ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END,created_at LIMIT 50""",
                guild_id,
            )
        text = (
            "\n".join(
                f"#{row['id']} <@{row['discord_user_id']}> · {row['item_name']} {fmt(row['quantity'])}개 · {row['status']}{' · ' + row['note'] if row['note'] else ''}"
                for row in rows
            )
            or "진행 중인 은행 의뢰가 없습니다."
        )
        await send_private(interaction, text)

    await safe_command(interaction, run)


@request_group.command(
    name="update", description="관리자: 의뢰를 수락·거절·완료 처리합니다"
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(
    status=[
        app_commands.Choice(name="수락", value="accepted"),
        app_commands.Choice(name="거절", value="declined"),
        app_commands.Choice(name="구매·전달 완료", value="fulfilled"),
    ]
)
async def request_update(
    interaction: discord.Interaction,
    request_id: app_commands.Range[int, 1, 2147483647],
    status: app_commands.Choice[str],
    reason: str,
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            async with conn.transaction():
                req = await conn.fetchrow(
                    "SELECT id,discord_user_id,item_name,quantity,status FROM bank_item_requests WHERE id=$1 AND guild_id=$2 FOR UPDATE",
                    request_id,
                    guild_id,
                )
                if not req:
                    raise ValueError("은행 의뢰를 찾을 수 없습니다.")
                allowed = (
                    req["status"] == "pending"
                    and status.value in ("accepted", "declined")
                ) or (
                    req["status"] == "accepted"
                    and status.value in ("fulfilled", "declined")
                )
                if not allowed:
                    raise ValueError(
                        "현재 상태에서 해당 의뢰 상태로 변경할 수 없습니다."
                    )
                await conn.execute(
                    "UPDATE bank_item_requests SET status=$1,review_note=$2,reviewed_by=$3,reviewed_at=now() WHERE id=$4",
                    status.value,
                    reason,
                    str(interaction.user.id),
                    request_id,
                )
        await send_private(
            interaction,
            f"은행 의뢰 #{request_id} 상태를 {status.value}로 변경했습니다. 사유: {reason}",
        )

    await safe_command(interaction, run)


bot.tree.add_command(request_group)


async def send_announcement(guild_id: str, content: str) -> bool:
    async with pool.acquire() as conn:
        channel_id = await conn.fetchval(
            "SELECT announcement_channel_id FROM bank_guild_settings WHERE guild_id=$1",
            guild_id,
        )
    if not channel_id:
        return False
    channel = bot.get_channel(int(channel_id))
    if channel is None:
        try:
            channel = await bot.fetch_channel(int(channel_id))
        except discord.HTTPException:
            logger.warning("Announcement channel is unavailable: %s", channel_id)
            return False
    if isinstance(channel, discord.abc.Messageable):
        await channel.send(
            content[:1900], allowed_mentions=discord.AllowedMentions.none()
        )
        return True
    return False


market_group = app_commands.Group(
    name="market", description="관리자: 가상주식 시장·평가·상장 관리"
)


@market_group.command(name="news", description="최근 시장 공지를 확인합니다")
async def market_news(interaction: discord.Interaction) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """SELECT n.title,n.content,s.name stock_name FROM bank_market_news n
                     LEFT JOIN bank_stocks s ON s.id=n.stock_id
                    WHERE n.guild_id=$1 ORDER BY n.created_at DESC LIMIT 8""",
                guild_id,
            )
        text = (
            "\n\n".join(
                f"**{row['stock_name'] + ' · ' if row['stock_name'] else ''}{row['title']}**\n{row['content']}"
                for row in rows
            )
            or "등록된 시장 공지가 없습니다."
        )
        await send_private(interaction, text)

    await safe_command(interaction, run)


@market_group.command(name="rumor", description="관리자: 가상 시장 찌라시를 공지합니다")
@app_commands.checks.has_permissions(administrator=True)
@app_commands.choices(
    kind=[
        app_commands.Choice(name="가짜 정보", value="fake_information"),
        app_commands.Choice(name="투자 정보", value="investment_tip"),
    ]
)
async def market_rumor(
    interaction: discord.Interaction,
    kind: app_commands.Choice[str],
    title: str,
    content: str,
    stock_name: str | None = None,
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        clean_title = title.strip()
        clean_content = content.strip()
        if not clean_title or len(clean_title) > 100:
            raise ValueError("찌라시 제목은 1~100자로 입력하세요.")
        if not clean_content or len(clean_content) > 1200:
            raise ValueError("찌라시 내용은 1~1,200자로 입력하세요.")
        stock_id = None
        resolved_stock_name = None
        if stock_name and stock_name.strip():
            async with pool.acquire() as conn:
                stock = await conn.fetchrow(
                    """SELECT id,name FROM bank_stocks
                       WHERE guild_id=$1 AND lower(name)=lower($2) AND listed=true""",
                    guild_id,
                    stock_name.strip(),
                )
            if not stock:
                raise ValueError("해당 이름의 활성 주식을 찾을 수 없습니다.")
            stock_id, resolved_stock_name = stock["id"], stock["name"]
        category = "가짜 정보" if kind.value == "fake_information" else "투자 정보"
        disclaimer = (
            "운영진 작성 찌라시이며, 사실 여부와 투자 결과는 보장되지 않습니다."
        )
        posted = (
            f"📣 **[찌라시 · {category} · 미확인] {clean_title}**\n"
            f"{'**관련 종목:** ' + resolved_stock_name + chr(10) if resolved_stock_name else ''}"
            f"{clean_content}\n\n*{disclaimer}*"
        )
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO bank_market_news (guild_id,stock_id,title,content,created_by)
                   VALUES ($1,$2,$3,$4,$5)""",
                guild_id,
                stock_id,
                f"[찌라시 · {category}] {clean_title}",
                posted,
                str(interaction.user.id),
            )
        announced = await send_announcement(guild_id, posted)
        status = (
            "저장하고 공지 채널에 게시했습니다."
            if announced
            else "저장했습니다. 게시할 채널이 설정되지 않아 공지 채널에는 올라가지 않았습니다."
        )
        await send_private(interaction, status)

    await safe_command(interaction, run)


@market_group.command(name="create", description="길드 주식을 상장합니다")
@app_commands.checks.has_permissions(administrator=True)
async def market_create(
    interaction: discord.Interaction,
    name: str,
    description: str,
    price: app_commands.Range[int, 1, 2147483647],
    initial_shares: app_commands.Range[int, 1, 2147483647],
    holder: discord.User,
    reason: str,
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        normalized_name = " ".join(unicodedata.normalize("NFC", name).split())
        normalized_description = description.strip()
        if not normalized_name or len(normalized_name) > 60:
            raise ValueError("종목 이름은 1~60자여야 합니다.")
        if not normalized_description or len(normalized_description) > 500:
            raise ValueError("종목 소개는 1~500자로 입력하세요.")
        async with pool.acquire() as conn:
            async with conn.transaction():
                holder_account = await account(
                    conn, guild_id, str(holder.id), lock=True
                )
                exists = await conn.fetchval(
                    "SELECT 1 FROM bank_stocks WHERE guild_id=$1 AND lower(trim(name))=lower(trim($2)) LIMIT 1",
                    guild_id,
                    normalized_name,
                )
                if exists:
                    raise ValueError("같은 이름의 종목이 이미 있습니다.")
                stock = await conn.fetchrow(
                    """INSERT INTO bank_stocks (guild_id,name,description,current_price,total_shares)
                       VALUES ($1,$2,$3,$4,$5) RETURNING id""",
                    guild_id,
                    normalized_name,
                    normalized_description,
                    price,
                    initial_shares,
                )
                await conn.execute(
                    "INSERT INTO bank_stock_holdings (stock_id,account_id,shares) VALUES ($1,$2,$3)",
                    stock["id"],
                    holder_account["id"],
                    initial_shares,
                )
                await conn.execute(
                    """INSERT INTO bank_market_news (guild_id,stock_id,title,content,created_by)
                       VALUES ($1,$2,'신규 상장',$3,$4)""",
                    guild_id,
                    stock["id"],
                    f"{normalized_description}\n상장 사유: {reason}",
                    str(interaction.user.id),
                )
        message = f"**{normalized_name} 신규 상장**\n{normalized_description}\n기준가 {fmt(price)} · 초기 발행 {fmt(initial_shares)}주"
        await send_private(interaction, message)
        await send_announcement(guild_id, message)

    await safe_command(interaction, run)


@market_group.command(name="describe", description="종목 소개를 등록하거나 수정합니다")
@app_commands.checks.has_permissions(administrator=True)
async def market_describe(
    interaction: discord.Interaction, stock: str, description: str, reason: str
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        normalized = description.strip()
        if not normalized or len(normalized) > 500:
            raise ValueError("종목 소개는 1~500자로 입력하세요.")
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await find_stock(conn, guild_id, stock, lock=True)
                await conn.execute(
                    "UPDATE bank_stocks SET description=$1 WHERE id=$2",
                    normalized,
                    row["id"],
                )
                await conn.execute(
                    """INSERT INTO bank_market_news (guild_id,stock_id,title,content,created_by)
                       VALUES ($1,$2,'종목 소개 수정',$3,$4)""",
                    guild_id,
                    row["id"],
                    f"{normalized}\n변경 사유: {reason}",
                    str(interaction.user.id),
                )
        message = f"**{row['name']} 종목 소개 수정**\n{normalized}"
        await send_private(interaction, message)
        await send_announcement(guild_id, message)

    await safe_command(interaction, run)


async def change_stock_supply(
    guild_id: str,
    actor_id: str,
    stock_name: str,
    holder_id: str,
    shares: int,
    operation: str,
    reason: str,
) -> asyncpg.Record:
    async with pool.acquire() as conn:
        async with conn.transaction():
            await get_or_create_account(conn, guild_id, actor_id)
            holder = await account(
                conn, guild_id, holder_id, lock=True, allow_frozen=True
            )
            stock = await find_stock(conn, guild_id, stock_name, lock=True)
            if operation == "issue":
                await conn.execute(
                    "UPDATE bank_stocks SET total_shares=total_shares+$1 WHERE id=$2",
                    shares,
                    stock["id"],
                )
                await conn.execute(
                    """INSERT INTO bank_stock_holdings (stock_id,account_id,shares) VALUES ($1,$2,$3)
                       ON CONFLICT (stock_id,account_id) DO UPDATE SET shares=bank_stock_holdings.shares+EXCLUDED.shares""",
                    stock["id"],
                    holder["id"],
                    shares,
                )
            else:
                pending = await conn.fetchval(
                    """SELECT COALESCE(SUM(remaining),0) FROM bank_stock_orders
                        WHERE stock_id=$1 AND account_id=$2 AND side='sell' AND status IN ('open','partial')""",
                    stock["id"],
                    holder["id"],
                )
                holding = await conn.fetchval(
                    "SELECT shares FROM bank_stock_holdings WHERE stock_id=$1 AND account_id=$2 FOR UPDATE",
                    stock["id"],
                    holder["id"],
                )
                if holding is None or int(holding) - int(pending) < shares:
                    raise ValueError(
                        "미체결 매도 주문을 제외한 보유 주식이 부족합니다."
                    )
                await conn.execute(
                    "UPDATE bank_stock_holdings SET shares=shares-$1 WHERE stock_id=$2 AND account_id=$3",
                    shares,
                    stock["id"],
                    holder["id"],
                )
                await conn.execute(
                    "UPDATE bank_stocks SET total_shares=total_shares-$1 WHERE id=$2",
                    shares,
                    stock["id"],
                )
            await conn.execute(
                """INSERT INTO bank_market_news (guild_id,stock_id,title,content,created_by)
                   VALUES ($1,$2,$3,$4,$5)""",
                guild_id,
                stock["id"],
                "주식 신규 발행" if operation == "issue" else "주식 소각",
                f"{holder_id} · {shares}주 · {reason}",
                actor_id,
            )
    return stock


@market_group.command(
    name="issue", description="주식을 신규 발행하여 보유자에게 지급합니다"
)
@app_commands.checks.has_permissions(administrator=True)
async def market_issue(
    interaction: discord.Interaction,
    stock: str,
    holder: discord.User,
    shares: app_commands.Range[int, 1, 2147483647],
    reason: str,
) -> None:
    async def action():
        row = await change_stock_supply(
            require_guild(interaction),
            str(interaction.user.id),
            stock,
            str(holder.id),
            shares,
            "issue",
            reason,
        )
        return f"{row['name']} {fmt(shares)}주를 <@{holder.id}>에게 발행했습니다. 사유: {reason}"

    await send_public(
        interaction,
        f"{stock} {fmt(shares)}주를 <@{holder.id}>에게 발행합니다. 사유: {reason}",
        view=ConfirmActionView(interaction.user.id, action),
    )


@market_group.command(name="burn", description="보유 주식을 소각합니다")
@app_commands.checks.has_permissions(administrator=True)
async def market_burn(
    interaction: discord.Interaction,
    stock: str,
    holder: discord.User,
    shares: app_commands.Range[int, 1, 2147483647],
    reason: str,
) -> None:
    async def action():
        row = await change_stock_supply(
            require_guild(interaction),
            str(interaction.user.id),
            stock,
            str(holder.id),
            shares,
            "burn",
            reason,
        )
        return f"{row['name']} <@{holder.id}> 보유분 {fmt(shares)}주를 소각했습니다. 사유: {reason}"

    await send_public(
        interaction,
        f"{stock} <@{holder.id}> 보유분 {fmt(shares)}주를 소각합니다. 사유: {reason}",
        view=ConfirmActionView(interaction.user.id, action),
    )


@market_group.command(
    name="remove", description="상장을 폐지하고 미체결 주문을 취소합니다"
)
@app_commands.checks.has_permissions(administrator=True)
async def market_remove(
    interaction: discord.Interaction, stock: str, reason: str
) -> None:
    guild_id = require_guild(interaction)

    async def action():
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await find_stock(conn, guild_id, stock, lock=True)
                accounts = await conn.fetch(
                    "SELECT DISTINCT account_id FROM bank_stock_orders WHERE stock_id=$1 AND status IN ('open','partial')",
                    row["id"],
                )
                for acct in accounts:
                    await cancel_user_orders(
                        conn, guild_id, acct["account_id"], row["id"]
                    )
                await conn.execute(
                    "UPDATE bank_stocks SET listed=false WHERE id=$1", row["id"]
                )
                await conn.execute(
                    "INSERT INTO bank_market_news (guild_id,stock_id,title,content,created_by) VALUES ($1,$2,'상장 폐지',$3,$4)",
                    guild_id,
                    row["id"],
                    reason,
                    str(interaction.user.id),
                )
        return f"{row['name']} 상장을 폐지하고 미체결 주문을 취소했습니다. 보유 주식과 기록은 보존됩니다."

    await send_public(
        interaction,
        f"{stock} 상장을 폐지하고 미체결 주문을 취소합니다. 사유: {reason}",
        view=ConfirmActionView(interaction.user.id, action),
    )


def evaluation_change_range(score: int) -> tuple[int, int]:
    if score == 0:
        return 0, 0
    bands = [
        (1, 5, 1, 2),
        (6, 10, 2, 4),
        (11, 15, 4, 6),
        (16, 20, 6, 8),
        (21, 25, 8, 10),
        (26, 30, 10, 12),
        (31, 35, 12, 14),
        (36, 40, 14, 16),
        (41, 45, 16, 18),
        (46, 50, 18, 20),
    ]
    band = next((entry for entry in bands if entry[0] <= abs(score) <= entry[1]), None)
    if not band:
        raise ValueError("평가 점수가 허용 범위를 벗어났습니다.")
    values = [band[2] * (1 if score > 0 else -1), band[3] * (1 if score > 0 else -1)]
    return min(values), max(values)


UNSCORED_MARKET_EVIDENCE = "관리자 평가 미등록 — 무작위 시세 변동"


def unscored_market_change() -> int:
    return random.randint(-10, 10)


def market_price_after_change(price: int, change: int) -> int:
    return max(1, math.floor(price * (1 + change / 100) + 0.5))


def is_unscored_market_evaluation(row: asyncpg.Record) -> bool:
    return (
        row["created_by"] == "system"
        and row["evidence"] == UNSCORED_MARKET_EVIDENCE
    )


def market_report_line(row: asyncpg.Record) -> str:
    score_label = (
        "점수 미등록 · 무작위 변동"
        if is_unscored_market_evaluation(row)
        else f"평가 {signed(row['final_score'])}점"
    )
    return (
        f"**{row['name']}** · {fmt(row['old_price'])} → {fmt(row['new_price'])} "
        f"({signed(row['change_percent'])}%) · {score_label}\n{row['evidence']}"
    )


async def ensure_unscored_market_evaluations(
    conn: asyncpg.Connection,
    guild_id: str,
    date: str,
    stock_name: str | None = None,
) -> None:
    stocks = await conn.fetch(
        """SELECT s.id,s.current_price
             FROM bank_stocks s
            WHERE s.guild_id=$1 AND s.listed=true
              AND NOT EXISTS (
                SELECT 1 FROM bank_stock_evaluations e
                 WHERE e.stock_id=s.id AND e.evaluation_date=$2
              )
              AND ($3::text IS NULL OR lower(trim(s.name))=lower(trim($3)))
            ORDER BY lower(s.name),s.name
            FOR UPDATE OF s""",
        guild_id,
        date,
        stock_name,
    )
    for stock in stocks:
        change = unscored_market_change()
        new_price = market_price_after_change(stock["current_price"], change)
        await conn.execute(
            """INSERT INTO bank_stock_evaluations
                 (guild_id,stock_id,evaluation_date,content_score,activity_score,
                  membership_score,events_score,growth_score,influence_score,
                  opinion_score,base_score,random_score,final_score,change_percent,
                  old_price,new_price,evidence,status,created_by)
               VALUES ($1,$2,$3,0,0,0,0,0,0,0,0,0,0,$4,$5,$6,$7,'pending','system')
               ON CONFLICT (stock_id,evaluation_date) DO NOTHING""",
            guild_id,
            stock["id"],
            date,
            change,
            stock["current_price"],
            new_price,
            UNSCORED_MARKET_EVIDENCE,
        )


def market_news_content(row: asyncpg.Record) -> str:
    price_line = (
        f"기준가 {fmt(row['old_price'])} → {fmt(row['new_price'])} "
        f"({signed(row['change_percent'])}%)"
    )
    if is_unscored_market_evaluation(row):
        return f"{price_line}\n점수 미등록 종목에 하루 -10%~+10% 무작위 변동을 적용했습니다."
    return (
        f"{price_line}\n"
        f"평가 {signed(row['final_score'])}점 (콘텐츠 {signed(row['content_score'])}, "
        f"활동 {signed(row['activity_score'])}, 인원 {signed(row['membership_score'])}, "
        f"사건 {signed(row['events_score'])}, 성장 {signed(row['growth_score'])}, "
        f"영향력 {signed(row['influence_score'])}, 여론 {signed(row['opinion_score'])})\n"
        f"근거: {row['evidence']}"
    )


@market_group.command(
    name="evaluate", description="종목의 세부 평가 점수와 근거를 등록합니다"
)
@app_commands.checks.has_permissions(administrator=True)
async def market_evaluate(
    interaction: discord.Interaction,
    stock: str,
    content: app_commands.Range[int, -6, 6],
    activity: app_commands.Range[int, -6, 6],
    membership: app_commands.Range[int, -5, 5],
    events: app_commands.Range[int, -8, 8],
    growth: app_commands.Range[int, -5, 5],
    influence: app_commands.Range[int, -5, 5],
    opinion: app_commands.Range[int, -5, 5],
    evidence: str,
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        now = datetime.now(ZoneInfo("Asia/Seoul"))
        if not 1230 <= now.hour * 60 + now.minute < 1260:
            raise ValueError(
                "평가는 한국 시간 20:30~21:00 사이에만 등록할 수 있습니다."
            )
        scores = [content, activity, membership, events, growth, influence, opinion]
        base_score = sum(scores)
        random_score = random.randint(-10, 10)
        final_score = base_score + random_score
        low, high = evaluation_change_range(final_score)
        change = random.randint(low, high) if low != high else low
        date = now.date().isoformat()
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await find_stock(conn, guild_id, stock, lock=True)
                officer = await conn.fetchval(
                    "SELECT 1 FROM bank_stock_officers WHERE stock_id=$1 AND discord_user_id=$2",
                    row["id"],
                    str(interaction.user.id),
                )
                if officer:
                    raise ValueError(
                        "해당 길드의 지정 관계자는 자기 종목 평가에 참여할 수 없습니다."
                    )
                new_price = (
                    row["current_price"]
                    if change == 0
                    else max(
                        1, math.floor(row["current_price"] * (1 + change / 100) + 0.5)
                    )
                )
                ev = await conn.fetchrow(
                    """INSERT INTO bank_stock_evaluations
                         (guild_id,stock_id,evaluation_date,content_score,activity_score,membership_score,
                          events_score,growth_score,influence_score,opinion_score,base_score,random_score,
                          final_score,change_percent,old_price,new_price,evidence,status,created_by)
                       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,'pending',$18)
                       ON CONFLICT (stock_id,evaluation_date) DO UPDATE SET content_score=EXCLUDED.content_score,
                         activity_score=EXCLUDED.activity_score,membership_score=EXCLUDED.membership_score,
                         events_score=EXCLUDED.events_score,growth_score=EXCLUDED.growth_score,
                         influence_score=EXCLUDED.influence_score,opinion_score=EXCLUDED.opinion_score,
                         base_score=EXCLUDED.base_score,random_score=EXCLUDED.random_score,
                         final_score=EXCLUDED.final_score,change_percent=EXCLUDED.change_percent,
                         old_price=EXCLUDED.old_price,new_price=EXCLUDED.new_price,evidence=EXCLUDED.evidence,
                         status='pending',created_by=EXCLUDED.created_by,created_at=now(),published_at=NULL
                       RETURNING id""",
                    guild_id,
                    row["id"],
                    date,
                    content,
                    activity,
                    membership,
                    events,
                    growth,
                    influence,
                    opinion,
                    base_score,
                    random_score,
                    final_score,
                    change,
                    row["current_price"],
                    new_price,
                    evidence,
                    str(interaction.user.id),
                )
        await send_private(
            interaction,
            f"**{row['name']} 평가 저장**\n기본 {base_score}점 + 무작위 {signed(random_score)}점 = 최종 {final_score}점 · 변동률 {signed(change)}% · 기준가 {fmt(row['current_price'])} → {fmt(new_price)}\n21:00 시세 공지 예정. 평가 #{ev['id']}.",
        )

    await safe_command(interaction, run)


@market_group.command(name="publish", description="오늘 평가와 새 주가를 공지합니다")
@app_commands.checks.has_permissions(administrator=True)
async def market_publish(
    interaction: discord.Interaction, stock: str | None = None
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        date = datetime.now(ZoneInfo("Asia/Seoul")).date().isoformat()
        async with pool.acquire() as conn:
            async with conn.transaction():
                await ensure_unscored_market_evaluations(
                    conn, guild_id, date, stock
                )
                rows = await conn.fetch(
                    """SELECT e.id,e.stock_id,s.name,e.old_price,e.new_price,e.content_score,e.activity_score,
                              e.membership_score,e.events_score,e.growth_score,e.influence_score,e.opinion_score,
                              e.base_score,e.random_score,e.final_score,e.change_percent,e.evidence,e.created_by
                         FROM bank_stock_evaluations e JOIN bank_stocks s ON s.id=e.stock_id
                        WHERE e.guild_id=$1 AND e.evaluation_date=$2 AND e.status='pending'
                          AND ($3::text IS NULL OR lower(trim(s.name))=lower(trim($3)))
                        ORDER BY lower(s.name),s.name FOR UPDATE OF e""",
                    guild_id,
                    date,
                    stock,
                )
                if not rows:
                    raise ValueError("오늘 공지할 미게시 평가가 없습니다.")
                for row in rows:
                    await conn.execute(
                        "UPDATE bank_stocks SET current_price=$1 WHERE id=$2",
                        row["new_price"],
                        row["stock_id"],
                    )
                    await conn.execute(
                        "UPDATE bank_stock_evaluations SET status='published',published_at=now() WHERE id=$1",
                        row["id"],
                    )
                    await conn.execute(
                        """INSERT INTO bank_market_news (guild_id,stock_id,title,content,created_by)
                           VALUES ($1,$2,$3,$4,'system')""",
                        guild_id,
                        row["stock_id"],
                        f"{row['name']} 일일 시세",
                        market_news_content(row),
                    )
                if stock is None:
                    await conn.execute(
                        "INSERT INTO bank_market_cycles (guild_id,cycle_date,stage) VALUES ($1,$2,'publish') ON CONFLICT DO NOTHING",
                        guild_id,
                        date,
                    )
        message = "오늘 가상주식 시세 발표\n" + "\n\n".join(
            market_report_line(row)
            for row in rows
        )
        await send_private(interaction, message)
        await send_announcement(guild_id, message)

    await safe_command(interaction, run)


async def announcement_channel_autocomplete(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    guild = interaction.guild
    if guild is None:
        return []

    search = current.strip().casefold().lstrip("#")
    channels = sorted(guild.text_channels, key=lambda channel: channel.name.casefold())
    matches = [
        channel
        for channel in channels
        if not search or search in channel.name.casefold() or search in str(channel.id)
    ]
    return [
        app_commands.Choice(
            name=(
                f"#{channel.name} · {channel.category.name}"
                if channel.category
                else f"#{channel.name}"
            )[:100],
            value=str(channel.id),
        )
        for channel in matches[:25]
    ]


def resolve_announcement_channel(
    guild: discord.Guild, value: str
) -> discord.TextChannel:
    channel_input = value.strip()
    if channel_input.startswith("<#") and channel_input.endswith(">"):
        channel_input = channel_input[2:-1]

    if channel_input.isdecimal():
        channel = guild.get_channel(int(channel_input))
    else:
        channel_name = channel_input.lstrip("#").casefold()
        channel = next(
            (
                candidate
                for candidate in guild.text_channels
                if candidate.name.casefold() == channel_name
            ),
            None,
        )

    if not isinstance(channel, discord.TextChannel):
        raise ValueError(
            "텍스트 채널을 찾지 못했습니다. 자동완성 목록에서 선택하거나 채널 이름을 확인해 주세요."
        )
    return channel


@market_group.command(
    name="channel", description="관리자 전용 · 시세·뉴스 공지 채널을 설정합니다"
)
@app_commands.checks.has_permissions(administrator=True)
@app_commands.autocomplete(channel=announcement_channel_autocomplete)
async def market_channel(interaction: discord.Interaction, channel: str) -> None:
    async def run():
        guild = interaction.guild
        if guild is None:
            raise ValueError("서버에서만 공지 채널을 설정할 수 있습니다.")
        guild_id = require_guild(interaction)
        target_channel = resolve_announcement_channel(guild, channel)
        async with pool.acquire() as conn:
            await conn.execute(
                """INSERT INTO bank_guild_settings (guild_id,announcement_channel_id)
                   VALUES ($1,$2) ON CONFLICT (guild_id) DO UPDATE SET announcement_channel_id=EXCLUDED.announcement_channel_id""",
                guild_id,
                str(target_channel.id),
            )
        await send_private(
            interaction,
            f"시세·뉴스 공지 채널을 {target_channel.mention}로 설정했습니다.",
        )

    await safe_command(interaction, run)


@market_group.command(name="note", description="확인된 시장 소식을 등록합니다")
@app_commands.checks.has_permissions(administrator=True)
async def market_note(
    interaction: discord.Interaction, title: str, content: str, stock: str | None = None
) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            stock_row = await find_stock(conn, guild_id, stock) if stock else None
            await conn.execute(
                """INSERT INTO bank_market_news (guild_id,stock_id,title,content,created_by)
                   VALUES ($1,$2,$3,$4,$5)""",
                guild_id,
                stock_row["id"] if stock_row else None,
                title,
                content,
                str(interaction.user.id),
            )
        message = f"**[시장 뉴스{(' · ' + stock_row['name']) if stock_row else ''}] {title}**\n{content}"
        await send_private(interaction, "시장을 공지했습니다.")
        await send_announcement(guild_id, message)

    await safe_command(interaction, run)


async def change_officer(
    guild_id: str, stock_name: str, user_id: str, add: bool
) -> str:
    async with pool.acquire() as conn:
        async with conn.transaction():
            stock = await find_stock(conn, guild_id, stock_name, lock=True)
            if add:
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM bank_stock_officers WHERE stock_id=$1",
                    stock["id"],
                )
                already = await conn.fetchval(
                    "SELECT 1 FROM bank_stock_officers WHERE stock_id=$1 AND discord_user_id=$2",
                    stock["id"],
                    user_id,
                )
                if not already and count >= 2:
                    raise ValueError("종목별 관계자는 최대 2명까지 지정할 수 있습니다.")
                await conn.execute(
                    "INSERT INTO bank_stock_officers (stock_id,discord_user_id) VALUES ($1,$2) ON CONFLICT DO NOTHING",
                    stock["id"],
                    user_id,
                )
            else:
                result = await conn.execute(
                    "DELETE FROM bank_stock_officers WHERE stock_id=$1 AND discord_user_id=$2",
                    stock["id"],
                    user_id,
                )
                if result.endswith("0"):
                    raise ValueError("해당 종목의 관계자 지정을 찾을 수 없습니다.")
    return stock["name"]


@market_group.command(
    name="officer-add", description="길드 관계자를 지정합니다 (종목별 최대 2명)"
)
@app_commands.checks.has_permissions(administrator=True)
async def market_officer_add(
    interaction: discord.Interaction, stock: str, officer: discord.User
) -> None:
    async def run():
        name = await change_officer(
            require_guild(interaction), stock, str(officer.id), True
        )
        await send_private(
            interaction,
            f"{name} 관계자를 지정했습니다. 해당 관계자는 소속 종목 평가에서 제외됩니다.",
        )

    await safe_command(interaction, run)


@market_group.command(
    name="officer-remove", description="길드 관계자 지정을 해제합니다"
)
@app_commands.checks.has_permissions(administrator=True)
async def market_officer_remove(
    interaction: discord.Interaction, stock: str, officer: discord.User
) -> None:
    async def run():
        name = await change_officer(
            require_guild(interaction), stock, str(officer.id), False
        )
        await send_private(interaction, f"{name} 관계자 지정을 해제했습니다.")

    await safe_command(interaction, run)


bot.tree.add_command(market_group)


@bot.tree.command(name="history", description="내 최근 은행·주식 거래내역을 확인합니다")
async def history(interaction: discord.Interaction) -> None:
    async def run():
        guild_id = require_guild(interaction)
        async with pool.acquire() as conn:
            acct = await account(
                conn, guild_id, str(interaction.user.id), allow_frozen=True
            )
            rows = await conn.fetch(
                """SELECT t.type,t.amount,t.fee,t.description,t.created_at,c.name currency
                     FROM bank_transactions t JOIN bank_currencies c ON c.id=t.currency_id
                    WHERE t.guild_id=$1 AND (t.actor_account_id=$2 OR t.target_account_id=$2)
                    ORDER BY t.created_at DESC,t.id DESC LIMIT 12""",
                guild_id,
                acct["id"],
            )
        lines = []
        for row in rows:
            when = int(row["created_at"].timestamp())
            description = row["description"] or row["type"]
            fee_text = f" (수수료 {fmt(row['fee'])})" if int(row["fee"]) else ""
            lines.append(
                f"<t:{when}:R> · {description} · {fmt(row['amount'])} {row['currency']}{fee_text}"
            )
        await send_private(interaction, "\n".join(lines) or "거래 내역이 없습니다.")

    await safe_command(interaction, run)


async def accrue_interest(guild_id: str, run_date: str) -> bool:
    async with pool.acquire() as conn:
        async with conn.transaction():
            inserted = await conn.fetchval(
                """INSERT INTO bank_interest_runs (guild_id,run_date) VALUES ($1,$2)
                   ON CONFLICT (guild_id,run_date) DO NOTHING RETURNING id""",
                guild_id,
                run_date,
            )
            if not inserted:
                return False
            await conn.execute(
                "INSERT INTO bank_tier_settings (guild_id) VALUES ($1) ON CONFLICT DO NOTHING",
                guild_id,
            )
            await conn.execute(
                """INSERT INTO bank_transactions (guild_id,type,target_account_id,currency_id,amount,description)
                   SELECT a.guild_id,'deposit_interest',a.id,c.id,
                          floor(b.deposit*(c.deposit_rate+CASE WHEN a.tier_key='vip' THEN COALESCE(ts.vip_deposit_rate_bonus,0) ELSE 0 END)/100),
                          '일일 예금 이자'
                     FROM bank_balances b JOIN bank_accounts a ON a.id=b.account_id
                     JOIN bank_currencies c ON c.id=b.currency_id
                     JOIN bank_tier_settings ts ON ts.guild_id=a.guild_id
                    WHERE a.guild_id=$1 AND c.active=true AND b.deposit>0
                      AND (c.deposit_rate+CASE WHEN a.tier_key='vip' THEN COALESCE(ts.vip_deposit_rate_bonus,0) ELSE 0 END)>0
                      AND floor(b.deposit*(c.deposit_rate+CASE WHEN a.tier_key='vip' THEN COALESCE(ts.vip_deposit_rate_bonus,0) ELSE 0 END)/100)>0""",
                guild_id,
            )
            await conn.execute(
                """UPDATE bank_balances b SET deposit=b.deposit+floor(b.deposit*(
                     c.deposit_rate+CASE WHEN a.tier_key='vip' THEN COALESCE(ts.vip_deposit_rate_bonus,0) ELSE 0 END
                   )/100)
                   FROM bank_accounts a,bank_currencies c,bank_tier_settings ts
                  WHERE b.account_id=a.id AND b.currency_id=c.id AND ts.guild_id=a.guild_id
                    AND a.guild_id=$1 AND c.active=true AND b.deposit>0
                    AND (c.deposit_rate+CASE WHEN a.tier_key='vip' THEN COALESCE(ts.vip_deposit_rate_bonus,0) ELSE 0 END)>0""",
                guild_id,
            )
            await conn.execute(
                """INSERT INTO bank_transactions (guild_id,type,target_account_id,currency_id,amount,description)
                   SELECT a.guild_id,'loan_interest',l.account_id,l.currency_id,
                          floor(l.amount_due*l.rate/100),'일일 대출 이자'
                     FROM bank_loans l JOIN bank_accounts a ON a.id=l.account_id
                    WHERE a.guild_id=$1 AND l.status='approved' AND l.rate>0
                      AND floor(l.amount_due*l.rate/100)>0""",
                guild_id,
            )
            await conn.execute(
                """UPDATE bank_loans l SET amount_due=l.amount_due+floor(l.amount_due*l.rate/100)
                     FROM bank_accounts a
                    WHERE l.account_id=a.id AND a.guild_id=$1 AND l.status='approved' AND l.rate>0""",
                guild_id,
            )
    return True


async def close_market_day(guild_id: str, run_date: str) -> int:
    async with pool.acquire() as conn:
        async with conn.transaction():
            claimed = await conn.fetchval(
                """INSERT INTO bank_market_cycles (guild_id,cycle_date,stage) VALUES ($1,$2,'close')
                   ON CONFLICT (guild_id,cycle_date,stage) DO NOTHING RETURNING id""",
                guild_id,
                run_date,
            )
            if not claimed:
                return 0
            accounts = await conn.fetch(
                "SELECT DISTINCT account_id FROM bank_stock_orders WHERE guild_id=$1 AND status IN ('open','partial')",
                guild_id,
            )
            total = 0
            for row in accounts:
                total += await cancel_user_orders(conn, guild_id, row["account_id"])
    return total


async def publish_market_day(guild_id: str, run_date: str) -> list[asyncpg.Record]:
    async with pool.acquire() as conn:
        async with conn.transaction():
            already_published = await conn.fetchval(
                "SELECT 1 FROM bank_market_cycles WHERE guild_id=$1 AND cycle_date=$2 AND stage='publish'",
                guild_id,
                run_date,
            )
            if already_published:
                return []
            await ensure_unscored_market_evaluations(conn, guild_id, run_date)
            rows = await conn.fetch(
                """SELECT e.id,e.stock_id,s.name,e.old_price,e.new_price,e.content_score,e.activity_score,
                          e.membership_score,e.events_score,e.growth_score,e.influence_score,e.opinion_score,
                          e.base_score,e.random_score,e.final_score,e.change_percent,e.evidence,e.created_by
                     FROM bank_stock_evaluations e JOIN bank_stocks s ON s.id=e.stock_id
                    WHERE e.guild_id=$1 AND e.evaluation_date=$2 AND e.status='pending'
                    ORDER BY lower(s.name),s.name FOR UPDATE OF e""",
                guild_id,
                run_date,
            )
            for row in rows:
                await conn.execute(
                    "UPDATE bank_stocks SET current_price=$1 WHERE id=$2",
                    row["new_price"],
                    row["stock_id"],
                )
                await conn.execute(
                    "UPDATE bank_stock_evaluations SET status='published',published_at=now() WHERE id=$1",
                    row["id"],
                )
                await conn.execute(
                    """INSERT INTO bank_market_news (guild_id,stock_id,title,content,created_by)
                       VALUES ($1,$2,$3,$4,'system')""",
                    guild_id,
                    row["stock_id"],
                    f"{row['name']} 일일 시세",
                    market_news_content(row),
                )
            await conn.execute(
                "INSERT INTO bank_market_cycles (guild_id,cycle_date,stage) VALUES ($1,$2,'publish') ON CONFLICT DO NOTHING",
                guild_id,
                run_date,
            )
    return list(rows)


@tasks.loop(minutes=1)
async def scheduled_tasks() -> None:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    minute = now.hour * 60 + now.minute
    run_date = now.date().isoformat()
    for guild in bot.guilds:
        guild_id = str(guild.id)
        try:
            if 1230 <= minute < 1260:
                closed = await close_market_day(guild_id, run_date)
                if closed:
                    await send_announcement(
                        guild_id,
                        f"오늘의 주식 주문 접수가 마감되어 미체결 주문 {fmt(closed)}건을 취소했습니다. 21:00 새 시세 발표 후 거래가 재개됩니다.",
                    )
            if 1260 <= minute < 1320:
                reports = await publish_market_day(guild_id, run_date)
                if reports:
                    message = "오늘 가상주식 시세 발표\n" + "\n\n".join(
                        market_report_line(row)
                        for row in reports
                    )
                    await send_announcement(guild_id, message)
            if minute < 30 and await accrue_interest(guild_id, run_date):
                logger.info("Daily interest accrued for guild %s", guild_id)
        except Exception:
            logger.exception(
                "Scheduled bank/market operation failed for guild %s", guild_id
            )


@scheduled_tasks.before_loop
async def before_scheduled_tasks() -> None:
    await bot.wait_until_ready()


configure_command_registry(bot.tree)


async def main() -> None:
    await bot.start(TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
