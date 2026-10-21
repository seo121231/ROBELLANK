import { pool } from "@workspace/db";
import type { PoolClient } from "pg";
import { randomInt } from "node:crypto";
import { getTier, tierAtLeast, type TierKey } from "./tiers";

type Queryable = Pick<PoolClient, "query">;
export type TierSettingKey =
  | "platinum_loan_bonus"
  | "vip_deposit_rate_bonus"
  | "bronze_storage_limit"
  | "silver_storage_limit"
  | "gold_storage_limit"
  | "platinum_storage_limit"
  | "ace_storage_limit"
  | "vip_storage_limit"
  | "loan_term_days"
  | "loan_extension_days"
  | "loan_extension_limit";

const tierSettingColumns: Record<TierSettingKey, string> = {
  platinum_loan_bonus: "platinum_loan_bonus",
  vip_deposit_rate_bonus: "vip_deposit_rate_bonus",
  bronze_storage_limit: "bronze_storage_limit",
  silver_storage_limit: "silver_storage_limit",
  gold_storage_limit: "gold_storage_limit",
  platinum_storage_limit: "platinum_storage_limit",
  ace_storage_limit: "ace_storage_limit",
  vip_storage_limit: "vip_storage_limit",
  loan_term_days: "loan_term_days",
  loan_extension_days: "loan_extension_days",
  loan_extension_limit: "loan_extension_limit",
};

type TierSettingsRow = {
  platinum_loan_bonus: string;
  vip_deposit_rate_bonus: string;
  bronze_storage_limit: number;
  silver_storage_limit: number;
  gold_storage_limit: number;
  platinum_storage_limit: number;
  ace_storage_limit: number;
  vip_storage_limit: number;
  loan_term_days: number;
  loan_extension_days: number;
  loan_extension_limit: number;
};

type CurrencyRow = {
  id: number;
  name: string;
  symbol: string;
  exchange_value: string;
  deposit_rate: string;
  loan_rate: string;
  is_base: boolean;
  active: boolean;
};

const formatInteger = (value: number) =>
  new Intl.NumberFormat("ko-KR", { maximumFractionDigits: 0 }).format(value);

export async function inTransaction<T>(
  action: (client: PoolClient) => Promise<T>,
): Promise<T> {
  for (let attempt = 0; ; attempt += 1) {
    const client = await pool.connect();
    try {
      await client.query("BEGIN");
      const result = await action(client);
      await client.query("COMMIT");
      return result;
    } catch (error) {
      await client.query("ROLLBACK").catch(() => undefined);
      const code =
        typeof error === "object" && error !== null && "code" in error
          ? String(error.code)
          : "";
      if (attempt < 2 && (code === "40P01" || code === "40001")) continue;
      throw error;
    } finally {
      client.release();
    }
  }
}

export const todayKst = (date = new Date()) =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);

export const kstMinuteOfDay = (date = new Date()) => {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "Asia/Seoul",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(date);
  const hour = Number(parts.find((part) => part.type === "hour")?.value ?? 0);
  const minute = Number(parts.find((part) => part.type === "minute")?.value ?? 0);
  return hour * 60 + minute;
};

async function ensureBaseCurrency(guildId: string, queryable: Queryable = pool) {
  const current = await queryable.query<CurrencyRow>(
    `SELECT id, name, symbol, exchange_value, deposit_rate, loan_rate, is_base, active
       FROM bank_currencies
      WHERE guild_id = $1 AND is_base = true AND active = true
      LIMIT 1`,
    [guildId],
  );
  if (current.rows[0]) return current.rows[0];

  const result = await queryable.query<CurrencyRow>(
    `INSERT INTO bank_currencies
       (guild_id, name, symbol, exchange_value, deposit_rate, loan_rate, is_base, active)
     VALUES ($1, '벨', '벨', 1, 0, 0, true, true)
     ON CONFLICT (guild_id, name) DO UPDATE SET active = true, is_base = true
     RETURNING id, name, symbol, exchange_value, deposit_rate, loan_rate, is_base, active`,
    [guildId],
  );
  return result.rows[0];
}

export async function ensureGuild(guildId: string) {
  return ensureBaseCurrency(guildId);
}

async function getCurrency(
  guildId: string,
  name: string,
  queryable: Queryable = pool,
  lock = false,
) {
  const result = await queryable.query<CurrencyRow>(
    `SELECT id, name, symbol, exchange_value, deposit_rate, loan_rate, is_base, active
       FROM bank_currencies
      WHERE guild_id = $1 AND lower(name) = lower($2) AND active = true
      LIMIT 1${lock ? " FOR UPDATE" : ""}`,
    [guildId, name],
  );
  if (!result.rows[0]) throw new Error(`재화 '${name}'을(를) 찾을 수 없습니다.`);
  return result.rows[0];
}

async function getAccount(
  guildId: string,
  discordUserId: string,
  queryable: Queryable = pool,
  lock = false,
  allowFrozen = false,
) {
  const result = await queryable.query<{
    id: number;
    frozen: boolean;
    tier_key: TierKey;
    credit_score: number;
  }>(
    `SELECT id, frozen, tier_key, credit_score FROM bank_accounts
      WHERE guild_id = $1 AND discord_user_id = $2
      LIMIT 1${lock ? " FOR UPDATE" : ""}`,
    [guildId, discordUserId],
  );
  const account = result.rows[0];
  if (!account) throw new Error("계좌가 없습니다. 먼저 /register를 사용하세요.");
  if (account.frozen && !allowFrozen) {
    throw new Error("계좌가 동결되어 거래할 수 없습니다. 관리자에게 문의하세요.");
  }
  return account;
}

async function getOrCreateAccount(
  guildId: string,
  discordUserId: string,
  queryable: Queryable,
) {
  const base = await baseCurrency(guildId, queryable);
  await queryable.query(
    `INSERT INTO bank_accounts (guild_id, discord_user_id)
     VALUES ($1, $2) ON CONFLICT (guild_id, discord_user_id) DO NOTHING`,
    [guildId, discordUserId],
  );
  const account = await getAccount(guildId, discordUserId, queryable, true, true);
  await ensureBalance(account.id, base.id, queryable);
  return account;
}

async function ensureBalance(
  accountId: number,
  currencyId: number,
  queryable: Queryable = pool,
) {
  await queryable.query(
    `INSERT INTO bank_balances (account_id, currency_id)
     VALUES ($1, $2) ON CONFLICT (account_id, currency_id) DO NOTHING`,
    [accountId, currencyId],
  );
}

async function baseCurrency(guildId: string, queryable: Queryable = pool) {
  const existing = await queryable.query<CurrencyRow>(
    `SELECT id, name, symbol, exchange_value, deposit_rate, loan_rate, is_base, active
       FROM bank_currencies
      WHERE guild_id = $1 AND is_base = true AND active = true LIMIT 1`,
    [guildId],
  );
  return existing.rows[0] ?? ensureBaseCurrency(guildId, queryable);
}

async function ensureTierSettings(
  guildId: string,
  queryable: Queryable = pool,
): Promise<TierSettingsRow> {
  await queryable.query(
    `INSERT INTO bank_tier_settings (guild_id)
     VALUES ($1) ON CONFLICT (guild_id) DO NOTHING`,
    [guildId],
  );
  const result = await queryable.query<TierSettingsRow>(
    `SELECT platinum_loan_bonus, vip_deposit_rate_bonus,
            bronze_storage_limit, silver_storage_limit, gold_storage_limit,
            platinum_storage_limit, ace_storage_limit, vip_storage_limit,
            loan_term_days, loan_extension_days, loan_extension_limit
       FROM bank_tier_settings WHERE guild_id = $1`,
    [guildId],
  );
  return result.rows[0];
}

export async function syncTierSnapshot(
  guildId: string,
  discordUserId: string,
  tierKey: TierKey,
) {
  await pool.query(
    `UPDATE bank_accounts SET tier_key = $1
      WHERE guild_id = $2 AND discord_user_id = $3`,
    [tierKey, guildId, discordUserId],
  );
}

export async function setTierSetting(
  guildId: string,
  actorDiscordUserId: string,
  key: TierSettingKey,
  value: number,
  reason: string,
) {
  const column = tierSettingColumns[key];
  return inTransaction(async (client) => {
    const settings = await ensureTierSettings(guildId, client);
    const oldValue = String(settings[key as keyof TierSettingsRow]);
    await client.query(
      `UPDATE bank_tier_settings
          SET ${column} = $1, updated_at = now()
        WHERE guild_id = $2`,
      [value, guildId],
    );
    await client.query(
      `INSERT INTO bank_tier_setting_history
         (guild_id, actor_discord_user_id, setting_key, old_value, new_value, reason)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [guildId, actorDiscordUserId, key, oldValue, String(value), reason],
    );
    return { key, oldValue, value };
  });
}

export async function setCreditScore(
  guildId: string,
  actorDiscordUserId: string,
  targetDiscordUserId: string,
  score: number,
  reason: string,
) {
  return inTransaction(async (client) => {
    const account = await getAccount(
      guildId,
      targetDiscordUserId,
      client,
      true,
      true,
    );
    await client.query(
      `UPDATE bank_accounts SET credit_score = $1 WHERE id = $2`,
      [score, account.id],
    );
    await client.query(
      `INSERT INTO bank_credit_score_history
         (guild_id, actor_discord_user_id, target_discord_user_id, old_score, new_score, reason)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [
        guildId,
        actorDiscordUserId,
        targetDiscordUserId,
        account.credit_score,
        score,
        reason,
      ],
    );
    return { oldScore: account.credit_score, score };
  });
}

export async function adjustCreditScore(
  guildId: string,
  actorDiscordUserId: string,
  targetDiscordUserId: string,
  adjustment: number,
  reason: string,
) {
  if (!Number.isInteger(adjustment) || adjustment === 0) {
    throw new Error("신용점수 변경값이 올바르지 않습니다.");
  }
  return inTransaction(async (client) => {
    const account = await getAccount(
      guildId,
      targetDiscordUserId,
      client,
      true,
      true,
    );
    const score = Math.max(0, Math.min(100, account.credit_score + adjustment));
    await client.query(
      `UPDATE bank_accounts SET credit_score = $1 WHERE id = $2`,
      [score, account.id],
    );
    await client.query(
      `INSERT INTO bank_credit_score_history
         (guild_id, actor_discord_user_id, target_discord_user_id, old_score, new_score, reason)
       VALUES ($1, $2, $3, $4, $5, $6)`,
      [
        guildId,
        actorDiscordUserId,
        targetDiscordUserId,
        account.credit_score,
        score,
        reason,
      ],
    );
    return {
      oldScore: account.credit_score,
      score,
      adjustment: score - account.credit_score,
    };
  });
}

export async function getTierSummary(
  guildId: string,
  discordUserId: string,
  tierKey: TierKey,
) {
  const account = await getAccount(guildId, discordUserId, pool, false, true);
  const settings = await ensureTierSettings(guildId);
  const currency = await getCurrency(guildId, "벨");
  const exposure = await pool.query<{ total: string }>(
    `SELECT COALESCE(SUM(
              CASE WHEN status = 'approved' THEN amount_due ELSE principal END
            ), 0)::text AS total
       FROM bank_loans
      WHERE guild_id = $1 AND account_id = $2 AND currency_id = $3
        AND loan_type = 'credit' AND status IN ('pending', 'approved')`,
    [guildId, account.id, currency.id],
  );
  const limit =
    account.credit_score * 10_000 +
    (tierAtLeast(tierKey, "platinum")
      ? Number(settings.platinum_loan_bonus)
      : 0);
  return {
    tier: getTier(tierKey),
    creditScore: account.credit_score,
    creditLimit: limit,
    creditUsed: Number(exposure.rows[0].total),
    settings,
  };
}

export async function listVaultItems(guildId: string, discordUserId: string) {
  const account = await getAccount(guildId, discordUserId, pool, false, true);
  const result = await pool.query(
    `SELECT item_name, quantity FROM bank_vault_items
      WHERE account_id = $1 AND quantity > 0
      ORDER BY lower(item_name)`,
    [account.id],
  );
  const settings = await ensureTierSettings(guildId);
  const column = `${account.tier_key}_storage_limit` as keyof TierSettingsRow;
  return {
    items: result.rows as { item_name: string; quantity: number }[],
    capacity: Number(settings[column]),
    tier: getTier(account.tier_key),
  };
}

export async function adjustVault(
  guildId: string,
  actorDiscordUserId: string,
  targetDiscordUserId: string,
  itemName: string,
  quantity: number,
  operation: "add" | "remove",
  reason: string,
) {
  const normalizedName = itemName.trim().normalize("NFKC");
  if (!normalizedName) throw new Error("아이템 이름을 입력하세요.");
  const itemKey = normalizedName.toLocaleLowerCase("ko-KR");
  return inTransaction(async (client) => {
    const account = await getAccount(
      guildId,
      targetDiscordUserId,
      client,
      true,
      true,
    );
    const settings = await ensureTierSettings(guildId, client);
    const column = `${account.tier_key}_storage_limit` as keyof TierSettingsRow;
    const capacity = Number(settings[column]);
    const current = await client.query<{ total: string }>(
      `SELECT COALESCE(SUM(quantity), 0)::text AS total
         FROM bank_vault_items WHERE account_id = $1`,
      [account.id],
    );
    if (operation === "add") {
      if (capacity <= 0) {
        throw new Error("이 등급의 보관 한도가 설정되지 않았습니다. 관리자에게 문의하세요.");
      }
      if (Number(current.rows[0].total) + quantity > capacity) {
        throw new Error(
          `보관 한도를 초과합니다. 현재 ${current.rows[0].total}개 / 한도 ${capacity}개.`,
        );
      }
      await client.query(
        `INSERT INTO bank_vault_items
           (account_id, item_key, item_name, quantity)
         VALUES ($1, $2, $3, $4)
         ON CONFLICT (account_id, item_key) DO UPDATE
           SET item_name = EXCLUDED.item_name,
               quantity = bank_vault_items.quantity + EXCLUDED.quantity,
               updated_at = now()`,
        [account.id, itemKey, normalizedName, quantity],
      );
    } else {
      const row = await client.query<{ id: number; quantity: number }>(
        `SELECT id, quantity FROM bank_vault_items
          WHERE account_id = $1 AND item_key = $2 FOR UPDATE`,
        [account.id, itemKey],
      );
      if (!row.rows[0] || row.rows[0].quantity < quantity) {
        throw new Error("은행 보관 수량이 부족합니다.");
      }
      const remaining = row.rows[0].quantity - quantity;
      if (remaining === 0) {
        await client.query(`DELETE FROM bank_vault_items WHERE id = $1`, [
          row.rows[0].id,
        ]);
      } else {
        await client.query(
          `UPDATE bank_vault_items SET quantity = $1, updated_at = now() WHERE id = $2`,
          [remaining, row.rows[0].id],
        );
      }
    }
    await client.query(
      `INSERT INTO bank_vault_history
         (guild_id, actor_discord_user_id, target_discord_user_id, item_name,
          quantity, operation, reason)
       VALUES ($1, $2, $3, $4, $5, $6, $7)`,
      [
        guildId,
        actorDiscordUserId,
        targetDiscordUserId,
        normalizedName,
        quantity,
        operation,
        reason,
      ],
    );
    return { tier: getTier(account.tier_key), capacity };
  });
}

export async function createBankItemRequest(
  guildId: string,
  discordUserId: string,
  itemName: string,
  quantity: number,
  note: string,
  tierKey: TierKey,
) {
  if (!tierAtLeast(tierKey, "platinum")) {
    throw new Error("은행 의뢰는 플레티넘 등급 이상부터 이용할 수 있습니다.");
  }
  const normalizedItem = itemName.trim().normalize("NFKC");
  if (!normalizedItem) throw new Error("아이템·재료 이름을 입력하세요.");
  return inTransaction(async (client) => {
    const account = await getAccount(guildId, discordUserId, client, true);
    await client.query(
      `UPDATE bank_accounts SET tier_key = $1 WHERE id = $2`,
      [tierKey, account.id],
    );
    const active = await client.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count
         FROM bank_item_requests
        WHERE guild_id = $1 AND discord_user_id = $2
          AND status IN ('pending', 'accepted')`,
      [guildId, discordUserId],
    );
    if (Number(active.rows[0].count) >= 5) {
      throw new Error("진행 중인 은행 의뢰는 사용자당 최대 5건까지 가능합니다.");
    }
    const result = await client.query<{ id: number }>(
      `INSERT INTO bank_item_requests
         (guild_id, discord_user_id, item_name, quantity, note)
       VALUES ($1, $2, $3, $4, $5)
       RETURNING id`,
      [guildId, discordUserId, normalizedItem, quantity, note.trim()],
    );
    return { requestId: result.rows[0].id };
  });
}

export async function listBankItemRequests(
  guildId: string,
  discordUserId?: string,
) {
  const result = discordUserId
    ? await pool.query(
        `SELECT id, discord_user_id, item_name, quantity, note, status,
                review_note, created_at
           FROM bank_item_requests
          WHERE guild_id = $1 AND discord_user_id = $2
          ORDER BY created_at DESC LIMIT 20`,
        [guildId, discordUserId],
      )
    : await pool.query(
        `SELECT id, discord_user_id, item_name, quantity, note, status,
                review_note, created_at
           FROM bank_item_requests
          WHERE guild_id = $1 AND status IN ('pending', 'accepted')
          ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, created_at
          LIMIT 50`,
        [guildId],
      );
  return result.rows;
}

export async function updateBankItemRequest(
  guildId: string,
  actorDiscordUserId: string,
  requestId: number,
  status: "accepted" | "declined" | "fulfilled",
  reviewNote: string,
) {
  return inTransaction(async (client) => {
    const result = await client.query<{
      id: number;
      discord_user_id: string;
      item_name: string;
      quantity: number;
      status: string;
    }>(
      `SELECT id, discord_user_id, item_name, quantity, status
         FROM bank_item_requests
        WHERE id = $1 AND guild_id = $2
        FOR UPDATE`,
      [requestId, guildId],
    );
    const request = result.rows[0];
    if (!request) throw new Error("은행 의뢰를 찾을 수 없습니다.");
    const validTransition =
      (request.status === "pending" &&
        (status === "accepted" || status === "declined")) ||
      (request.status === "accepted" &&
        (status === "fulfilled" || status === "declined"));
    if (!validTransition) {
      throw new Error("현재 상태에서 해당 의뢰 상태로 변경할 수 없습니다.");
    }
    await client.query(
      `UPDATE bank_item_requests
          SET status = $1, review_note = $2, reviewed_by = $3, reviewed_at = now()
        WHERE id = $4`,
      [status, reviewNote, actorDiscordUserId, requestId],
    );
    return { ...request, status };
  });
}

export async function registerAccount(guildId: string, discordUserId: string) {
  return inTransaction(async (client) => {
    const base = await baseCurrency(guildId, client);
    const account = await client.query<{ id: number }>(
      `INSERT INTO bank_accounts (guild_id, discord_user_id)
       VALUES ($1, $2)
       ON CONFLICT (guild_id, discord_user_id) DO UPDATE SET discord_user_id = EXCLUDED.discord_user_id
       RETURNING id`,
      [guildId, discordUserId],
    );
    await ensureBalance(account.rows[0].id, base.id, client);
    return { accountId: account.rows[0].id, currency: base };
  });
}

export async function getBalances(guildId: string, discordUserId: string) {
  const account = await getAccount(guildId, discordUserId, pool, false, true);
  const result = await pool.query(
    `SELECT c.name, c.symbol, b.wallet, b.deposit, c.is_base
       FROM bank_currencies c
       LEFT JOIN bank_balances b
         ON b.currency_id = c.id AND b.account_id = $2
      WHERE c.guild_id = $1 AND c.active = true
      ORDER BY c.is_base DESC, c.name`,
    [guildId, account.id],
  );
  return result.rows;
}

async function recordTransaction(
  queryable: Queryable,
  input: {
    guildId: string;
    type: string;
    actorId?: number | null;
    targetId?: number | null;
    currencyId: number;
    amount: number;
    fee?: number;
    description?: string;
    metadata?: unknown;
  },
) {
  await queryable.query(
    `INSERT INTO bank_transactions
       (guild_id, type, actor_account_id, target_account_id, currency_id, amount, fee, description, metadata)
     VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
    [
      input.guildId,
      input.type,
      input.actorId ?? null,
      input.targetId ?? null,
      input.currencyId,
      input.amount,
      input.fee ?? 0,
      input.description ?? "",
      JSON.stringify(input.metadata ?? {}),
    ],
  );
}

export async function transfer(
  guildId: string,
  senderId: string,
  recipientId: string,
  currencyName: string,
  amount: number,
) {
  if (senderId === recipientId) throw new Error("본인에게 송금할 수 없습니다.");
  return inTransaction(async (client) => {
    const sender = await getAccount(guildId, senderId, client);
    const recipient = await getAccount(guildId, recipientId, client);
    const lockedAccounts = await client.query<{
      id: number;
      frozen: boolean;
    }>(
      `SELECT id, frozen FROM bank_accounts
        WHERE id = ANY($1::int[]) ORDER BY id FOR UPDATE`,
      [[sender.id, recipient.id].sort((a, b) => a - b)],
    );
    if (lockedAccounts.rows.some((account) => account.frozen)) {
      throw new Error("동결된 계좌와는 송금할 수 없습니다.");
    }
    const currencyRow = await getCurrency(guildId, currencyName, client);
    await ensureBalance(sender.id, currencyRow.id, client);
    await ensureBalance(recipient.id, currencyRow.id, client);
    const rows = await client.query<{ account_id: number; wallet: string }>(
      `SELECT account_id, wallet FROM bank_balances
        WHERE currency_id = $1 AND account_id = ANY($2::int[])
        ORDER BY account_id FOR UPDATE`,
      [currencyRow.id, [sender.id, recipient.id].sort((a, b) => a - b)],
    );
    const senderBalance = rows.rows.find((row) => row.account_id === sender.id);
    if (!senderBalance || Number(senderBalance.wallet) < amount) {
      throw new Error("지갑 잔액이 부족합니다.");
    }
    await client.query(
      `UPDATE bank_balances SET wallet = wallet - $1 WHERE account_id = $2 AND currency_id = $3`,
      [amount, sender.id, currencyRow.id],
    );
    await client.query(
      `UPDATE bank_balances SET wallet = wallet + $1 WHERE account_id = $2 AND currency_id = $3`,
      [amount, recipient.id, currencyRow.id],
    );
    await recordTransaction(client, {
      guildId,
      type: "transfer",
      actorId: sender.id,
      targetId: recipient.id,
      currencyId: currencyRow.id,
      amount,
      description: `${currencyRow.name} 송금`,
    });
    return currencyRow;
  });
}

export async function exchange(
  guildId: string,
  discordUserId: string,
  fromName: string,
  toName: string,
  amount: number,
) {
  if (fromName.toLocaleLowerCase() === toName.toLocaleLowerCase()) {
    throw new Error("서로 다른 재화를 선택하세요.");
  }
  return inTransaction(async (client) => {
    const account = await getAccount(guildId, discordUserId, client, true);
    const from = await getCurrency(guildId, fromName, client, true);
    const to = await getCurrency(guildId, toName, client, true);
    await ensureBalance(account.id, from.id, client);
    await ensureBalance(account.id, to.id, client);
    const rows = await client.query<{
      currency_id: number;
      wallet: string;
    }>(
      `SELECT currency_id, wallet FROM bank_balances
        WHERE account_id = $1 AND currency_id = ANY($2::int[])
        ORDER BY currency_id FOR UPDATE`,
      [account.id, [from.id, to.id].sort((a, b) => a - b)],
    );
    const source = rows.rows.find((row) => row.currency_id === from.id);
    if (!source || Number(source.wallet) < amount) {
      throw new Error("지갑 잔액이 부족합니다.");
    }
    const received = Math.floor(
      (amount * Number(from.exchange_value)) / Number(to.exchange_value),
    );
    if (!Number.isSafeInteger(received) || received < 1) {
      throw new Error("환전 결과가 1 미만입니다. 더 큰 금액을 입력하세요.");
    }
    await client.query(
      `UPDATE bank_balances SET wallet = wallet - $1 WHERE account_id = $2 AND currency_id = $3`,
      [amount, account.id, from.id],
    );
    await client.query(
      `UPDATE bank_balances SET wallet = wallet + $1 WHERE account_id = $2 AND currency_id = $3`,
      [received, account.id, to.id],
    );
    await recordTransaction(client, {
      guildId,
      type: "exchange",
      actorId: account.id,
      targetId: account.id,
      currencyId: from.id,
      amount,
      description: `${from.name} → ${to.name} ${received}`,
      metadata: { received, targetCurrencyId: to.id },
    });
    return { from, to, received };
  });
}

export async function moveDeposit(
  guildId: string,
  discordUserId: string,
  currencyName: string,
  amount: number,
  direction: "deposit" | "withdraw",
) {
  return inTransaction(async (client) => {
    const account = await getAccount(guildId, discordUserId, client, true);
    const currencyRow = await getCurrency(guildId, currencyName, client, true);
    await ensureBalance(account.id, currencyRow.id, client);
    const result = await client.query<{ wallet: string; deposit: string }>(
      `SELECT wallet, deposit FROM bank_balances
        WHERE account_id = $1 AND currency_id = $2 FOR UPDATE`,
      [account.id, currencyRow.id],
    );
    const balance = result.rows[0];
    if (direction === "deposit") {
      if (Number(balance.wallet) < amount) throw new Error("지갑 잔액이 부족합니다.");
      await client.query(
        `UPDATE bank_balances SET wallet = wallet - $1, deposit = deposit + $1
          WHERE account_id = $2 AND currency_id = $3`,
        [amount, account.id, currencyRow.id],
      );
    } else {
      if (Number(balance.deposit) < amount) throw new Error("예금 잔액이 부족합니다.");
      await client.query(
        `UPDATE bank_balances SET wallet = wallet + $1, deposit = deposit - $1
          WHERE account_id = $2 AND currency_id = $3`,
        [amount, account.id, currencyRow.id],
      );
    }
    await recordTransaction(client, {
      guildId,
      type: direction,
      actorId: account.id,
      targetId: account.id,
      currencyId: currencyRow.id,
      amount,
      description: direction === "deposit" ? "지갑에서 예금" : "예금에서 지갑",
    });
    return currencyRow;
  });
}

export async function recentHistory(guildId: string, discordUserId: string) {
  const account = await getAccount(guildId, discordUserId, pool, false, true);
  const result = await pool.query(
    `SELECT t.type, t.amount, t.fee, t.description, t.created_at,
            c.name AS currency, t.target_account_id, t.actor_account_id,
            s.name AS stock_name, tr.shares, tr.execution_price
       FROM bank_transactions t
       JOIN bank_currencies c ON c.id = t.currency_id
       LEFT JOIN bank_stock_trades tr
         ON (tr.buyer_account_id = t.actor_account_id OR tr.seller_account_id = t.actor_account_id)
        AND tr.created_at = t.created_at
       LEFT JOIN bank_stocks s ON s.id = tr.stock_id
      WHERE t.guild_id = $1
        AND (t.actor_account_id = $2 OR t.target_account_id = $2)
      ORDER BY t.created_at DESC, t.id DESC LIMIT 12`,
    [guildId, account.id],
  );
  return result.rows;
}

export async function leaderboard(guildId: string, currencyName: string) {
  const currencyRow = await getCurrency(guildId, currencyName);
  const result = await pool.query(
    `SELECT a.discord_user_id, COALESCE(b.wallet, 0) AS wallet,
            COALESCE(b.deposit, 0) AS deposit,
            COALESCE(b.wallet, 0) + COALESCE(b.deposit, 0) AS total
       FROM bank_accounts a
       LEFT JOIN bank_balances b
         ON b.account_id = a.id AND b.currency_id = $2
      WHERE a.guild_id = $1
      ORDER BY total DESC, a.discord_user_id ASC
      LIMIT 10`,
    [guildId, currencyRow.id],
  );
  return { currency: currencyRow, rows: result.rows };
}

export async function listCurrencies(guildId: string) {
  await ensureBaseCurrency(guildId);
  const result = await pool.query(
    `SELECT name, symbol, exchange_value, deposit_rate, loan_rate, is_base
       FROM bank_currencies
      WHERE guild_id = $1 AND active = true
      ORDER BY is_base DESC, name`,
    [guildId],
  );
  return result.rows;
}

export async function createCurrency(
  guildId: string,
  input: {
    name: string;
    symbol: string;
    value: number;
    depositRate: number;
    loanRate: number;
  },
) {
  if (!Number.isFinite(input.value) || input.value <= 0) {
    throw new Error("환전가치는 0보다 커야 합니다.");
  }
  const result = await pool.query(
    `INSERT INTO bank_currencies
       (guild_id, name, symbol, exchange_value, deposit_rate, loan_rate, active)
     VALUES ($1, $2, $3, $4, $5, $6, true)
     ON CONFLICT (guild_id, name) DO UPDATE SET
       symbol = EXCLUDED.symbol,
       exchange_value = EXCLUDED.exchange_value,
       deposit_rate = EXCLUDED.deposit_rate,
       loan_rate = EXCLUDED.loan_rate,
       active = true
     RETURNING name, symbol, exchange_value, deposit_rate, loan_rate`,
    [
      guildId,
      input.name.trim().toLocaleLowerCase("ko-KR"),
      input.symbol.trim(),
      input.value,
      input.depositRate,
      input.loanRate,
    ],
  );
  return result.rows[0];
}

export async function setBaseCurrency(guildId: string, name: string) {
  return inTransaction(async (client) => {
    const selected = await getCurrency(guildId, name, client, true);
    await client.query(
      `UPDATE bank_currencies SET is_base = false WHERE guild_id = $1`,
      [guildId],
    );
    await client.query(
      `UPDATE bank_currencies SET is_base = true WHERE id = $1`,
      [selected.id],
    );
    return selected;
  });
}

export async function setCurrencyValue(
  guildId: string,
  name: string,
  value: number,
) {
  const selected = await getCurrency(guildId, name);
  await pool.query(
    `UPDATE bank_currencies SET exchange_value = $1 WHERE id = $2`,
    [value, selected.id],
  );
  return { ...selected, exchange_value: String(value) };
}

export async function setCurrencyRates(
  guildId: string,
  name: string,
  depositRate: number,
  loanRate: number,
) {
  const selected = await getCurrency(guildId, name);
  await pool.query(
    `UPDATE bank_currencies SET deposit_rate = $1, loan_rate = $2 WHERE id = $3`,
    [depositRate, loanRate, selected.id],
  );
  return selected;
}

export async function removeCurrency(guildId: string, name: string) {
  return inTransaction(async (client) => {
    const selected = await getCurrency(guildId, name, client, true);
    if (selected.is_base) throw new Error("기본재화는 삭제할 수 없습니다.");
    const inUse = await client.query(
      `SELECT 1 FROM bank_balances WHERE currency_id = $1
         AND (wallet <> 0 OR deposit <> 0)
       UNION ALL
       SELECT 1 FROM bank_loans WHERE currency_id = $1 AND status IN ('pending', 'approved')
       LIMIT 1`,
      [selected.id],
    );
    if (inUse.rowCount) throw new Error("잔액 또는 대출이 남아 있어 비활성화할 수 없습니다.");
    await client.query(
      `UPDATE bank_currencies SET active = false WHERE id = $1`,
      [selected.id],
    );
    return selected;
  });
}

export async function changeMoney(
  guildId: string,
  adminUserId: string,
  targetUserId: string,
  currencyName: string,
  amount: number,
  action: "mint" | "confiscate",
  reason: string,
) {
  return inTransaction(async (client) => {
    const admin = await getOrCreateAccount(guildId, adminUserId, client);
    const target = await getAccount(guildId, targetUserId, client, true, true);
    const currencyRow = await getCurrency(guildId, currencyName, client, true);
    await ensureBalance(target.id, currencyRow.id, client);
    const balance = await client.query<{ wallet: string }>(
      `SELECT wallet FROM bank_balances
        WHERE account_id = $1 AND currency_id = $2 FOR UPDATE`,
      [target.id, currencyRow.id],
    );
    if (action === "confiscate" && Number(balance.rows[0].wallet) < amount) {
      throw new Error("대상 사용자의 지갑 잔액이 부족합니다.");
    }
    const operator = action === "mint" ? "+" : "-";
    await client.query(
      `UPDATE bank_balances SET wallet = wallet ${operator} $1
        WHERE account_id = $2 AND currency_id = $3`,
      [amount, target.id, currencyRow.id],
    );
    await recordTransaction(client, {
      guildId,
      type: action,
      actorId: admin.id,
      targetId: target.id,
      currencyId: currencyRow.id,
      amount,
      description: reason,
    });
    return currencyRow;
  });
}

export async function setFrozen(
  guildId: string,
  actorUserId: string,
  targetUserId: string,
  frozen: boolean,
  reason: string,
) {
  return inTransaction(async (client) => {
    const actor = await getOrCreateAccount(guildId, actorUserId, client);
    const target = await getAccount(guildId, targetUserId, client, true, true);
    if (actor.id === target.id) throw new Error("본인 계좌 상태는 변경할 수 없습니다.");
    await client.query(`UPDATE bank_accounts SET frozen = $1 WHERE id = $2`, [
      frozen,
      target.id,
    ]);
    if (frozen) await cancelUserOrders(client, guildId, target.id);
    const base = await baseCurrency(guildId, client);
    await recordTransaction(client, {
      guildId,
      type: frozen ? "account_frozen" : "account_unfrozen",
      actorId: actor.id,
      targetId: target.id,
      currencyId: base.id,
      amount: 0,
      description: reason,
    });
    return target;
  });
}

export async function getSupply(guildId: string, currencyName: string) {
  const currencyRow = await getCurrency(guildId, currencyName);
  const result = await pool.query<{ total: string }>(
    `SELECT COALESCE(SUM(wallet + deposit), 0) AS total
       FROM bank_balances WHERE currency_id = $1`,
    [currencyRow.id],
  );
  return { currency: currencyRow, total: result.rows[0].total };
}

export async function createCreditLoanRequest(
  guildId: string,
  discordUserId: string,
  currencyName: string,
  amount: number,
  tierKey: TierKey,
) {
  if (!tierAtLeast(tierKey, "gold")) {
    throw new Error("신용 대출은 골드 등급 이상부터 신청할 수 있습니다.");
  }
  return inTransaction(async (client) => {
    const account = await getAccount(guildId, discordUserId, client, true);
    await client.query(
      `UPDATE bank_accounts SET tier_key = $1 WHERE id = $2`,
      [tierKey, account.id],
    );
    const currencyRow = await getCurrency(guildId, currencyName, client, true);
    if (currencyRow.name !== "벨") {
      throw new Error("신용 대출은 벨로만 신청할 수 있습니다.");
    }
    const settings = await ensureTierSettings(guildId, client);
    const creditLimit =
      account.credit_score * 10_000 +
      (tierAtLeast(tierKey, "platinum")
        ? Number(settings.platinum_loan_bonus)
        : 0);
    const exposure = await client.query<{ total: string }>(
      `SELECT COALESCE(SUM(
                CASE WHEN status = 'approved' THEN amount_due ELSE principal END
              ), 0)::text AS total
         FROM bank_loans
        WHERE guild_id = $1 AND account_id = $2 AND currency_id = $3
          AND loan_type = 'credit' AND status IN ('pending', 'approved')`,
      [guildId, account.id, currencyRow.id],
    );
    const available = creditLimit - Number(exposure.rows[0].total);
    if (amount > available) {
      throw new Error(
        `신용 대출 한도를 초과합니다. 신용점수 ${account.credit_score}점 기준 한도 ${formatInteger(creditLimit)}벨, 사용 중 ${formatInteger(Number(exposure.rows[0].total))}벨입니다.`,
      );
    }
    const result = await client.query<{ id: number }>(
      `INSERT INTO bank_loans
         (guild_id, account_id, currency_id, principal, amount_due, rate,
          status, loan_type, requested_tier)
       VALUES ($1, $2, $3, $4, $4, $5, 'pending', 'credit', $6)
       RETURNING id`,
      [
        guildId,
        account.id,
        currencyRow.id,
        amount,
        currencyRow.loan_rate,
        tierKey,
      ],
    );
    return {
      loanId: result.rows[0].id,
      currency: currencyRow,
      creditLimit,
      available: available - amount,
    };
  });
}

export async function createCollateralLoanRequest(
  guildId: string,
  discordUserId: string,
  itemName: string,
  quantity: number,
  amount: number,
  tierKey: TierKey,
) {
  if (!tierAtLeast(tierKey, "silver")) {
    throw new Error("담보 대출은 실버 등급 이상부터 신청할 수 있습니다.");
  }
  const normalizedItem = itemName.trim().normalize("NFKC");
  if (!normalizedItem) throw new Error("담보 아이템 이름을 입력하세요.");
  return inTransaction(async (client) => {
    const account = await getAccount(guildId, discordUserId, client, true);
    await client.query(
      `UPDATE bank_accounts SET tier_key = $1 WHERE id = $2`,
      [tierKey, account.id],
    );
    const currencyRow = await getCurrency(guildId, "벨", client, true);
    const result = await client.query<{ id: number }>(
      `INSERT INTO bank_loans
         (guild_id, account_id, currency_id, principal, amount_due, rate,
          status, loan_type, requested_tier, collateral_item, collateral_quantity,
          collateral_status)
       VALUES ($1, $2, $3, $4, $4, $5, 'pending', 'collateral', $6, $7, $8, 'pending')
       RETURNING id`,
      [
        guildId,
        account.id,
        currencyRow.id,
        amount,
        currencyRow.loan_rate,
        tierKey,
        normalizedItem,
        quantity,
      ],
    );
    return { loanId: result.rows[0].id, currency: currencyRow };
  });
}

export async function reviewLoan(
  guildId: string,
  actorUserId: string,
  loanId: number,
  approve: boolean,
  reason = "",
  verifiedCollateralValue?: number,
) {
  return inTransaction(async (client) => {
    const actor = await getOrCreateAccount(guildId, actorUserId, client);
    const result = await client.query<{
      id: number;
      account_id: number;
      currency_id: number;
      principal: string;
      status: string;
      loan_type: string;
      requested_tier: TierKey;
      collateral_item: string | null;
      collateral_quantity: number | null;
      collateral_status: string;
      discord_user_id: string;
      credit_score: number;
    }>(
      `SELECT l.id, l.account_id, l.currency_id, l.principal, l.status,
              l.loan_type, l.requested_tier, l.collateral_item,
              l.collateral_quantity, l.collateral_status,
              a.discord_user_id, a.credit_score
         FROM bank_loans l JOIN bank_accounts a ON a.id = l.account_id
        WHERE l.id = $1 AND l.guild_id = $2 FOR UPDATE`,
      [loanId, guildId],
    );
    const loan = result.rows[0];
    if (!loan || loan.status !== "pending") {
      throw new Error("대기 중인 대출 신청을 찾을 수 없습니다.");
    }
    if (approve) {
      if (loan.loan_type === "collateral") {
        if (!verifiedCollateralValue || verifiedCollateralValue <= 0) {
          throw new Error("관리자가 게임에서 확인한 담보 가치를 입력해야 합니다.");
        }
        if (Number(loan.principal) > verifiedCollateralValue) {
          throw new Error("신청 금액이 확인된 담보 가치보다 큽니다.");
        }
      } else if (verifiedCollateralValue !== undefined) {
        throw new Error("신용 대출 승인에는 담보 가치를 입력할 수 없습니다.");
      }
      const borrower = await client.query<{ frozen: boolean }>(
        `SELECT frozen FROM bank_accounts WHERE id = $1 FOR UPDATE`,
        [loan.account_id],
      );
      if (borrower.rows[0]?.frozen) throw new Error("동결된 계좌에는 대출을 지급할 수 없습니다.");
      if (loan.loan_type === "credit") {
        if (!tierAtLeast(loan.requested_tier, "gold")) {
          throw new Error("신용 대출은 골드 등급 이상만 승인할 수 있습니다.");
        }
        const settings = await ensureTierSettings(guildId, client);
        const creditLimit =
          loan.credit_score * 10_000 +
          (tierAtLeast(loan.requested_tier, "platinum")
            ? Number(settings.platinum_loan_bonus)
            : 0);
        const otherExposure = await client.query<{ total: string }>(
          `SELECT COALESCE(SUM(
                    CASE WHEN status = 'approved' THEN amount_due ELSE principal END
                  ), 0)::text AS total
             FROM bank_loans
            WHERE guild_id = $1 AND account_id = $2 AND currency_id = $3
              AND loan_type = 'credit' AND status IN ('pending', 'approved')
              AND id <> $4`,
          [guildId, loan.account_id, loan.currency_id, loan.id],
        );
        if (
          Number(otherExposure.rows[0].total) + Number(loan.principal) >
          creditLimit
        ) {
          throw new Error("현재 신용 대출 한도를 초과해 승인할 수 없습니다.");
        }
      }
      const settings = await ensureTierSettings(guildId, client);
      const termDays = Number(settings.loan_term_days);
      const dueAt =
        termDays > 0 ? new Date(Date.now() + termDays * 86_400_000) : null;
      await ensureBalance(loan.account_id, loan.currency_id, client);
      await client.query(
        `UPDATE bank_balances SET wallet = wallet + $1 WHERE account_id = $2 AND currency_id = $3`,
        [loan.principal, loan.account_id, loan.currency_id],
      );
      await client.query(
        `UPDATE bank_loans
            SET status = 'approved', reviewed_at = now(), due_at = $2,
                collateral_value = $3,
                collateral_status = CASE WHEN loan_type = 'collateral' THEN 'held' ELSE 'none' END
          WHERE id = $1`,
        [loan.id, dueAt, verifiedCollateralValue ?? null],
      );
      await recordTransaction(client, {
        guildId,
        type: "loan_disbursement",
        actorId: actor.id,
        targetId: loan.account_id,
        currencyId: loan.currency_id,
        amount: Number(loan.principal),
        description: `대출 #${loan.id} 승인`,
      });
    } else {
      await client.query(
        `UPDATE bank_loans
            SET status = 'rejected', reviewed_at = now(),
                collateral_status = CASE WHEN loan_type = 'collateral' THEN 'rejected' ELSE 'none' END
          WHERE id = $1`,
        [loan.id],
      );
      await recordTransaction(client, {
        guildId,
        type: "loan_rejected",
        actorId: actor.id,
        targetId: loan.account_id,
        currencyId: loan.currency_id,
        amount: 0,
        description: reason || `대출 #${loan.id} 거절`,
      });
    }
    return { loanId, approved: approve };
  });
}

export async function listLoans(guildId: string, discordUserId: string) {
  const account = await getAccount(guildId, discordUserId, pool, false, true);
  const result = await pool.query(
    `SELECT l.id, c.name AS currency, l.principal, l.amount_due, l.rate,
            l.status, l.loan_type, l.collateral_item, l.collateral_quantity,
            l.collateral_value, l.collateral_status, l.due_at,
            l.extension_count, l.created_at
       FROM bank_loans l JOIN bank_currencies c ON c.id = l.currency_id
      WHERE l.guild_id = $1 AND l.account_id = $2
      ORDER BY l.id DESC LIMIT 15`,
    [guildId, account.id],
  );
  return result.rows;
}

export async function listLoanQueue(guildId: string) {
  const result = await pool.query(
    `SELECT l.id, a.discord_user_id, l.loan_type, l.requested_tier,
            l.principal, l.collateral_item, l.collateral_quantity, l.created_at
       FROM bank_loans l
       JOIN bank_accounts a ON a.id = l.account_id
      WHERE l.guild_id = $1 AND l.status = 'pending'
      ORDER BY CASE l.requested_tier
                 WHEN 'vip' THEN 0
                 WHEN 'ace' THEN 1
                 ELSE 2
               END,
               l.created_at ASC
      LIMIT 30`,
    [guildId],
  );
  return result.rows;
}

export async function extendLoan(
  guildId: string,
  discordUserId: string,
  loanId: number,
  tierKey: TierKey,
) {
  if (!tierAtLeast(tierKey, "silver")) {
    throw new Error("대출 기간 연장은 실버 등급 이상부터 사용할 수 있습니다.");
  }
  return inTransaction(async (client) => {
    const account = await getAccount(guildId, discordUserId, client, true);
    await client.query(`UPDATE bank_accounts SET tier_key = $1 WHERE id = $2`, [
      tierKey,
      account.id,
    ]);
    const loanResult = await client.query<{
      id: number;
      account_id: number;
      due_at: Date | null;
      extension_count: number;
      status: string;
    }>(
      `SELECT id, account_id, due_at, extension_count, status
         FROM bank_loans WHERE id = $1 AND guild_id = $2 FOR UPDATE`,
      [loanId, guildId],
    );
    const loan = loanResult.rows[0];
    if (
      !loan ||
      loan.account_id !== account.id ||
      loan.status !== "approved" ||
      !loan.due_at
    ) {
      throw new Error("연장할 수 있는 본인 대출을 찾을 수 없습니다.");
    }
    const settings = await ensureTierSettings(guildId, client);
    const days = settings.loan_extension_days;
    const limit = settings.loan_extension_limit;
    if (days <= 0 || limit <= 0) {
      throw new Error("관리자가 대출 연장 기간과 횟수를 아직 설정하지 않았습니다.");
    }
    if (loan.extension_count >= limit) {
      throw new Error("이 대출은 설정된 연장 횟수를 모두 사용했습니다.");
    }
    const updated = await client.query<{ due_at: Date }>(
      `UPDATE bank_loans
          SET due_at = GREATEST(due_at, now()) + ($1::int * INTERVAL '1 day'),
              extension_count = extension_count + 1
        WHERE id = $2
        RETURNING due_at`,
      [days, loan.id],
    );
    await client.query(
      `INSERT INTO bank_loan_extensions
         (loan_id, discord_user_id, days, old_due_at, new_due_at)
       VALUES ($1, $2, $3, $4, $5)`,
      [loan.id, discordUserId, days, loan.due_at, updated.rows[0].due_at],
    );
    return { days, dueAt: updated.rows[0].due_at };
  });
}

export async function returnCollateral(
  guildId: string,
  actorDiscordUserId: string,
  loanId: number,
  reason: string,
) {
  return inTransaction(async (client) => {
    const result = await client.query<{
      id: number;
      discord_user_id: string;
      status: string;
      loan_type: string;
      collateral_item: string | null;
      collateral_quantity: number | null;
      collateral_status: string;
    }>(
      `SELECT l.id, a.discord_user_id, l.status, l.loan_type,
              l.collateral_item, l.collateral_quantity, l.collateral_status
         FROM bank_loans l
         JOIN bank_accounts a ON a.id = l.account_id
        WHERE l.id = $1 AND l.guild_id = $2
        FOR UPDATE`,
      [loanId, guildId],
    );
    const loan = result.rows[0];
    if (
      !loan ||
      loan.loan_type !== "collateral" ||
      loan.status !== "repaid" ||
      loan.collateral_status !== "return_due"
    ) {
      throw new Error("반환 가능한 상환 완료 담보를 찾을 수 없습니다.");
    }
    await client.query(
      `UPDATE bank_loans SET collateral_status = 'returned' WHERE id = $1`,
      [loan.id],
    );
    await client.query(
      `INSERT INTO bank_vault_history
         (guild_id, actor_discord_user_id, target_discord_user_id, item_name,
          quantity, operation, reason)
       VALUES ($1, $2, $3, $4, $5, 'collateral_return', $6)`,
      [
        guildId,
        actorDiscordUserId,
        loan.discord_user_id,
        loan.collateral_item ?? "담보",
        loan.collateral_quantity ?? 0,
        reason,
      ],
    );
    return {
      discordUserId: loan.discord_user_id,
      itemName: loan.collateral_item,
      quantity: loan.collateral_quantity,
    };
  });
}

export async function repayLoan(
  guildId: string,
  discordUserId: string,
  loanId: number,
  requestedAmount: number,
) {
  return inTransaction(async (client) => {
    const account = await getAccount(guildId, discordUserId, client, true);
    const loanResult = await client.query<{
      id: number;
      account_id: number;
      currency_id: number;
      amount_due: string;
      status: string;
      loan_type: string;
    }>(
      `SELECT id, account_id, currency_id, amount_due, status, loan_type
         FROM bank_loans WHERE id = $1 AND guild_id = $2 FOR UPDATE`,
      [loanId, guildId],
    );
    const loan = loanResult.rows[0];
    if (!loan || loan.account_id !== account.id || loan.status !== "approved") {
      throw new Error("상환 가능한 본인 대출을 찾을 수 없습니다.");
    }
    const due = Number(loan.amount_due);
    const payment = Math.min(requestedAmount, due);
    await ensureBalance(account.id, loan.currency_id, client);
    const balance = await client.query<{ wallet: string }>(
      `SELECT wallet FROM bank_balances
        WHERE account_id = $1 AND currency_id = $2 FOR UPDATE`,
      [account.id, loan.currency_id],
    );
    if (Number(balance.rows[0].wallet) < payment) {
      throw new Error("지갑 잔액이 부족합니다.");
    }
    await client.query(
      `UPDATE bank_balances SET wallet = wallet - $1 WHERE account_id = $2 AND currency_id = $3`,
      [payment, account.id, loan.currency_id],
    );
    const remaining = due - payment;
    await client.query(
      `UPDATE bank_loans
          SET amount_due = $1, status = $2,
              collateral_status = CASE
                WHEN $2 = 'repaid' AND loan_type = 'collateral' THEN 'return_due'
                ELSE collateral_status
              END
        WHERE id = $3`,
      [remaining, remaining === 0 ? "repaid" : "approved", loan.id],
    );
    await recordTransaction(client, {
      guildId,
      type: "loan_repayment",
      actorId: account.id,
      targetId: account.id,
      currencyId: loan.currency_id,
      amount: payment,
      description: `대출 #${loan.id} 상환`,
    });
    return { payment, remaining };
  });
}

export async function accrueInterest(guildId: string, runDate: string) {
  return inTransaction(async (client) => {
    const run = await client.query(
      `INSERT INTO bank_interest_runs (guild_id, run_date)
       VALUES ($1, $2) ON CONFLICT (guild_id, run_date) DO NOTHING RETURNING id`,
      [guildId, runDate],
    );
    if (!run.rowCount) return false;
    await ensureTierSettings(guildId, client);
    await client.query(
      `INSERT INTO bank_transactions
         (guild_id, type, target_account_id, currency_id, amount, description)
       SELECT a.guild_id, 'deposit_interest', a.id, c.id,
               floor(b.deposit * (
                 c.deposit_rate +
                 CASE WHEN a.tier_key = 'vip'
                   THEN COALESCE(ts.vip_deposit_rate_bonus, 0) ELSE 0 END
               ) / 100), '일일 예금 이자'
         FROM bank_balances b
         JOIN bank_accounts a ON a.id = b.account_id
         JOIN bank_currencies c ON c.id = b.currency_id
         LEFT JOIN bank_tier_settings ts ON ts.guild_id = a.guild_id
        WHERE a.guild_id = $1 AND c.active = true
          AND b.deposit > 0
          AND (c.deposit_rate +
               CASE WHEN a.tier_key = 'vip'
                 THEN COALESCE(ts.vip_deposit_rate_bonus, 0) ELSE 0 END) > 0
          AND floor(b.deposit * (
                c.deposit_rate +
                CASE WHEN a.tier_key = 'vip'
                  THEN COALESCE(ts.vip_deposit_rate_bonus, 0) ELSE 0 END
              ) / 100) > 0`,
      [guildId],
    );
    await client.query(
      `UPDATE bank_balances b
          SET deposit = b.deposit + floor(b.deposit * (
            c.deposit_rate +
            CASE WHEN a.tier_key = 'vip'
              THEN COALESCE(ts.vip_deposit_rate_bonus, 0) ELSE 0 END
          ) / 100)
         FROM bank_accounts a, bank_currencies c, bank_tier_settings ts
        WHERE b.account_id = a.id AND b.currency_id = c.id
          AND ts.guild_id = a.guild_id
          AND a.guild_id = $1 AND c.active = true
          AND b.deposit > 0
          AND (c.deposit_rate +
               CASE WHEN a.tier_key = 'vip'
                 THEN COALESCE(ts.vip_deposit_rate_bonus, 0) ELSE 0 END) > 0`,
      [guildId],
    );
    await client.query(
      `INSERT INTO bank_transactions
         (guild_id, type, target_account_id, currency_id, amount, description)
       SELECT a.guild_id, 'loan_interest', l.account_id, l.currency_id,
              floor(l.amount_due * l.rate / 100), '일일 대출 이자'
         FROM bank_loans l
         JOIN bank_accounts a ON a.id = l.account_id
        WHERE a.guild_id = $1 AND l.status = 'approved'
          AND l.rate > 0 AND floor(l.amount_due * l.rate / 100) > 0`,
      [guildId],
    );
    await client.query(
      `UPDATE bank_loans l
          SET amount_due = l.amount_due + floor(l.amount_due * l.rate / 100)
         FROM bank_accounts a
        WHERE l.account_id = a.id AND a.guild_id = $1
          AND l.status = 'approved' AND l.rate > 0`,
      [guildId],
    );
    return true;
  });
}

async function findStock(guildId: string, stockName: string, queryable: Queryable = pool, lock = false) {
  const result = await queryable.query<{
    id: number;
    name: string;
    description: string;
    current_price: number;
    total_shares: number;
    market_cap: string;
    listed: boolean;
  }>(
    `SELECT id, name, description, current_price, total_shares,
            current_price::numeric * total_shares AS market_cap, listed
       FROM bank_stocks
      WHERE guild_id = $1 AND lower(trim(name)) = lower(trim($2))
      LIMIT 1${lock ? " FOR UPDATE" : ""}`,
    [guildId, stockName],
  );
  const stock = result.rows[0];
  if (!stock) throw new Error(`종목 이름 '${stockName}'을(를) 찾을 수 없습니다.`);
  if (!stock.listed) throw new Error("상장 폐지된 종목입니다.");
  return stock;
}

export async function listStocks(guildId: string) {
  const result = await pool.query<{
    name: string;
    description: string;
    current_price: number;
    total_shares: number;
    market_cap: string;
    change_percent: number | null;
  }>(
    `SELECT s.name, s.description, s.current_price, s.total_shares,
            s.current_price::bigint * s.total_shares AS market_cap,
            e.change_percent
       FROM bank_stocks s
       LEFT JOIN LATERAL (
         SELECT change_percent
           FROM bank_stock_evaluations
          WHERE stock_id = s.id AND status = 'published'
          ORDER BY evaluation_date DESC LIMIT 1
       ) e ON true
      WHERE s.guild_id = $1 AND s.listed = true
      ORDER BY lower(s.name), s.name`,
    [guildId],
  );
  return result.rows;
}

export async function quoteStock(guildId: string, stockName: string) {
  const stock = await findStock(guildId, stockName);
  const result = await pool.query(
    `SELECT evaluation_date, content_score, activity_score, membership_score,
            events_score, growth_score, influence_score, opinion_score,
            base_score, random_score, final_score, change_percent,
            old_price, new_price, evidence
       FROM bank_stock_evaluations
      WHERE stock_id = $1 AND status = 'published'
      ORDER BY evaluation_date DESC LIMIT 1`,
    [stock.id],
  );
  const orderBook = await pool.query(
    `SELECT
       (SELECT limit_price FROM bank_stock_orders
         WHERE stock_id = $1 AND side = 'buy' AND status IN ('open', 'partial')
         ORDER BY limit_price DESC, created_at ASC, id ASC LIMIT 1) AS best_bid,
       (SELECT COALESCE(SUM(remaining), 0) FROM bank_stock_orders
         WHERE stock_id = $1 AND side = 'buy' AND status IN ('open', 'partial')) AS bid_shares,
       (SELECT limit_price FROM bank_stock_orders
         WHERE stock_id = $1 AND side = 'sell' AND status IN ('open', 'partial')
         ORDER BY limit_price ASC, created_at ASC, id ASC LIMIT 1) AS best_ask,
       (SELECT COALESCE(SUM(remaining), 0) FROM bank_stock_orders
         WHERE stock_id = $1 AND side = 'sell' AND status IN ('open', 'partial')) AS ask_shares`,
    [stock.id],
  );
  const trades = await pool.query(
    `SELECT shares, execution_price, created_at
       FROM bank_stock_trades
      WHERE stock_id = $1
      ORDER BY created_at DESC, id DESC LIMIT 3`,
    [stock.id],
  );
  return {
    ...stock,
    market_cap: stock.current_price * stock.total_shares,
    evaluation: result.rows[0] ?? null,
    orderBook: orderBook.rows[0],
    recentTrades: trades.rows,
  };
}

export async function createStock(
  guildId: string,
  createdBy: string,
  name: string,
  description: string,
  price: number,
  initialShares: number,
  holderDiscordId: string,
  reason: string,
) {
  const normalizedName = name.normalize("NFC").trim().replace(/\s+/g, " ");
  const normalizedDescription = description.trim();
  if (!normalizedName || normalizedName.length > 60) {
    throw new Error("종목 이름은 1~60자여야 합니다.");
  }
  if (!normalizedDescription || normalizedDescription.length > 500) {
    throw new Error("종목 소개는 1~500자로 입력하세요.");
  }
  return inTransaction(async (client) => {
    const holder = await getAccount(guildId, holderDiscordId, client, true);
    const duplicate = await client.query(
      `SELECT 1 FROM bank_stocks
        WHERE guild_id = $1 AND lower(trim(name)) = lower(trim($2))
        LIMIT 1`,
      [guildId, normalizedName],
    );
    if (duplicate.rowCount) {
      throw new Error("같은 이름의 종목이 이미 있습니다. 기존 종목 이름을 확인하세요.");
    }
    const stock = await client.query<{ id: number }>(
      `INSERT INTO bank_stocks (guild_id, name, description, current_price, total_shares)
       VALUES ($1, $2, $3, $4, $5) RETURNING id`,
      [guildId, normalizedName, normalizedDescription, price, initialShares],
    );
    await client.query(
      `INSERT INTO bank_stock_holdings (stock_id, account_id, shares)
       VALUES ($1, $2, $3)`,
      [stock.rows[0].id, holder.id, initialShares],
    );
    await client.query(
      `INSERT INTO bank_market_news (guild_id, stock_id, title, content, created_by)
       VALUES ($1, $2, '신규 상장', $3, $4)`,
      [guildId, stock.rows[0].id, `${normalizedDescription}\n상장 사유: ${reason}`, createdBy],
    );
    return { name: normalizedName, description: normalizedDescription, initialShares, price };
  });
}

export async function updateStockDescription(
  guildId: string,
  authorId: string,
  stockName: string,
  description: string,
  reason: string,
) {
  const normalizedDescription = description.trim();
  if (!normalizedDescription || normalizedDescription.length > 500) {
    throw new Error("종목 소개는 1~500자로 입력하세요.");
  }
  return inTransaction(async (client) => {
    const stock = await findStock(guildId, stockName, client, true);
    await client.query(
      `UPDATE bank_stocks SET description = $1 WHERE id = $2`,
      [normalizedDescription, stock.id],
    );
    await client.query(
      `INSERT INTO bank_market_news (guild_id, stock_id, title, content, created_by)
       VALUES ($1, $2, '종목 소개 수정', $3, $4)`,
      [guildId, stock.id, `${normalizedDescription}\n변경 사유: ${reason}`, authorId],
    );
    return { ...stock, description: normalizedDescription };
  });
}

async function cancelUserOrders(
  client: Queryable,
  guildId: string,
  accountId: number,
  stockId?: number,
) {
  const base = await baseCurrency(guildId, client);
  const orders = await client.query<{
    id: number;
    side: string;
    remaining: number;
    limit_price: number;
    account_id: number;
  }>(
    `SELECT id, side, remaining, limit_price, account_id
       FROM bank_stock_orders
      WHERE guild_id = $1 AND account_id = $2 AND status IN ('open', 'partial')
        AND ($3::int IS NULL OR stock_id = $3)
      FOR UPDATE`,
    [guildId, accountId, stockId ?? null],
  );
  for (const order of orders.rows) {
    if (order.side === "buy") {
      const refund = order.remaining * order.limit_price;
      await client.query(
        `INSERT INTO bank_balances (account_id, currency_id, wallet)
         VALUES ($1, $2, $3)
         ON CONFLICT (account_id, currency_id)
         DO UPDATE SET wallet = bank_balances.wallet + EXCLUDED.wallet`,
        [accountId, base.id, refund],
      );
    }
    await client.query(
      `UPDATE bank_stock_orders SET status = 'cancelled', remaining = 0 WHERE id = $1`,
      [order.id],
    );
  }
  return orders.rowCount ?? 0;
}

export async function cancelMarketOrders(guildId: string, date: string) {
  return inTransaction(async (client) => {
    const stage = await client.query(
      `INSERT INTO bank_market_cycles (guild_id, cycle_date, stage)
       VALUES ($1, $2, 'close')
       ON CONFLICT (guild_id, cycle_date, stage) DO NOTHING RETURNING id`,
      [guildId, date],
    );
    if (!stage.rowCount) return 0;
    const accounts = await client.query<{ account_id: number }>(
      `SELECT DISTINCT account_id FROM bank_stock_orders
        WHERE guild_id = $1 AND status IN ('open', 'partial')`,
      [guildId],
    );
    let cancelled = 0;
    for (const account of accounts.rows) {
      cancelled += await cancelUserOrders(client, guildId, account.account_id);
    }
    return cancelled;
  });
}

export async function placeOrder(
  guildId: string,
  discordUserId: string,
  stockName: string,
  side: "buy" | "sell",
  quantity: number,
  limitPrice: number,
) {
  if (kstMinuteOfDay() >= 1230 && kstMinuteOfDay() < 1260) {
    throw new Error("20:30~21:00 시세 산정 시간에는 주문할 수 없습니다.");
  }
  return inTransaction(async (client) => {
    const account = await getAccount(guildId, discordUserId, client, true);
    const stock = await findStock(guildId, stockName, client, true);
    const base = await baseCurrency(guildId, client);
    if (side === "buy") {
      const cost = quantity * limitPrice;
      if (!Number.isSafeInteger(cost)) throw new Error("주문 금액이 너무 큽니다.");
      await ensureBalance(account.id, base.id, client);
      const balance = await client.query<{ wallet: string }>(
        `SELECT wallet FROM bank_balances
          WHERE account_id = $1 AND currency_id = $2 FOR UPDATE`,
        [account.id, base.id],
      );
      if (Number(balance.rows[0].wallet) < cost) {
        throw new Error("주문 금액을 지갑에서 확보할 수 없습니다.");
      }
      await client.query(
        `UPDATE bank_balances SET wallet = wallet - $1 WHERE account_id = $2 AND currency_id = $3`,
        [cost, account.id, base.id],
      );
    } else {
      const holding = await client.query<{ shares: number }>(
        `SELECT shares FROM bank_stock_holdings
          WHERE stock_id = $1 AND account_id = $2`,
        [stock.id, account.id],
      );
      const row = holding.rows[0];
      const pendingSell = await client.query<{ reserved: number }>(
        `SELECT COALESCE(SUM(remaining), 0) AS reserved FROM bank_stock_orders
          WHERE stock_id = $1 AND account_id = $2 AND side = 'sell'
            AND status IN ('open', 'partial')`,
        [stock.id, account.id],
      );
      const available = (row?.shares ?? 0) - Number(pendingSell.rows[0].reserved);
      if (available < quantity) throw new Error("매도 가능한 보유 주식 수가 부족합니다.");
    }

    const created = await client.query<{ id: number }>(
      `INSERT INTO bank_stock_orders
         (guild_id, stock_id, account_id, side, limit_price, quantity, remaining)
       VALUES ($1, $2, $3, $4, $5, $6, $6) RETURNING id`,
      [guildId, stock.id, account.id, side, limitPrice, quantity],
    );
    const incomingId = created.rows[0].id;
    let remaining = quantity;
    const opposite = side === "buy" ? "sell" : "buy";
    const matches = await client.query<{
      id: number;
      account_id: number;
      limit_price: number;
      remaining: number;
    }>(
      `SELECT id, account_id, limit_price, remaining
         FROM bank_stock_orders
        WHERE stock_id = $1 AND side = $2 AND status IN ('open', 'partial')
          AND account_id <> $3
          AND ($4 = 'buy' AND limit_price <= $5 OR $4 = 'sell' AND limit_price >= $5)
        ORDER BY
          CASE WHEN $4 = 'buy' THEN limit_price END ASC,
          CASE WHEN $4 = 'sell' THEN limit_price END DESC,
          created_at ASC, id ASC
        FOR UPDATE`,
      [stock.id, opposite, account.id, side, limitPrice],
    );
    for (const resting of matches.rows) {
      if (remaining <= 0) break;
      const fill = Math.min(remaining, resting.remaining);
      const executionPrice = resting.limit_price;
      const gross = fill * executionPrice;
      if (!Number.isSafeInteger(gross)) throw new Error("체결 금액이 너무 큽니다.");
      const fee = Math.round(gross * 0.075);
      const buyerId = side === "buy" ? account.id : resting.account_id;
      const sellerId = side === "sell" ? account.id : resting.account_id;

      if (side === "buy" && limitPrice > executionPrice) {
        await client.query(
          `UPDATE bank_balances SET wallet = wallet + $1
            WHERE account_id = $2 AND currency_id = $3`,
          [fill * (limitPrice - executionPrice), account.id, base.id],
        );
      }
      await client.query(
        `INSERT INTO bank_balances (account_id, currency_id, wallet)
         VALUES ($1, $2, $3)
         ON CONFLICT (account_id, currency_id)
         DO UPDATE SET wallet = bank_balances.wallet + EXCLUDED.wallet`,
        [sellerId, base.id, gross - fee],
      );
      await client.query(
        `INSERT INTO bank_stock_holdings (stock_id, account_id, shares)
         VALUES ($1, $2, $3)
         ON CONFLICT (stock_id, account_id)
         DO UPDATE SET shares = bank_stock_holdings.shares + EXCLUDED.shares`,
        [stock.id, buyerId, fill],
      );
      await client.query(
        `UPDATE bank_stock_holdings SET shares = shares - $1
          WHERE stock_id = $2 AND account_id = $3`,
        [fill, stock.id, sellerId],
      );
      await client.query(
        `UPDATE bank_stock_orders
            SET remaining = remaining - $1,
                status = CASE WHEN remaining - $1 = 0 THEN 'filled' ELSE 'partial' END
          WHERE id = $2`,
        [fill, resting.id, fill],
      );
      await client.query(
        `INSERT INTO bank_stock_trades
           (guild_id, stock_id, buyer_account_id, seller_account_id, currency_id,
            shares, execution_price, gross_amount, fee)
         VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
        [guildId, stock.id, buyerId, sellerId, base.id, fill, executionPrice, gross, fee],
      );
      await recordTransaction(client, {
        guildId,
        type: "stock_buy",
        actorId: buyerId,
        targetId: sellerId,
        currencyId: base.id,
        amount: gross,
        description: `${stock.name} ${fill}주 매수`,
        metadata: { stockId: stock.id, shares: fill, price: executionPrice },
      });
      await recordTransaction(client, {
        guildId,
        type: "stock_sell",
        actorId: sellerId,
        targetId: buyerId,
        currencyId: base.id,
        amount: gross - fee,
        fee,
        description: `${stock.name} ${fill}주 매도`,
        metadata: { stockId: stock.id, shares: fill, price: executionPrice },
      });
      remaining -= fill;
    }
    await client.query(
      `UPDATE bank_stock_orders
          SET remaining = $1,
              status = CASE WHEN $1 = 0 THEN 'filled' ELSE 'open' END
        WHERE id = $2`,
      [remaining, incomingId],
    );
    return { orderId: incomingId, filled: quantity - remaining, remaining, stock };
  });
}

export async function listOrders(guildId: string, discordUserId: string) {
  const account = await getAccount(guildId, discordUserId, pool, false, true);
  const result = await pool.query(
    `SELECT o.id, s.name, o.side, o.limit_price, o.quantity, o.remaining, o.status
       FROM bank_stock_orders o JOIN bank_stocks s ON s.id = o.stock_id
      WHERE o.guild_id = $1 AND o.account_id = $2
        AND o.status IN ('open', 'partial')
      ORDER BY o.created_at, o.id`,
    [guildId, account.id],
  );
  return result.rows;
}

export async function cancelOrder(
  guildId: string,
  discordUserId: string,
  orderId: number,
) {
  return inTransaction(async (client) => {
    const account = await getAccount(guildId, discordUserId, client, true, true);
    const result = await client.query<{
      id: number;
      side: string;
      remaining: number;
      limit_price: number;
    }>(
      `SELECT id, side, remaining, limit_price FROM bank_stock_orders
        WHERE id = $1 AND guild_id = $2 AND account_id = $3
          AND status IN ('open', 'partial') FOR UPDATE`,
      [orderId, guildId, account.id],
    );
    const order = result.rows[0];
    if (!order) throw new Error("취소할 수 있는 본인 주문이 없습니다.");
    if (order.side === "buy") {
      const base = await baseCurrency(guildId, client);
      const refund = order.remaining * order.limit_price;
      await client.query(
        `INSERT INTO bank_balances (account_id, currency_id, wallet)
         VALUES ($1, $2, $3)
         ON CONFLICT (account_id, currency_id)
         DO UPDATE SET wallet = bank_balances.wallet + EXCLUDED.wallet`,
        [account.id, base.id, refund],
      );
    }
    await client.query(
      `UPDATE bank_stock_orders SET status = 'cancelled', remaining = 0 WHERE id = $1`,
      [orderId],
    );
    return order;
  });
}

export async function portfolio(guildId: string, discordUserId: string) {
  const account = await getAccount(guildId, discordUserId, pool, false, true);
  const result = await pool.query(
    `SELECT s.name, s.current_price, h.shares,
            h.shares * s.current_price AS market_value, s.listed
       FROM bank_stock_holdings h JOIN bank_stocks s ON s.id = h.stock_id
      WHERE s.guild_id = $1 AND h.account_id = $2 AND h.shares > 0
      ORDER BY s.listed DESC, lower(s.name), s.name`,
    [guildId, account.id],
  );
  return result.rows;
}

export async function removeStock(
  guildId: string,
  stockName: string,
  reason: string,
) {
  return inTransaction(async (client) => {
    const stock = await findStock(guildId, stockName, client, true);
    const openOrders = await client.query<{ account_id: number }>(
      `SELECT DISTINCT account_id FROM bank_stock_orders
        WHERE stock_id = $1 AND status IN ('open', 'partial')`,
      [stock.id],
    );
    for (const row of openOrders.rows) {
      await cancelUserOrders(client, guildId, row.account_id, stock.id);
    }
    await client.query(`UPDATE bank_stocks SET listed = false WHERE id = $1`, [
      stock.id,
    ]);
    await client.query(
      `INSERT INTO bank_market_news (guild_id, stock_id, title, content, created_by)
       VALUES ($1, $2, '상장 폐지', $3, 'system')`,
      [guildId, stock.id, reason],
    );
    return stock;
  });
}

export async function alterShares(
  guildId: string,
  actorUserId: string,
  stockName: string,
  holderUserId: string,
  shares: number,
  operation: "issue" | "burn",
  reason: string,
) {
  return inTransaction(async (client) => {
    await getOrCreateAccount(guildId, actorUserId, client);
    const holder = await getAccount(guildId, holderUserId, client, true, true);
    const stock = await findStock(guildId, stockName, client, true);
    if (operation === "issue") {
      await client.query(
        `UPDATE bank_stocks SET total_shares = total_shares + $1 WHERE id = $2`,
        [shares, stock.id],
      );
      await client.query(
        `INSERT INTO bank_stock_holdings (stock_id, account_id, shares)
         VALUES ($1, $2, $3)
         ON CONFLICT (stock_id, account_id)
         DO UPDATE SET shares = bank_stock_holdings.shares + EXCLUDED.shares`,
        [stock.id, holder.id, shares],
      );
    } else {
      const pendingSell = await client.query<{ reserved: number }>(
        `SELECT COALESCE(SUM(remaining), 0) AS reserved FROM bank_stock_orders
          WHERE stock_id = $1 AND account_id = $2 AND side = 'sell'
            AND status IN ('open', 'partial')`,
        [stock.id, holder.id],
      );
      const holding = await client.query<{ shares: number }>(
        `SELECT shares FROM bank_stock_holdings WHERE stock_id = $1 AND account_id = $2 FOR UPDATE`,
        [stock.id, holder.id],
      );
      if (
        !holding.rows[0] ||
        holding.rows[0].shares - Number(pendingSell.rows[0].reserved) < shares
      ) {
        throw new Error("미체결 매도 주문을 제외한 보유 주식이 부족합니다.");
      }
      await client.query(
        `UPDATE bank_stock_holdings SET shares = shares - $1 WHERE stock_id = $2 AND account_id = $3`,
        [shares, stock.id, holder.id],
      );
      await client.query(
        `UPDATE bank_stocks SET total_shares = total_shares - $1 WHERE id = $2`,
        [shares, stock.id],
      );
    }
    await client.query(
      `INSERT INTO bank_market_news (guild_id, stock_id, title, content, created_by)
       VALUES ($1, $2, $3, $4, $5)`,
      [
        guildId,
        stock.id,
        operation === "issue" ? "주식 신규 발행" : "주식 소각",
        `${holderUserId} · ${shares}주 · ${reason}`,
        actorUserId,
      ],
    );
    return stock;
  });
}

export async function saveEvaluation(
  guildId: string,
  evaluatorUserId: string,
  stockName: string,
  scores: {
    content: number;
    activity: number;
    membership: number;
    events: number;
    growth: number;
    influence: number;
    opinion: number;
    evidence: string;
  },
  date: string,
) {
  const minute = kstMinuteOfDay();
  if (minute < 1230 || minute >= 1260) {
    throw new Error("평가는 한국 시간 20:30~21:00 사이에만 등록할 수 있습니다.");
  }
  return inTransaction(async (client) => {
    const stock = await findStock(guildId, stockName, client, true);
    const conflict = await client.query(
      `SELECT 1 FROM bank_stock_officers
        WHERE stock_id = $1 AND discord_user_id = $2`,
      [stock.id, evaluatorUserId],
    );
    if (conflict.rowCount) {
      throw new Error("해당 길드의 지정 관계자는 자기 종목 평가에 참여할 수 없습니다.");
    }
    const baseScore =
      scores.content +
      scores.activity +
      scores.membership +
      scores.events +
      scores.growth +
      scores.influence +
      scores.opinion;
    const randomScore = randomInt(-10, 11);
    const finalScore = baseScore + randomScore;
    const [minimum, maximum] = changeRange(finalScore);
    const changePercent =
      minimum === maximum ? minimum : randomInt(minimum, maximum + 1);
    const newPrice =
      changePercent === 0
        ? stock.current_price
        : Math.max(
            1,
            Math.round(stock.current_price * (1 + changePercent / 100)),
          );
    const result = await client.query(
      `INSERT INTO bank_stock_evaluations
         (guild_id, stock_id, evaluation_date, content_score, activity_score,
          membership_score, events_score, growth_score, influence_score, opinion_score,
          base_score, random_score, final_score, change_percent, old_price, new_price,
          evidence, status, created_by)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,'pending',$18)
       ON CONFLICT (stock_id, evaluation_date) DO UPDATE SET
         content_score = EXCLUDED.content_score,
         activity_score = EXCLUDED.activity_score,
         membership_score = EXCLUDED.membership_score,
         events_score = EXCLUDED.events_score,
         growth_score = EXCLUDED.growth_score,
         influence_score = EXCLUDED.influence_score,
         opinion_score = EXCLUDED.opinion_score,
         base_score = EXCLUDED.base_score,
         random_score = EXCLUDED.random_score,
         final_score = EXCLUDED.final_score,
         change_percent = EXCLUDED.change_percent,
         old_price = EXCLUDED.old_price,
         new_price = EXCLUDED.new_price,
         evidence = EXCLUDED.evidence,
         status = 'pending',
         created_by = EXCLUDED.created_by,
         created_at = now(),
         published_at = NULL
       RETURNING final_score, random_score, change_percent, old_price, new_price`,
      [
        guildId,
        stock.id,
        date,
        scores.content,
        scores.activity,
        scores.membership,
        scores.events,
        scores.growth,
        scores.influence,
        scores.opinion,
        baseScore,
        randomScore,
        finalScore,
        changePercent,
        stock.current_price,
        newPrice,
        scores.evidence,
        evaluatorUserId,
      ],
    );
    return { stock, ...result.rows[0] };
  });
}

function changeRange(score: number): [number, number] {
  if (score === 0) return [0, 0];
  const magnitude = Math.abs(score);
  const bands: [number, number, number, number][] = [
    [1, 5, 1, 2],
    [6, 10, 2, 4],
    [11, 15, 4, 6],
    [16, 20, 6, 8],
    [21, 25, 8, 10],
    [26, 30, 10, 12],
    [31, 35, 12, 14],
    [36, 40, 14, 16],
    [41, 45, 16, 18],
    [46, 50, 18, 20],
  ];
  const band = bands.find(([min, max]) => magnitude >= min && magnitude <= max);
  if (!band) throw new Error("평가 점수가 허용 범위를 벗어났습니다.");
  const sign = score > 0 ? 1 : -1;
  return [band[2] * sign, band[3] * sign].sort((a, b) => a - b) as [
    number,
    number,
  ];
}

export async function publishEvaluations(
  guildId: string,
  date: string,
  stockName?: string,
) {
  return inTransaction(async (client) => {
    const evaluationsResult = await client.query<{
      id: number;
      stock_id: number;
      name: string;
      old_price: number;
      new_price: number;
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
      evidence: string;
    }>(
      `SELECT e.id, e.stock_id, s.name, e.old_price, e.new_price,
              e.content_score, e.activity_score, e.membership_score,
              e.events_score, e.growth_score, e.influence_score, e.opinion_score,
              e.base_score, e.random_score, e.final_score, e.change_percent, e.evidence
         FROM bank_stock_evaluations e
         JOIN bank_stocks s ON s.id = e.stock_id
        WHERE e.guild_id = $1 AND e.evaluation_date = $2 AND e.status = 'pending'
          AND ($3::text IS NULL OR lower(trim(s.name)) = lower(trim($3)))
        ORDER BY lower(s.name), s.name FOR UPDATE OF e`,
      [guildId, date, stockName ?? null],
    );
    if (!evaluationsResult.rowCount) {
      throw new Error("오늘 공지할 미게시 평가가 없습니다.");
    }
    const reports = [];
    for (const evaluation of evaluationsResult.rows) {
      await client.query(
        `UPDATE bank_stocks SET current_price = $1 WHERE id = $2`,
        [evaluation.new_price, evaluation.stock_id],
      );
      await client.query(
        `UPDATE bank_stock_evaluations
            SET status = 'published', published_at = now()
          WHERE id = $1`,
        [evaluation.id],
      );
      await client.query(
        `INSERT INTO bank_market_news (guild_id, stock_id, title, content, created_by)
         VALUES ($1, $2, $3, $4, $5)`,
        [
          guildId,
          evaluation.stock_id,
          `${evaluation.name} 일일 시세`,
          `기준가 ${evaluation.old_price} → ${evaluation.new_price} (${evaluation.change_percent >= 0 ? "+" : ""}${evaluation.change_percent}%)\n세부 점수: 콘텐츠 ${evaluation.content_score}, 활동 ${evaluation.activity_score}, 인원 ${evaluation.membership_score}, 주요 사건 ${evaluation.events_score}, 성장 ${evaluation.growth_score}, 영향력 ${evaluation.influence_score}, 여론 ${evaluation.opinion_score}\n기본 ${evaluation.base_score}점 + 무작위 ${evaluation.random_score >= 0 ? "+" : ""}${evaluation.random_score}점 = 최종 ${evaluation.final_score}점.\n근거: ${evaluation.evidence}`,
          "system",
        ],
      );
      reports.push(evaluation);
    }
    if (!stockName) {
      await client.query(
        `INSERT INTO bank_market_cycles (guild_id, cycle_date, stage)
         VALUES ($1, $2, 'publish') ON CONFLICT DO NOTHING`,
        [guildId, date],
      );
    }
    return reports;
  });
}

export async function setAnnouncementChannel(
  guildId: string,
  channelId: string,
) {
  await pool.query(
    `INSERT INTO bank_guild_settings (guild_id, announcement_channel_id)
     VALUES ($1, $2)
     ON CONFLICT (guild_id) DO UPDATE
       SET announcement_channel_id = EXCLUDED.announcement_channel_id`,
    [guildId, channelId],
  );
}

export async function getAnnouncementChannel(guildId: string) {
  const result = await pool.query<{ announcement_channel_id: string | null }>(
    `SELECT announcement_channel_id FROM bank_guild_settings WHERE guild_id = $1`,
    [guildId],
  );
  return result.rows[0]?.announcement_channel_id ?? null;
}

export async function addMarketNews(
  guildId: string,
  authorId: string,
  title: string,
  content: string,
  stockName?: string,
) {
  const stock = stockName
    ? await findStock(guildId, stockName)
    : null;
  await pool.query(
    `INSERT INTO bank_market_news (guild_id, stock_id, title, content, created_by)
     VALUES ($1, $2, $3, $4, $5)`,
    [guildId, stock?.id ?? null, title, content, authorId],
  );
  return { stockName: stock?.name ?? null };
}

export async function recentNews(guildId: string) {
  const result = await pool.query(
    `SELECT n.title, n.content, n.created_at, s.name AS stock_name
       FROM bank_market_news n
       LEFT JOIN bank_stocks s ON s.id = n.stock_id
      WHERE n.guild_id = $1
      ORDER BY n.created_at DESC LIMIT 8`,
    [guildId],
  );
  return result.rows;
}

export async function addOfficer(
  guildId: string,
  stockName: string,
  discordUserId: string,
) {
  return inTransaction(async (client) => {
    const stock = await findStock(guildId, stockName, client, true);
    const existing = await client.query<{ count: string }>(
      `SELECT COUNT(*)::text AS count FROM bank_stock_officers WHERE stock_id = $1`,
      [stock.id],
    );
    const already = await client.query(
      `SELECT 1 FROM bank_stock_officers WHERE stock_id = $1 AND discord_user_id = $2`,
      [stock.id, discordUserId],
    );
    if (!already.rowCount && Number(existing.rows[0].count) >= 2) {
      throw new Error("종목별 지정 관계자는 최대 2명입니다.");
    }
    await client.query(
      `INSERT INTO bank_stock_officers (stock_id, discord_user_id)
       VALUES ($1, $2) ON CONFLICT (stock_id, discord_user_id) DO NOTHING`,
      [stock.id, discordUserId],
    );
    return stock;
  });
}

export async function removeOfficer(
  guildId: string,
  stockName: string,
  discordUserId: string,
) {
  const stock = await findStock(guildId, stockName);
  await pool.query(
    `DELETE FROM bank_stock_officers WHERE stock_id = $1 AND discord_user_id = $2`,
    [stock.id, discordUserId],
  );
  return stock;
}

export async function runMarketScheduler(guildIds: string[], date: string, minute: number) {
  const messages: { guildId: string; stage: "close" | "publish" | "interest"; count: number }[] = [];
  for (const guildId of guildIds) {
    if (minute >= 1230 && minute < 1260) {
      const count = await cancelMarketOrders(guildId, date);
      messages.push({ guildId, stage: "close", count });
    }
    if (minute >= 1260 && minute < 1320) {
      const hasRun = await pool.query(
        `SELECT 1 FROM bank_market_cycles WHERE guild_id = $1 AND cycle_date = $2 AND stage = 'publish' LIMIT 1`,
        [guildId, date],
      );
      if (!hasRun.rowCount) {
        try {
          const reports = await publishEvaluations(guildId, date);
          messages.push({ guildId, stage: "publish", count: reports.length });
        } catch (error) {
          if (!(error instanceof Error) || !error.message.includes("미게시 평가")) {
            throw error;
          }
          await pool.query(
            `INSERT INTO bank_market_cycles (guild_id, cycle_date, stage)
             VALUES ($1, $2, 'publish') ON CONFLICT DO NOTHING`,
            [guildId, date],
          );
        }
      }
    }
    if (minute < 30) {
      const hasRun = await pool.query(
        `SELECT 1 FROM bank_interest_runs WHERE guild_id = $1 AND run_date = $2 LIMIT 1`,
        [guildId, date],
      );
      if (!hasRun.rowCount) {
        const accrued = await accrueInterest(guildId, date);
        if (accrued) messages.push({ guildId, stage: "interest", count: 1 });
      }
    }
  }
  return messages;
}
