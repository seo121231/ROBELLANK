import unittest
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import main
from localization import translate_message


class FakeConnection:
    def __init__(self):
        self.language = None
        self.execute_args = None

    async def fetchval(self, query, user_id):
        self.fetch_user_id = user_id
        return self.language

    async def execute(self, query, user_id, language):
        self.execute_args = (user_id, language)
        self.language = language


class FakeAcquire:
    def __init__(self, connection):
        self.connection = connection

    async def __aenter__(self):
        return self.connection

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakePool:
    def __init__(self):
        self.connection = FakeConnection()

    def acquire(self):
        return FakeAcquire(self.connection)


class BankBotHelpersTest(unittest.IsolatedAsyncioTestCase):
    def test_normalizes_stock_names_without_tickers(self):
        self.assertEqual(main.normalize_name("  Café   Market "), "café   market")

    def test_tier_thresholds_follow_role_order(self):
        self.assertTrue(main.tier_at_least("silver", "bronze"))
        self.assertTrue(main.tier_at_least("vip", "ace"))
        self.assertFalse(main.tier_at_least("gold", "platinum"))
        self.assertFalse(main.tier_at_least("unknown", "silver"))

    def test_evaluation_score_ranges(self):
        self.assertEqual(main.evaluation_change_range(0), (0, 0))
        self.assertEqual(main.evaluation_change_range(5), (1, 2))
        self.assertEqual(main.evaluation_change_range(-5), (-2, -1))
        self.assertEqual(main.evaluation_change_range(50), (18, 20))
        self.assertEqual(main.evaluation_change_range(-50), (-20, -18))
        with self.assertRaises(ValueError):
            main.evaluation_change_range(51)

    def test_unscored_market_changes_allow_both_ten_percent_bounds(self):
        with patch("main.random.randint", side_effect=[-10, 10]) as choose_change:
            self.assertEqual(main.unscored_market_change(), -10)
            self.assertEqual(main.unscored_market_change(), 10)

        self.assertEqual(choose_change.call_args_list[0].args, (-10, 10))
        self.assertEqual(choose_change.call_args_list[1].args, (-10, 10))
        self.assertEqual(main.market_price_after_change(1_000, -10), 900)
        self.assertEqual(main.market_price_after_change(1_000, 10), 1_100)
        self.assertEqual(main.market_price_after_change(1, -10), 1)

    def test_unscored_market_rows_are_labeled_as_random_movements(self):
        row = {
            "created_by": "system",
            "evidence": main.UNSCORED_MARKET_EVIDENCE,
            "name": "테스트 종목",
            "old_price": 1_000,
            "new_price": 1_050,
            "change_percent": 5,
            "final_score": 0,
        }
        self.assertTrue(main.is_unscored_market_evaluation(row))
        self.assertIn("점수 미등록 · 무작위 변동", main.market_report_line(row))

    def test_slash_command_groups_include_stock_table_and_admin_rumor(self):
        commands = {
            command.name: command.to_dict(main.bot.tree)
            for command in main.bot.tree.get_commands()
        }
        market_commands = {option["name"] for option in commands["market"]["options"]}
        stock_commands = {option["name"] for option in commands["stock"]["options"]}
        self.assertIn("rumor", market_commands)
        self.assertIn("table", stock_commands)

    def test_language_and_menu_commands_are_registered(self):
        language = main.bot.tree.get_command("language")
        menu = main.bot.tree.get_command("menu")

        self.assertIsNotNone(language)
        self.assertIsNotNone(menu)
        language_option = language.to_dict(main.bot.tree)["options"][0]
        self.assertEqual(
            {choice["value"] for choice in language_option["choices"]},
            {"ko", "en"},
        )

    def test_menu_has_public_navigation_and_language_buttons(self):
        view = main.BankMenuView(123456, "en")

        self.assertEqual(
            [button.label for button in view.children],
            ["Menu", "Help", "Stocks", "Language: English"],
        )

    def test_account_card_uses_gold_embed_and_groups_each_currency(self):
        user = SimpleNamespace(
            display_name="Slayer",
            display_avatar=SimpleNamespace(url="https://example.com/avatar.png"),
        )
        rows = [
            {
                "name": "bell",
                "symbol": "B",
                "is_base": True,
                "wallet": 588_000,
                "deposit": 28_000,
            },
            {
                "name": "branch",
                "symbol": "BR",
                "is_base": False,
                "wallet": 803,
                "deposit": 0,
            },
        ]

        embed = main.build_account_embed(user, rows, False, "en")

        self.assertEqual(embed.color.value, main.BANK_GOLD)
        self.assertEqual(embed.title, "Slayer's Account")
        self.assertEqual(embed.thumbnail.url, "https://example.com/avatar.png")
        self.assertEqual(len(embed.fields), 2)
        self.assertIn("Wallet", embed.fields[0].value)
        self.assertIn("588,000 B", embed.fields[0].value)
        self.assertIn("Savings", embed.fields[0].value)
        self.assertIn("28,000 B", embed.fields[0].value)
        self.assertIn("803 BR", embed.fields[1].value)
        self.assertFalse(embed.fields[0].inline)

    def test_account_card_stays_within_discord_embed_limits(self):
        user = SimpleNamespace(
            display_name="Slayer",
            display_avatar=SimpleNamespace(url="https://example.com/avatar.png"),
        )
        rows = [
            {
                "name": f"currency-{index}-" + "n" * 500,
                "symbol": "S" * 500,
                "is_base": index == 0,
                "wallet": 2_147_483_647,
                "deposit": 2_147_483_647,
            }
            for index in range(26)
        ]

        embed = main.build_account_embed(user, rows, False, "en")

        self.assertEqual(len(embed.fields), 25)
        self.assertLessEqual(len(embed.fields[0].name), 256)
        self.assertLessEqual(len(embed.fields[0].value), 1024)
        self.assertLessEqual(len(embed), 6000)
        self.assertIn("2 more currencies omitted", embed.fields[-1].value)

    def test_english_market_report_translates_system_generated_evidence(self):
        message = (
            "오늘 가상주식 시세 발표\n"
            "**종목 A** · 1,000 → 1,100 (+10%) · 점수 미등록 · 무작위 변동\n"
            "점수 미등록 종목에 하루 -10%~+10% 무작위 변동을 적용했습니다."
        )

        translated = translate_message(message, "en")

        self.assertIn("Today's virtual stock prices", translated)
        self.assertIn("Unscored · random movement", translated)
        self.assertIn("A random daily price movement of -10% to +10%", translated)

    def test_single_row_account_summaries_translate_without_newlines(self):
        loan = translate_message(
            "#12 신용 · 원금 100 · 남은 원리금 105 · 일 1% · pending",
            "en",
        )
        currency = translate_message(
            "**벨** (BELL) · 환전가치 1 · 기본재화 · 일 예금 0% · 일 대출 0%",
            "en",
        )

        self.assertIn("Credit · principal 100 · remaining balance 105", loan)
        self.assertIn("exchange value 1 · base currency · daily deposit 0%", currency)

    def test_english_admin_confirmation_results_preserve_reason_and_amount(self):
        result = translate_message(
            "지급 완료: <@123456> · 1,000 BELL · 사유: verified",
            "en",
        )

        self.assertEqual(
            result,
            "Granted 1,000 BELL for <@123456>. Reason: verified",
        )

    def test_language_setting_translates_known_messages_and_keeps_korean(self):
        original = "계좌가 없습니다. 먼저 /register를 사용하세요."
        self.assertEqual(
            translate_message(original, "en"),
            "You do not have an account. Run /register first.",
        )
        self.assertEqual(translate_message(original, "ko"), original)

    def test_unknown_english_response_is_not_silently_left_in_korean(self):
        translated = translate_message("이 문구에는 아직 번역이 없습니다.", "en")
        self.assertTrue(translated.startswith("English translation unavailable"))
        self.assertIn("이 문구에는 아직 번역이 없습니다.", translated)

    async def test_language_preference_is_saved_per_discord_user(self):
        pool = FakePool()

        with patch.object(main, "pool", pool, create=True):
            await main.set_user_language(123456, "en")
            language = await main.get_user_language(123456)

        self.assertEqual(language, "en")
        self.assertEqual(pool.connection.execute_args, ("123456", "en"))
        self.assertEqual(pool.connection.fetch_user_id, "123456")

    def test_bot_does_not_send_ephemeral_interaction_messages(self):
        source = ast.parse(Path(main.__file__).read_text())
        ephemeral_true_calls = []
        for node in ast.walk(source):
            if not isinstance(node, ast.Call):
                continue
            if not isinstance(node.func, ast.Attribute):
                continue
            if node.func.attr not in {"send_message", "send"}:
                continue
            for keyword in node.keywords:
                if (
                    keyword.arg == "ephemeral"
                    and isinstance(keyword.value, ast.Constant)
                    and keyword.value.value is True
                ):
                    ephemeral_true_calls.append(node.lineno)

        self.assertEqual(ephemeral_true_calls, [])

    def test_market_channel_uses_text_autocomplete_and_is_admin_only(self):
        market_group = main.bot.tree.get_command("market")
        channel_command = market_group.get_command("channel")
        channel_option = next(
            option
            for option in channel_command.to_dict(main.bot.tree)["options"]
            if option["name"] == "channel"
        )

        self.assertEqual(channel_option["type"], 3)
        self.assertTrue(channel_option["autocomplete"])
        self.assertTrue(
            channel_command.description.startswith(main.ADMIN_DESCRIPTION_PREFIX)
        )
        self.assertEqual(len(channel_command.checks), 1)

    def test_admin_commands_are_labeled_and_restricted_in_discord(self):
        mint = main.bot.tree.get_command("mint")
        credit = main.bot.tree.get_command("credit")
        credit_adjust = credit.get_command("adjust")

        self.assertTrue(mint.description.startswith(main.ADMIN_DESCRIPTION_PREFIX))
        self.assertTrue(mint.default_permissions.administrator)
        self.assertTrue(credit.default_permissions.administrator)
        self.assertTrue(
            credit_adjust.description.startswith(main.ADMIN_DESCRIPTION_PREFIX)
        )


if __name__ == "__main__":
    unittest.main()
