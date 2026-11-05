import unittest
from unittest.mock import patch

import main


class BankBotHelpersTest(unittest.TestCase):
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
