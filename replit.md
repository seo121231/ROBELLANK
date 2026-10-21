# ROBELLANK 은행 봇

Discord 서버에서 가상 통화·계좌와 길드 가상주식 시장을 운영하는 한국어 슬래시 명령 봇입니다.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the API server (port 8080)
- `pnpm --filter @workspace/robellank-bankbot run dev` — run the ROBELLANK Discord bank bot
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required env: `DATABASE_URL` — Postgres connection string

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: Express 5
- DB: PostgreSQL + Drizzle ORM
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)

## Where things live

- `artifacts/robellank-bankbot` — Discord slash commands, interaction handlers, bank and market operations, and Korean command guide
- `lib/db/src/schema/index.ts` — PostgreSQL schema for accounts, currencies, transactions, loans, stocks, orders, evaluations, and news
- `artifacts/api-server` — shared API scaffold, separate from the Discord bot process

## Architecture decisions

- Discord gateway bot runs as a dedicated console workflow; it does not depend on the API server process.
- Market scores and user-entered evidence are stored separately from the trading ledger; unpublished evaluations can be corrected before publication.
- Buy order funds are escrowed; open orders are refunded when cancelled or at the daily market close.
- Guild stocks are found by unique display name rather than ticker; trades and holdings remain linked by immutable internal stock IDs, and stock listings carry a user-facing description.
- Discord tier roles are assigned manually by server administrators; the bot must never grant or change roles. New bank accounts start at 50 credit points.
- Game currency is verified by an administrator in-game and then issued to the bank through the confirmed `/mint` flow; users do not self-register currency balances.

## Product

- Server-scoped bank accounts, wallet/deposit balances, transfers, currency exchange, daily interest, approval-based loans, and transaction history.
- Guild stock listings tracked by name, detailed issuer descriptions and quotes, user-to-user limit orders, portfolios, 7.5% sell fees, daily score-based price changes, and market announcements.
- Administrator controls for currencies, account freezes, money supply, loans, listings, share issuance, scoring, and announcements.

## User preferences

- The bot's user-facing commands and messages should be in Korean.
- The investment system is a guild virtual-stock exchange based on the supplied ROBELLANK operating rules, not fixed-term investment products.

## Gotchas

- Currency rates and interest are defined as values per one unit of currency; interest accrues daily at 00:00 Asia/Seoul.
- Only Discord server administrators can use administrative bank and market commands.
- To deliver a user-to-user stock market, accounts need to be registered and initial shares need to be assigned to a holder who can place sell orders.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
