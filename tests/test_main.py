import unittest

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

    def test_slash_command_groups_include_stock_table_and_admin_rumor(self):
        commands = {
            command.name: command.to_dict(main.bot.tree)
            for command in main.bot.tree.get_commands()
        }
        market_commands = {option["name"] for option in commands["market"]["options"]}
        stock_commands = {option["name"] for option in commands["stock"]["options"]}
        self.assertIn("rumor", market_commands)
        self.assertIn("table", stock_commands)


if __name__ == "__main__":
    unittest.main()
