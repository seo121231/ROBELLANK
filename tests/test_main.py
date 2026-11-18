import unittest
import ast
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

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
    def test_discord_token_is_validated_before_startup(self):
        with patch.dict(
            os.environ,
            {
                "DISCORD_TOKEN": "  primary-test-token  ",
                "DISCORD_BOT_TOKEN": "secondary-test-token",
            },
        ):
            with self.assertLogs(main.logger, level="INFO") as captured:
                self.assertEqual(main.require_discord_token(), "primary-test-token")
            self.assertIn("DISCORD_TOKEN", captured.output[0])
            self.assertNotIn("primary-test-token", captured.output[0])

        with patch.dict(
            os.environ,
            {"DISCORD_TOKEN": "   ", "DISCORD_BOT_TOKEN": "  fallback-test-token  "},
        ):
            self.assertEqual(main.require_discord_token(), "fallback-test-token")

        with patch.dict(
            os.environ,
            {"DISCORD_TOKEN": "", "DISCORD_BOT_TOKEN": ""},
        ):
            with self.assertRaisesRegex(
                RuntimeError, "DISCORD_TOKEN or DISCORD_BOT_TOKEN is missing"
            ):
                main.require_discord_token()

    def test_discord_guild_id_is_optional_and_validated(self):
        with patch.dict(os.environ, {"DISCORD_GUILD_ID": ""}):
            self.assertIsNone(main.configured_discord_guild_id())

        with patch.dict(os.environ, {"DISCORD_GUILD_ID": "123456789012345678"}):
            self.assertEqual(
                main.configured_discord_guild_id(), 123456789012345678
            )

        for value in ("not-a-server-id", "0", "-12"):
            with self.subTest(value=value), patch.dict(
                os.environ, {"DISCORD_GUILD_ID": value}
            ):
                with self.assertRaises(RuntimeError):
                    main.configured_discord_guild_id()

    async def test_setup_clears_guild_command_copies_before_global_sync(self):
        class RecordingTree:
            def __init__(self):
                self.cleared_guild_ids = []
                self.synced_guild_ids = []

            async def set_translator(self, translator):
                self.translator = translator

            def clear_commands(self, *, guild=None):
                self.cleared_guild_ids.append(guild.id if guild else None)

            async def sync(self, *, guild=None):
                self.synced_guild_ids.append(guild.id if guild else None)
                return []

        bot = main.BankBot()
        tree = RecordingTree()
        bot.tree = tree

        with (
            patch.object(main, "DATABASE_URL", "postgres://test"),
            patch.object(main, "configured_discord_guild_id", return_value=123456789),
            patch.object(main.asyncpg, "create_pool", new=AsyncMock(return_value=object())),
        ):
            await bot.setup_hook()

        self.assertEqual(tree.cleared_guild_ids, [123456789])
        self.assertEqual(tree.synced_guild_ids, [123456789, None])

    def test_normalizes_stock_names_without_tickers(self):
        self.assertEqual(main.normalize_name("  Café   Market "), "café   market")

    def test_tier_thresholds_follow_role_order(self):
        self.assertTrue(main.tier_at_least("silver", "bronze"))
        self.assertTrue(main.tier_at_least("vip", "ace"))
        self.assertFalse(main.tier_at_least("gold", "platinum"))
        self.assertFalse(main.tier_at_least("unknown", "silver"))

    def test_credit_loan_limit_uses_two_thousand_bell_per_point(self):
        self.assertEqual(main.credit_loan_limit(50), 100_000)
        self.assertEqual(main.credit_loan_limit(100), 200_000)
        self.assertEqual(main.credit_loan_limit(50, 75_000), 175_000)

    def test_stock_sell_fee_is_eight_percent_rounded_to_nearest_bell(self):
        self.assertEqual(main.calculate_stock_sell_fee(10_000), 800)
        self.assertEqual(main.calculate_stock_sell_fee(6), 0)
        self.assertEqual(main.calculate_stock_sell_fee(7), 1)

    async def test_buy_and_sell_commands_share_stock_order_submission(self):
        interaction = SimpleNamespace(user=SimpleNamespace(id=123))
        order_result = {
            "stock": {"name": "테스트"},
            "order_id": 7,
            "filled": 2,
            "remaining": 3,
        }

        with (
            patch.object(main, "require_guild", return_value="guild"),
            patch.object(
                main, "place_order", new=AsyncMock(return_value=order_result)
            ) as place_order,
            patch.object(main, "send_private", new=AsyncMock()) as send_private,
        ):
            for side, action in (("buy", "매수"), ("sell", "매도")):
                with self.subTest(side=side):
                    await main._submit_stock_order(
                        interaction, "테스트", 5, 100, side
                    )

                    place_order.assert_awaited_with(
                        "guild", "123", "테스트", side, 5, 100
                    )
                    send_private.assert_awaited_with(
                        interaction,
                        f"**테스트** · {action} 주문 #7\n"
                        "5주 · 지정가 100 · 체결 2주 · 대기 3주",
                    )
                    place_order.reset_mock()
                    send_private.reset_mock()

    def test_tier_detection_accepts_role_names_and_uses_highest_tier(self):
        member = SimpleNamespace(
            roles=[
                SimpleNamespace(id=900001, name="브론즈 등급"),
                SimpleNamespace(id=900002, name="⭐ Gold Tier"),
                SimpleNamespace(id=900003, name="VIP"),
            ]
        )

        self.assertEqual(main.tier_for(member), "vip")
        self.assertEqual(
            main.tier_for(SimpleNamespace(roles=[SimpleNamespace(id=900004, name="플래티넘")])),
            "platinum",
        )

    def test_bracketed_tier_tags_use_lowercase_except_uppercase_vip(self):
        member = SimpleNamespace(
            roles=[
                SimpleNamespace(id=900011, name="Member [bronze]"),
                SimpleNamespace(id=900012, name="Rank [silver]"),
                SimpleNamespace(id=900013, name="Tier [gold]"),
                SimpleNamespace(id=900014, name="[platinum]"),
                SimpleNamespace(id=900015, name="[ace]"),
            ]
        )
        uppercase_vip = SimpleNamespace(
            roles=[SimpleNamespace(id=900016, name="Special [VIP]")]
        )
        lowercase_vip_with_legacy_id = SimpleNamespace(
            roles=[
                SimpleNamespace(
                    id=int(main.TIER_ROLE["vip"]),
                    name="Special [vip]",
                )
            ]
        )

        self.assertEqual(main.tier_for(member), "ace")
        self.assertEqual(
            main.tier_for(
                SimpleNamespace(
                    roles=[SimpleNamespace(id=900017, name="[platinum]")]
                )
            ),
            "platinum",
        )
        self.assertEqual(main.tier_for(uppercase_vip), "vip")
        self.assertEqual(main.tier_for(lowercase_vip_with_legacy_id), "bronze")

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

    def test_eleven_english_slash_commands_are_registered(self):
        commands = {
            command.name: command.to_dict(main.bot.tree)
            for command in main.bot.tree.get_commands()
        }
        self.assertEqual(
            set(commands),
            {
                "menu",
                "language",
                "help",
                "profile",
                "storage",
                "requests",
                "savings",
                "loan",
                "stocks",
                "market",
                "admin",
            },
        )
        self.assertEqual(len(commands), 11)
        stock_commands = {
            command.name
            for command in main.ACTION_COMMANDS_BY_CATEGORY["stocks"]
        }
        self.assertIn("table", stock_commands)
        self.assertIn(
            "news",
            {command.name for command in main.ACTION_COMMANDS_BY_CATEGORY["market"]},
        )
        self.assertIn(
            "currencies",
            {command.name for command in main.ACTION_COMMANDS_BY_CATEGORY["savings"]},
        )
        groups = []
        for root in main.bot.tree.get_commands():
            if isinstance(root, main.app_commands.Group):
                groups.append(root)
                groups.extend(
                    command
                    for command in root.walk_commands()
                    if isinstance(command, main.app_commands.Group)
                )
        self.assertTrue(all(len(group.commands) <= 25 for group in groups))
        self.assertTrue(
            all(
                isinstance(main.bot.tree.get_command(name), main.app_commands.Group)
                for name, _ in main.COMMAND_CATEGORIES
            )
        )
        self.assertIsNotNone(main.get_command_by_path("stocks stock buy"))
        self.assertIsNotNone(main.get_command_by_path("admin market create"))
        self.assertIsNotNone(main.get_command_by_path("market news"))
        with self.assertRaisesRegex(ValueError, "Command path is not registered"):
            main.get_command_by_path("market create")

    def test_stock_creation_command_is_available_under_admin_market(self):
        command = main.ACTION_COMMANDS_BY_PATH.get("admin market create")

        self.assertIsNotNone(command)
        self.assertEqual(
            [parameter.name for parameter in command.parameters],
            ["name", "description", "price", "initial_shares", "holder", "reason"],
        )
        self.assertIn(command, main.ACTION_COMMANDS_BY_CATEGORY["admin"])

    def test_documented_core_features_have_registered_commands(self):
        required_paths = {
            "profile register",
            "profile balance",
            "profile history",
            "savings currencies",
            "savings transfer",
            "savings exchange",
            "savings deposit",
            "loan request",
            "loan repay",
            "admin loan approve",
            "storage vault list",
            "admin storage add",
            "requests submit",
            "admin requests update",
            "stocks stock list",
            "stocks stock quote",
            "stocks stock buy",
            "stocks stock sell",
            "stocks stock cancel",
            "stocks portfolio",
            "admin market create",
            "admin market evaluate",
            "admin market publish",
            "market news",
            "admin currency create",
            "admin currency setrate",
            "admin mint",
            "admin freeze",
            "admin supply",
        }

        self.assertTrue(required_paths.issubset(main.ACTION_COMMANDS_BY_PATH))

    def test_language_and_menu_commands_are_registered(self):
        menu = main.bot.tree.get_command("menu")
        language_selector = main.bot.tree.get_command("language")

        self.assertIsNotNone(menu)
        self.assertIsNotNone(language_selector)
        self.assertEqual(menu.parameters, [])
        self.assertEqual(len(language_selector.parameters), 1)
        self.assertEqual(
            {choice.value for choice in language_selector.parameters[0].choices},
            {"ko", "en"},
        )

    def test_menu_shows_broad_command_categories_as_text(self):
        embed = main.build_main_menu_embed("ko")

        self.assertIn("은행: `/profile` · `/savings` · `/loan`", embed.description)
        self.assertIn("아이템: `/storage` · `/requests`", embed.description)
        self.assertIn("관리자: `/admin`", embed.description)

    def test_direct_slash_commands_resolve_without_menu_shortcuts(self):
        paths = list(main.MENU_COMMAND_PATHS.values())
        paths.extend(
            [
                "savings transfer",
                "savings deposit",
                "savings exchange",
                "stocks stock buy",
                "stocks stock sell",
            ]
        )
        for path in paths:
            with self.subTest(path=path):
                self.assertIsNotNone(main.get_command_by_path(path).callback)

        for action, fields in main.BankActionModal.FORM_FIELDS.items():
            modal = main.BankActionModal(123456, action)
            self.assertEqual(set(modal.inputs), {field[0] for field in fields})
            self.assertLessEqual(len(modal.children), 5)
        evaluation = main.CommandActionModal(
            123456, main.get_command_by_path("admin market evaluate")
        )
        self.assertEqual(len(evaluation.children), 5)
        next_page = main.CommandActionModal(
            123456,
            main.get_command_by_path("admin market evaluate"),
            values={
                "stock": "Example",
                "content": 1,
                "activity": 1,
                "membership": 1,
                "events": 1,
            },
        )
        self.assertEqual(len(next_page.children), 4)
        adjustment = main.ACTION_COMMANDS_BY_PATH["admin credit adjust"]
        choice_view = main.ChoiceActionView(
            123456,
            adjustment,
            [parameter for parameter in adjustment.parameters if parameter.choices],
        )
        self.assertEqual(len(choice_view.children[0].options), 16)

    def test_every_exposed_action_has_a_callable_handler(self):
        self.assertGreater(len(main.ACTION_COMMANDS_BY_PATH), 0)
        for path, command in main.ACTION_COMMANDS_BY_PATH.items():
            with self.subTest(path=path):
                self.assertTrue(callable(command.callback))

    def test_member_target_actions_open_discord_user_selectors(self):
        target_commands = [
            command
            for command in main.ACTION_COMMANDS_BY_PATH.values()
            if any(
                parameter.type == main.discord.AppCommandOptionType.user
                for parameter in command.parameters
            )
        ]
        self.assertGreaterEqual(len(target_commands), 10)
        for command in target_commands:
            with self.subTest(path=command.qualified_name):
                view = main.MemberSelectView(
                    123456, command=command, language="ko"
                )
                self.assertIsInstance(view.children[0], main.discord.ui.UserSelect)

    async def test_member_selection_prefills_target_fields_before_forms(self):
        selected_member = SimpleNamespace(id=654321, display_name="Selected User")
        response = SimpleNamespace(send_modal=AsyncMock())
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=123456),
            response=response,
        )
        command = main.ACTION_COMMANDS_BY_PATH["admin freeze"]
        view = main.MemberSelectView(
            123456, command=command, language="ko"
        )

        await view.accept_member(interaction, selected_member)

        response.send_modal.assert_awaited_once()
        modal = response.send_modal.await_args.args[0]
        self.assertIsInstance(modal, main.CommandActionModal)
        self.assertIs(modal.values["user"], selected_member)
        self.assertEqual(set(modal.inputs), {"reason"})
        self.assertEqual(
            modal.inputs["reason"].to_component_dict()["label"],
            "사유",
        )

    async def test_transfer_uses_selected_member_instead_of_typed_username(self):
        selected_member = SimpleNamespace(id=654321, display_name="Selected User")
        response = SimpleNamespace(send_modal=AsyncMock())
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=123456),
            response=response,
        )
        view = main.MemberSelectView(
            123456,
            command=main.ACTION_COMMANDS_BY_PATH["savings transfer"],
            action="transfer",
            language="ko",
        )

        await view.accept_member(interaction, selected_member)

        modal = response.send_modal.await_args.args[0]
        self.assertIsInstance(modal, main.BankActionModal)
        self.assertIs(modal.initial_values["user"], selected_member)
        self.assertEqual(set(modal.inputs), {"currency", "amount"})

    def test_native_stock_command_descriptions_follow_the_saved_language(self):
        command = main.ACTION_COMMANDS_BY_PATH["admin market create"]

        self.assertRegex(main.localized_command_description(command, "ko"), r"[가-힣]")
        self.assertNotRegex(main.localized_command_description(command, "en"), r"[가-힣]")

    async def test_action_modal_parses_choices_and_enforces_numeric_ranges(self):
        evaluation = main.get_command_by_path("admin market evaluate")
        modal = main.CommandActionModal(123456, evaluation)
        score_parameter = next(
            parameter for parameter in evaluation.parameters if parameter.name == "content"
        )
        self.assertEqual(
            await modal.parse_value(SimpleNamespace(), score_parameter, "5"),
            5,
        )
        with self.assertRaises(ValueError):
            await modal.parse_value(SimpleNamespace(), score_parameter, "7")

        rumor = main.get_command_by_path("admin market rumor")
        kind_parameter = next(
            parameter for parameter in rumor.parameters if parameter.name == "kind"
        )
        choice = await modal.parse_value(
            SimpleNamespace(), kind_parameter, "Unverified rumor"
        )
        self.assertEqual(choice.value, "fake_information")

    async def test_admin_actions_allow_server_managers_and_admin_roles(self):
        command = main.ACTION_COMMANDS_BY_PATH["admin mint"]
        regular_user = SimpleNamespace(
            guild_permissions=SimpleNamespace(
                administrator=False, manage_guild=False
            ),
            roles=[],
        )
        admin_user = SimpleNamespace(
            guild_permissions=SimpleNamespace(
                administrator=True, manage_guild=False
            ),
            roles=[],
        )
        server_manager = SimpleNamespace(
            guild_permissions=SimpleNamespace(
                administrator=False, manage_guild=True
            ),
            roles=[],
        )
        admin_role_user = SimpleNamespace(
            guild_permissions=SimpleNamespace(
                administrator=False, manage_guild=False
            ),
            roles=[SimpleNamespace(id=900005, name="서버 관리자")],
        )

        with self.assertRaisesRegex(ValueError, "서버 관리자"):
            await main.require_action_permission(
                SimpleNamespace(user=regular_user), command
            )
        await main.require_action_permission(SimpleNamespace(user=admin_user), command)
        await main.require_action_permission(
            SimpleNamespace(user=server_manager), command
        )
        await main.require_action_permission(
            SimpleNamespace(user=admin_role_user), command
        )
        for allowed_user in (admin_user, server_manager, admin_role_user):
            self.assertTrue(
                await command.checks[0](SimpleNamespace(user=allowed_user))
            )
        self.assertFalse(
            await command.checks[0](SimpleNamespace(user=regular_user))
        )

    def test_help_lists_only_english_slash_commands(self):
        lines = main.build_help_embed("ko").description.splitlines()
        self.assertEqual(
            lines,
            [
                "/menu",
                "/language",
                "/profile",
                "/storage",
                "/requests",
                "/savings",
                "/loan",
                "/stocks",
                "/market",
                "/admin",
                "/help",
            ],
        )

    def test_registered_command_descriptions_and_choices_are_english(self):
        commands = [
            *main.bot.tree.get_commands(),
            *main.ACTION_COMMANDS_BY_PATH.values(),
        ]
        for command in commands:
            self.assertNotRegex(command.name, r"[가-힣]")
            self.assertNotRegex(command.description, r"[가-힣]")
            if isinstance(command, main.app_commands.Group):
                continue
            for parameter in command.parameters:
                self.assertNotRegex(parameter.name, r"[가-힣]")
                self.assertNotRegex(parameter.description, r"[가-힣]")
                for choice in parameter.choices:
                    self.assertNotRegex(choice.name, r"[가-힣]")

    async def test_discord_korean_locale_translates_command_and_option_descriptions(
        self,
    ):
        translator = main.BankCommandTranslator()
        group = main.bot.tree.get_command("profile")
        group_context = main.app_commands.TranslationContext(
            main.app_commands.TranslationContextLocation.group_description,
            group,
        )
        translated_group = await translator.translate(
            main.app_commands.locale_str(group.description),
            main.discord.Locale.korean,
            group_context,
        )

        self.assertEqual(
            translated_group,
            main.localized_command_description(group, "ko"),
        )
        self.assertRegex(translated_group, r"[가-힣]")
        self.assertIsNone(
            await translator.translate(
                main.app_commands.locale_str(group.description),
                main.discord.Locale.american_english,
                group_context,
            )
        )

        command = main.ACTION_COMMANDS_BY_PATH["savings transfer"]
        parameter = command.parameters[0]
        parameter_context = main.app_commands.TranslationContext(
            main.app_commands.TranslationContextLocation.parameter_description,
            parameter,
        )
        translated_parameter = await translator.translate(
            main.app_commands.locale_str(parameter.description),
            main.discord.Locale.korean,
            parameter_context,
        )

        self.assertEqual(
            translated_parameter,
            main.localized_parameter_description(command, parameter, "ko"),
        )
        self.assertRegex(translated_parameter, r"[가-힣]")

    def test_all_registered_command_and_parameter_korean_descriptions_exist(self):
        for path, descriptions in main.COMMAND_DESCRIPTION_COPIES.items():
            with self.subTest(command=path):
                self.assertRegex(descriptions["ko"], r"[가-힣]")

        for key, descriptions in main.COMMAND_PARAMETER_DESCRIPTION_COPIES.items():
            with self.subTest(parameter=key):
                self.assertRegex(descriptions["ko"], r"[가-힣]")

    def test_tier_benefits_use_one_command_and_select_menu(self):
        command = main.ACTION_COMMANDS_BY_PATH["admin tier-benefits"]
        credit = main.ACTION_COMMANDS_BY_PATH["admin credit set"].parent

        self.assertIsNotNone(command)
        self.assertFalse(isinstance(command, main.app_commands.Group))
        self.assertIn("admin credit set", main.ACTION_COMMANDS_BY_PATH)
        self.assertIn("admin credit adjust", main.ACTION_COMMANDS_BY_PATH)

        settings = {
            "platinum_loan_bonus": 100_000,
            "vip_deposit_rate_bonus": 1.5,
            "bronze_storage_limit": 0,
            "silver_storage_limit": 10,
            "gold_storage_limit": 20,
            "platinum_storage_limit": 30,
            "ace_storage_limit": 40,
            "vip_storage_limit": 50,
            "loan_term_days": 30,
            "loan_extension_days": 7,
            "loan_extension_limit": 2,
        }
        view = main.TierSettingsView(123456, "987654", settings)
        options = view.children[0].options
        self.assertEqual(len(options), 10)
        self.assertIn("loan_extension", {option.value for option in options})

    def test_tier_setting_values_are_validated(self):
        self.assertEqual(
            main.parse_tier_setting_value("vip_deposit_rate_bonus", "2.5"), 2.5
        )
        self.assertEqual(
            main.parse_tier_setting_value("gold_storage_limit", "500"), 500
        )
        for key, raw in (
            ("vip_deposit_rate_bonus", "101"),
            ("gold_storage_limit", "-1"),
            ("loan_term_days", "3651"),
            ("loan_extension_limit", "11"),
        ):
            with self.subTest(key=key, raw=raw):
                with self.assertRaises(ValueError):
                    main.parse_tier_setting_value(key, raw)

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
        self.assertNotIn("────────", embed.fields[0].value)
        self.assertNotIn("------", embed.fields[0].value)
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
        original = "계좌가 없습니다. 먼저 `/profile register`를 실행하세요."
        self.assertEqual(
            translate_message(original, "en"),
            "You do not have an account. Run `/profile register` first.",
        )
        self.assertEqual(translate_message(original, "ko"), original)

    def test_stock_order_summary_uses_concise_english_copy(self):
        message = (
            "**테스트** · 매수 주문 #7\n"
            "5주 · 지정가 100 · 체결 2주 · 대기 3주"
        )
        self.assertEqual(
            translate_message(message, "en"),
            "**테스트** · Buy order #7\n"
            "5 shares · limit 100 · filled 2 · open 3",
        )

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

    async def test_language_command_saves_the_selected_preference(self):
        pool = FakePool()
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=123456),
        )

        with (
            patch.object(main, "pool", pool, create=True),
            patch.object(main, "send_public", new=AsyncMock()) as send_public,
        ):
            await main.bot.tree.get_command("language").callback(
                interaction,
                main.app_commands.Choice(name="English", value="en"),
            )
            saved_language = await main.get_user_language(123456)

        self.assertEqual(saved_language, "en")
        send_public.assert_awaited_once_with(
            interaction, "Your bot language is now English.", language="en"
        )

    async def test_menu_command_keeps_category_guidance_text_only(self):
        interaction = SimpleNamespace(user=SimpleNamespace(id=123456))
        with (
            patch.object(main, "get_user_language", AsyncMock(return_value="ko")),
            patch.object(main, "send_public", new=AsyncMock()) as send_public,
        ):
            await main.bot.tree.get_command("menu").callback(interaction)

        send_public.assert_awaited_once()
        self.assertNotIn("view", send_public.await_args.kwargs)
        self.assertIn(
            "관리자: `/admin`",
            send_public.await_args.kwargs["embed"].description,
        )

    def test_category_menu_paginates_without_truncating_admin_actions(self):
        commands = main.ACTION_COMMANDS_BY_CATEGORY["admin"]
        page_count = (
            len(commands) + main.CATEGORY_PAGE_SIZE - 1
        ) // main.CATEGORY_PAGE_SIZE

        displayed_paths = []
        for page in range(page_count):
            embed = main.build_category_page_embed("admin", "ko", page)
            self.assertLessEqual(len(embed.description), main.MESSAGE_CHUNK_LIMIT)
            displayed_paths.extend(
                line.split(" — ", 1)[0].removeprefix("/")
                for line in embed.description.splitlines()
            )

        self.assertEqual(set(displayed_paths), {command.qualified_name for command in commands})
        admin_view = main.CategoryActionView(123456, "ko", "admin")
        self.assertTrue(any(isinstance(item, main.discord.ui.Button) for item in admin_view.children))
        self.assertEqual(
            len(admin_view.children[0].options),
            min(len(commands), main.CATEGORY_PAGE_SIZE),
        )

    async def test_all_public_command_replies_use_the_saved_language(self):
        pool = FakePool()
        response = SimpleNamespace(
            is_done=lambda: False,
            send_message=AsyncMock(),
        )
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=123456),
            response=response,
        )
        source = "계좌가 없습니다. 먼저 `/profile register`를 실행하세요."

        with patch.object(main, "pool", pool, create=True):
            await main.set_user_language(123456, "en")
            await main.send_public(interaction, source)

        message = response.send_message.await_args.kwargs
        self.assertNotIn("content", message)
        self.assertEqual(
            message["embed"].description,
            "You do not have an account. Run `/profile register` first.",
        )
        self.assertEqual(message["embed"].color.value, main.BANK_GOLD)

    async def test_send_public_does_not_pass_an_empty_view(self):
        pool = FakePool()
        response = SimpleNamespace(
            is_done=lambda: False,
            send_message=AsyncMock(),
        )
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=123456),
            response=response,
        )

        with patch.object(main, "pool", pool, create=True):
            await main.send_public(interaction, "정수를 입력하세요.")

        message_options = response.send_message.await_args.kwargs
        self.assertNotIn("content", message_options)
        self.assertEqual(message_options["embed"].description, "정수를 입력하세요.")
        self.assertEqual(message_options["embed"].color.value, main.BANK_GOLD)
        self.assertNotIn("view", message_options)
        self.assertFalse(message_options["ephemeral"])

    async def test_long_public_messages_are_split_without_dropping_text(self):
        text = ("긴 공지 문장을 충분히 반복합니다.\n" * 180).rstrip()
        response = SimpleNamespace(
            is_done=lambda: False,
            send_message=AsyncMock(),
        )
        followup = SimpleNamespace(send=AsyncMock())
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=123456),
            response=response,
            followup=followup,
        )

        await main.send_public(interaction, text, language="ko")

        sent_chunks = [
            response.send_message.await_args.kwargs["embed"].description,
            *[
                call.kwargs["embed"].description
                for call in followup.send.await_args_list
            ],
        ]
        self.assertGreater(len(sent_chunks), 1)
        self.assertTrue(
            all(len(chunk) <= main.MESSAGE_CHUNK_LIMIT for chunk in sent_chunks)
        )
        self.assertEqual("".join(sent_chunks), text)

    async def test_send_public_recolors_existing_embeds_gold(self):
        response = SimpleNamespace(
            is_done=lambda: False,
            send_message=AsyncMock(),
        )
        interaction = SimpleNamespace(
            user=SimpleNamespace(id=123456),
            response=response,
        )
        existing = main.discord.Embed(description="Stock quote", color=0x207E66)

        with patch.object(main, "get_user_language", AsyncMock(return_value="en")):
            await main.send_public(interaction, embed=existing)

        sent_embed = response.send_message.await_args.kwargs["embed"]
        self.assertEqual(sent_embed.description, "Stock quote")
        self.assertEqual(sent_embed.color.value, main.BANK_GOLD)

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
        channel_command = main.ACTION_COMMANDS_BY_PATH["admin market channel"]
        channel_parameter = channel_command.parameters[0]

        self.assertEqual(
            channel_parameter.type, main.discord.AppCommandOptionType.string
        )
        self.assertIsNotNone(channel_parameter._Parameter__parent.autocomplete)
        self.assertTrue(
            channel_command.description.startswith(main.ADMIN_DESCRIPTION_PREFIX)
        )
        self.assertEqual(len(channel_command.checks), 1)

    def test_admin_commands_are_labeled_and_restricted_in_discord(self):
        other = main.bot.tree.get_command("admin")
        mint = main.ACTION_COMMANDS_BY_PATH["admin mint"]
        credit = main.ACTION_COMMANDS_BY_PATH["admin credit set"].parent
        credit_adjust = main.ACTION_COMMANDS_BY_PATH["admin credit adjust"]
        benefits = main.ACTION_COMMANDS_BY_PATH["admin tier-benefits"]

        self.assertTrue(mint.description.startswith(main.ADMIN_DESCRIPTION_PREFIX))
        self.assertIsNone(other.default_permissions)
        self.assertIsNone(credit.default_permissions)
        self.assertTrue(mint.checks)
        self.assertTrue(
            credit_adjust.description.startswith(main.ADMIN_DESCRIPTION_PREFIX)
        )
        self.assertTrue(benefits.description.startswith(main.ADMIN_DESCRIPTION_PREFIX))

    def test_currency_delete_and_stock_relist_actions_are_admin_only(self):
        currency_delete = main.ACTION_COMMANDS_BY_PATH["admin currency delete"]
        currency_remove = main.ACTION_COMMANDS_BY_PATH["admin currency remove"]
        market_relist = main.ACTION_COMMANDS_BY_PATH["admin market relist"]

        self.assertTrue(currency_delete.checks)
        self.assertTrue(currency_remove.checks)
        self.assertTrue(market_relist.checks)
        self.assertIn(currency_delete, main.ACTION_COMMANDS_BY_CATEGORY["admin"])
        self.assertIn(market_relist, main.ACTION_COMMANDS_BY_CATEGORY["admin"])
        self.assertIn("delete", currency_delete.name)

    def test_every_admin_only_action_is_nested_under_admin(self):
        admin_only = [
            command
            for command in main.ACTION_COMMANDS_BY_PATH.values()
            if command.checks
        ]

        self.assertGreater(len(admin_only), 20)
        self.assertTrue(
            all(command.qualified_name.startswith("admin ") for command in admin_only)
        )
        self.assertFalse(main.ACTION_COMMANDS_BY_PATH["market news"].checks)
        self.assertFalse(main.ACTION_COMMANDS_BY_PATH["loan request"].checks)

    def test_currency_removal_and_relisting_confirmations_are_translated(self):
        currency_message = (
            "재화 `가지`를 사용 중지합니다. "
            "잔액과 거래 기록은 보존됩니다. 사유: 운영 종료"
        )
        relist_message = (
            "다음 종목을 다시 상장합니다: `테스트 주식`. "
            "기존 보유 주식과 거래 기록은 보존됩니다. 사유: 운영 재개"
        )

        self.assertEqual(
            translate_message(currency_message, "en"),
            "Disable currency 가지? Balances and transaction history will be preserved. Reason: 운영 종료",
        )
        self.assertEqual(
            translate_message(relist_message, "en"),
            "Relist 테스트 주식? Existing holdings and trade history will be preserved. Reason: 운영 재개",
        )
        self.assertEqual(
            translate_message(
                "재화 `가지`를 사용 중지했습니다. 사유: 운영 종료",
                "en",
            ),
            "Disabled currency 가지. Reason: 운영 종료",
        )

    def test_stock_supply_cannot_exceed_the_database_integer_limit(self):
        main.validate_share_supply(2_147_483_646, 1)
        with self.assertRaisesRegex(ValueError, "2,147,483,647"):
            main.validate_share_supply(2_147_483_647, 1)

    def test_user_facing_platinum_tier_spelling_is_correct(self):
        self.assertEqual(main.TIER_NAME["platinum"], "플래티넘")
        self.assertEqual(
            translate_message(
                "은행 의뢰는 플래티넘 등급 이상부터 이용할 수 있습니다.", "en"
            ),
            "Bank requests are available to Platinum tier and above.",
        )

    async def test_confirmation_button_rechecks_admin_permission(self):
        action = AsyncMock(return_value="executed")
        view = main.ConfirmActionView(123456, action)
        interaction = SimpleNamespace(
            user=SimpleNamespace(
                id=123456,
                guild_permissions=SimpleNamespace(
                    administrator=False, manage_guild=False
                ),
                roles=[],
            ),
            response=SimpleNamespace(edit_message=AsyncMock()),
        )

        with patch.object(main, "get_user_language", AsyncMock(return_value="ko")):
            await view.children[0].callback(interaction)

        action.assert_not_awaited()
        self.assertEqual(
            interaction.response.edit_message.await_args.kwargs["embed"].description,
            "관리자 권한이 확인되지 않아 실행하지 않았습니다.",
        )

    async def test_confirmation_button_shows_action_validation_errors(self):
        async def reject_action():
            raise ValueError("기본재화는 사용 중지할 수 없습니다.")

        view = main.ConfirmActionView(123456, reject_action)
        interaction = SimpleNamespace(
            user=SimpleNamespace(
                id=123456,
                guild_permissions=SimpleNamespace(
                    administrator=True, manage_guild=False
                ),
                roles=[],
            ),
            response=SimpleNamespace(edit_message=AsyncMock()),
        )

        with patch.object(main, "get_user_language", AsyncMock(return_value="ko")):
            await view.children[0].callback(interaction)

        self.assertEqual(
            interaction.response.edit_message.await_args.kwargs["embed"].description,
            "기본재화는 사용 중지할 수 없습니다.",
        )


if __name__ == "__main__":
    unittest.main()
