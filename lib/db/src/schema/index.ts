import {
  boolean,
  index,
  integer,
  jsonb,
  numeric,
  pgTable,
  serial,
  text,
  timestamp,
  uniqueIndex,
} from "drizzle-orm/pg-core";
import { sql } from "drizzle-orm";

const createdAt = () =>
  timestamp("created_at", { withTimezone: true }).notNull().defaultNow();

export const accounts = pgTable(
  "bank_accounts",
  {
    id: serial("id").primaryKey(),
    guildId: text("guild_id").notNull(),
    discordUserId: text("discord_user_id").notNull(),
    frozen: boolean("frozen").notNull().default(false),
    tierKey: text("tier_key").notNull().default("bronze"),
    creditScore: integer("credit_score").notNull().default(50),
    createdAt: createdAt(),
  },
  (table) => [
    uniqueIndex("bank_accounts_guild_user_uq").on(
      table.guildId,
      table.discordUserId,
    ),
  ],
);

export const currencies = pgTable(
  "bank_currencies",
  {
    id: serial("id").primaryKey(),
    guildId: text("guild_id").notNull(),
    name: text("name").notNull(),
    symbol: text("symbol").notNull(),
    exchangeValue: numeric("exchange_value", {
      precision: 18,
      scale: 6,
    })
      .notNull()
      .default("1"),
    depositRate: numeric("deposit_rate", { precision: 8, scale: 4 })
      .notNull()
      .default("0"),
    loanRate: numeric("loan_rate", { precision: 8, scale: 4 })
      .notNull()
      .default("0"),
    isBase: boolean("is_base").notNull().default(false),
    active: boolean("active").notNull().default(true),
    createdAt: createdAt(),
  },
  (table) => [
    uniqueIndex("bank_currencies_guild_name_uq").on(
      table.guildId,
      table.name,
    ),
    index("bank_currencies_guild_active_idx").on(table.guildId, table.active),
  ],
);

export const balances = pgTable(
  "bank_balances",
  {
    id: serial("id").primaryKey(),
    accountId: integer("account_id")
      .notNull()
      .references(() => accounts.id),
    currencyId: integer("currency_id")
      .notNull()
      .references(() => currencies.id),
    wallet: numeric("wallet", { precision: 24, scale: 0 })
      .notNull()
      .default("0"),
    deposit: numeric("deposit", { precision: 24, scale: 0 })
      .notNull()
      .default("0"),
  },
  (table) => [
    uniqueIndex("bank_balances_account_currency_uq").on(
      table.accountId,
      table.currencyId,
    ),
    index("bank_balances_currency_idx").on(table.currencyId),
  ],
);

export const transactions = pgTable(
  "bank_transactions",
  {
    id: serial("id").primaryKey(),
    guildId: text("guild_id").notNull(),
    type: text("type").notNull(),
    actorAccountId: integer("actor_account_id").references(() => accounts.id),
    targetAccountId: integer("target_account_id").references(() => accounts.id),
    currencyId: integer("currency_id")
      .notNull()
      .references(() => currencies.id),
    amount: numeric("amount", { precision: 24, scale: 0 }).notNull(),
    fee: numeric("fee", { precision: 24, scale: 0 }).notNull().default("0"),
    description: text("description").notNull().default(""),
    metadata: jsonb("metadata").notNull().default({}),
    createdAt: createdAt(),
  },
  (table) => [
    index("bank_transactions_guild_created_idx").on(
      table.guildId,
      table.createdAt,
    ),
    index("bank_transactions_actor_idx").on(table.actorAccountId),
    index("bank_transactions_target_idx").on(table.targetAccountId),
  ],
);

export const loans = pgTable(
  "bank_loans",
  {
    id: serial("id").primaryKey(),
    guildId: text("guild_id").notNull(),
    accountId: integer("account_id")
      .notNull()
      .references(() => accounts.id),
    currencyId: integer("currency_id")
      .notNull()
      .references(() => currencies.id),
    principal: numeric("principal", { precision: 24, scale: 0 }).notNull(),
    amountDue: numeric("amount_due", { precision: 24, scale: 0 }).notNull(),
    rate: numeric("rate", { precision: 8, scale: 4 }).notNull(),
    status: text("status").notNull().default("pending"),
    loanType: text("loan_type").notNull().default("credit"),
    requestedTier: text("requested_tier").notNull().default("bronze"),
    collateralItem: text("collateral_item"),
    collateralQuantity: integer("collateral_quantity"),
    collateralValue: numeric("collateral_value", {
      precision: 24,
      scale: 0,
    }),
    collateralStatus: text("collateral_status").notNull().default("none"),
    dueAt: timestamp("due_at", { withTimezone: true }),
    extensionCount: integer("extension_count").notNull().default(0),
    createdAt: createdAt(),
    reviewedAt: timestamp("reviewed_at", { withTimezone: true }),
  },
  (table) => [
    index("bank_loans_account_status_idx").on(table.accountId, table.status),
    index("bank_loans_guild_idx").on(table.guildId),
  ],
);

export const tierSettings = pgTable("bank_tier_settings", {
  guildId: text("guild_id").primaryKey(),
  platinumLoanBonus: numeric("platinum_loan_bonus", {
    precision: 24,
    scale: 0,
  })
    .notNull()
    .default("0"),
  vipDepositRateBonus: numeric("vip_deposit_rate_bonus", {
    precision: 8,
    scale: 4,
  })
    .notNull()
    .default("0"),
  bronzeStorageLimit: integer("bronze_storage_limit").notNull().default(0),
  silverStorageLimit: integer("silver_storage_limit").notNull().default(0),
  goldStorageLimit: integer("gold_storage_limit").notNull().default(0),
  platinumStorageLimit: integer("platinum_storage_limit").notNull().default(0),
  aceStorageLimit: integer("ace_storage_limit").notNull().default(0),
  vipStorageLimit: integer("vip_storage_limit").notNull().default(0),
  loanTermDays: integer("loan_term_days").notNull().default(0),
  loanExtensionDays: integer("loan_extension_days").notNull().default(0),
  loanExtensionLimit: integer("loan_extension_limit").notNull().default(0),
  updatedAt: createdAt(),
});

export const creditScoreHistory = pgTable(
  "bank_credit_score_history",
  {
    id: serial("id").primaryKey(),
    guildId: text("guild_id").notNull(),
    actorDiscordUserId: text("actor_discord_user_id").notNull(),
    targetDiscordUserId: text("target_discord_user_id").notNull(),
    oldScore: integer("old_score").notNull(),
    newScore: integer("new_score").notNull(),
    reason: text("reason").notNull(),
    createdAt: createdAt(),
  },
  (table) => [
    index("bank_credit_score_history_guild_created_idx").on(
      table.guildId,
      table.createdAt,
    ),
    index("bank_credit_score_history_target_idx").on(
      table.guildId,
      table.targetDiscordUserId,
    ),
  ],
);

export const tierSettingHistory = pgTable(
  "bank_tier_setting_history",
  {
    id: serial("id").primaryKey(),
    guildId: text("guild_id").notNull(),
    actorDiscordUserId: text("actor_discord_user_id").notNull(),
    settingKey: text("setting_key").notNull(),
    oldValue: text("old_value").notNull(),
    newValue: text("new_value").notNull(),
    reason: text("reason").notNull(),
    createdAt: createdAt(),
  },
  (table) => [
    index("bank_tier_setting_history_guild_created_idx").on(
      table.guildId,
      table.createdAt,
    ),
  ],
);

export const vaultItems = pgTable(
  "bank_vault_items",
  {
    id: serial("id").primaryKey(),
    accountId: integer("account_id")
      .notNull()
      .references(() => accounts.id),
    itemKey: text("item_key").notNull(),
    itemName: text("item_name").notNull(),
    quantity: integer("quantity").notNull().default(0),
    updatedAt: createdAt(),
  },
  (table) => [
    uniqueIndex("bank_vault_items_account_key_uq").on(
      table.accountId,
      table.itemKey,
    ),
    index("bank_vault_items_account_idx").on(table.accountId),
  ],
);

export const vaultHistory = pgTable(
  "bank_vault_history",
  {
    id: serial("id").primaryKey(),
    guildId: text("guild_id").notNull(),
    actorDiscordUserId: text("actor_discord_user_id").notNull(),
    targetDiscordUserId: text("target_discord_user_id").notNull(),
    itemName: text("item_name").notNull(),
    quantity: integer("quantity").notNull(),
    operation: text("operation").notNull(),
    reason: text("reason").notNull(),
    createdAt: createdAt(),
  },
  (table) => [
    index("bank_vault_history_guild_created_idx").on(
      table.guildId,
      table.createdAt,
    ),
    index("bank_vault_history_target_idx").on(
      table.guildId,
      table.targetDiscordUserId,
    ),
  ],
);

export const loanExtensions = pgTable(
  "bank_loan_extensions",
  {
    id: serial("id").primaryKey(),
    loanId: integer("loan_id")
      .notNull()
      .references(() => loans.id),
    discordUserId: text("discord_user_id").notNull(),
    days: integer("days").notNull(),
    oldDueAt: timestamp("old_due_at", { withTimezone: true }).notNull(),
    newDueAt: timestamp("new_due_at", { withTimezone: true }).notNull(),
    createdAt: createdAt(),
  },
  (table) => [
    index("bank_loan_extensions_loan_idx").on(table.loanId, table.createdAt),
  ],
);

export const bankItemRequests = pgTable(
  "bank_item_requests",
  {
    id: serial("id").primaryKey(),
    guildId: text("guild_id").notNull(),
    discordUserId: text("discord_user_id").notNull(),
    itemName: text("item_name").notNull(),
    quantity: integer("quantity").notNull(),
    note: text("note").notNull().default(""),
    status: text("status").notNull().default("pending"),
    reviewNote: text("review_note").notNull().default(""),
    reviewedBy: text("reviewed_by"),
    reviewedAt: timestamp("reviewed_at", { withTimezone: true }),
    createdAt: createdAt(),
  },
  (table) => [
    index("bank_item_requests_guild_status_created_idx").on(
      table.guildId,
      table.status,
      table.createdAt,
    ),
    index("bank_item_requests_user_idx").on(
      table.guildId,
      table.discordUserId,
      table.createdAt,
    ),
  ],
);

export const stocks = pgTable(
  "bank_stocks",
  {
    id: serial("id").primaryKey(),
    guildId: text("guild_id").notNull(),
    name: text("name").notNull(),
    description: text("description").notNull().default(""),
    currentPrice: integer("current_price").notNull(),
    totalShares: integer("total_shares").notNull().default(0),
    listed: boolean("listed").notNull().default(true),
    createdAt: createdAt(),
  },
  (table) => [
    uniqueIndex("bank_stocks_guild_name_uq").on(
      table.guildId,
      sql`lower(trim(${table.name}))`,
    ),
    index("bank_stocks_guild_listed_idx").on(table.guildId, table.listed),
  ],
);

export const stockHoldings = pgTable(
  "bank_stock_holdings",
  {
    id: serial("id").primaryKey(),
    stockId: integer("stock_id")
      .notNull()
      .references(() => stocks.id),
    accountId: integer("account_id")
      .notNull()
      .references(() => accounts.id),
    shares: integer("shares").notNull().default(0),
  },
  (table) => [
    uniqueIndex("bank_stock_holdings_stock_account_uq").on(
      table.stockId,
      table.accountId,
    ),
    index("bank_stock_holdings_account_idx").on(table.accountId),
  ],
);

export const stockOrders = pgTable(
  "bank_stock_orders",
  {
    id: serial("id").primaryKey(),
    guildId: text("guild_id").notNull(),
    stockId: integer("stock_id")
      .notNull()
      .references(() => stocks.id),
    accountId: integer("account_id")
      .notNull()
      .references(() => accounts.id),
    side: text("side").notNull(),
    limitPrice: integer("limit_price").notNull(),
    quantity: integer("quantity").notNull(),
    remaining: integer("remaining").notNull(),
    status: text("status").notNull().default("open"),
    createdAt: createdAt(),
  },
  (table) => [
    index("bank_stock_orders_book_idx").on(
      table.stockId,
      table.side,
      table.status,
      table.limitPrice,
      table.createdAt,
    ),
    index("bank_stock_orders_account_idx").on(
      table.accountId,
      table.status,
    ),
  ],
);

export const stockTrades = pgTable(
  "bank_stock_trades",
  {
    id: serial("id").primaryKey(),
    guildId: text("guild_id").notNull(),
    stockId: integer("stock_id")
      .notNull()
      .references(() => stocks.id),
    buyerAccountId: integer("buyer_account_id")
      .notNull()
      .references(() => accounts.id),
    sellerAccountId: integer("seller_account_id")
      .notNull()
      .references(() => accounts.id),
    currencyId: integer("currency_id")
      .notNull()
      .references(() => currencies.id),
    shares: integer("shares").notNull(),
    executionPrice: integer("execution_price").notNull(),
    grossAmount: numeric("gross_amount", { precision: 24, scale: 0 }).notNull(),
    fee: numeric("fee", { precision: 24, scale: 0 }).notNull(),
    createdAt: createdAt(),
  },
  (table) => [
    index("bank_stock_trades_stock_created_idx").on(
      table.stockId,
      table.createdAt,
    ),
    index("bank_stock_trades_buyer_idx").on(table.buyerAccountId),
    index("bank_stock_trades_seller_idx").on(table.sellerAccountId),
  ],
);

export const stockOfficers = pgTable(
  "bank_stock_officers",
  {
    id: serial("id").primaryKey(),
    stockId: integer("stock_id")
      .notNull()
      .references(() => stocks.id),
    discordUserId: text("discord_user_id").notNull(),
    createdAt: createdAt(),
  },
  (table) => [
    uniqueIndex("bank_stock_officers_stock_user_uq").on(
      table.stockId,
      table.discordUserId,
    ),
    index("bank_stock_officers_stock_idx").on(table.stockId),
  ],
);

export const evaluations = pgTable(
  "bank_stock_evaluations",
  {
    id: serial("id").primaryKey(),
    guildId: text("guild_id").notNull(),
    stockId: integer("stock_id")
      .notNull()
      .references(() => stocks.id),
    evaluationDate: text("evaluation_date").notNull(),
    contentScore: integer("content_score").notNull(),
    activityScore: integer("activity_score").notNull(),
    membershipScore: integer("membership_score").notNull(),
    eventsScore: integer("events_score").notNull(),
    growthScore: integer("growth_score").notNull(),
    influenceScore: integer("influence_score").notNull(),
    opinionScore: integer("opinion_score").notNull(),
    baseScore: integer("base_score").notNull(),
    randomScore: integer("random_score").notNull(),
    finalScore: integer("final_score").notNull(),
    changePercent: integer("change_percent").notNull(),
    oldPrice: integer("old_price").notNull(),
    newPrice: integer("new_price").notNull(),
    evidence: text("evidence").notNull(),
    status: text("status").notNull().default("pending"),
    createdBy: text("created_by").notNull(),
    createdAt: createdAt(),
    publishedAt: timestamp("published_at", { withTimezone: true }),
  },
  (table) => [
    uniqueIndex("bank_stock_evaluations_stock_date_uq").on(
      table.stockId,
      table.evaluationDate,
    ),
    index("bank_stock_evaluations_guild_date_idx").on(
      table.guildId,
      table.evaluationDate,
    ),
  ],
);

export const marketNews = pgTable(
  "bank_market_news",
  {
    id: serial("id").primaryKey(),
    guildId: text("guild_id").notNull(),
    stockId: integer("stock_id").references(() => stocks.id),
    title: text("title").notNull(),
    content: text("content").notNull(),
    createdBy: text("created_by").notNull(),
    createdAt: createdAt(),
  },
  (table) => [
    index("bank_market_news_guild_created_idx").on(
      table.guildId,
      table.createdAt,
    ),
  ],
);

export const guildSettings = pgTable("bank_guild_settings", {
  guildId: text("guild_id").primaryKey(),
  announcementChannelId: text("announcement_channel_id"),
});

export const userPreferences = pgTable("bank_user_preferences", {
  discordUserId: text("discord_user_id").primaryKey(),
  language: text("language").notNull().default("ko"),
  createdAt: createdAt(),
});

export const marketCycles = pgTable(
  "bank_market_cycles",
  {
    id: serial("id").primaryKey(),
    guildId: text("guild_id").notNull(),
    cycleDate: text("cycle_date").notNull(),
    stage: text("stage").notNull(),
    createdAt: createdAt(),
  },
  (table) => [
    uniqueIndex("bank_market_cycles_guild_date_stage_uq").on(
      table.guildId,
      table.cycleDate,
      table.stage,
    ),
  ],
);

export const interestRuns = pgTable(
  "bank_interest_runs",
  {
    id: serial("id").primaryKey(),
    guildId: text("guild_id").notNull(),
    runDate: text("run_date").notNull(),
    createdAt: createdAt(),
  },
  (table) => [
    uniqueIndex("bank_interest_runs_guild_date_uq").on(
      table.guildId,
      table.runDate,
    ),
  ],
);
