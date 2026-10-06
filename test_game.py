"""State-transition tests for game.py.

Every test drives one core flow (combat, potions, shop, equip, flee,
victory progression, mini-games) as an independently verifiable state
transition: input is scripted, randomness is seeded, and the player
state is asserted before/after. Mini-game tests prove the main state
is always intact after a game ends, is replayed, or exits abnormally.
"""
import builtins
import random
import sys

import pytest

import game

MONSTERS = [game.Rat, game.Vamp, game.BigBat,
            game.Archer_Elf, game.War_Elf, game.Elf_Chief,
            game.Giant_Eagle, game.Wind_Dragon, game.Sky_Monarch]

ALL_WEAPONS = ["Fists", "Wooden Sword", "Steel Sword", "Silver Sword",
               "Blaze Sword", "Z - Sword", "God Killer"]
EXPECTED_ATTACK = {"Fists": 10, "Wooden Sword": 15, "Steel Sword": 25,
                   "Silver Sword": 40, "Blaze Sword": 60,
                   "Z - Sword": 70, "God Killer": 90}


class InputsExhausted(Exception):
    """Raised when the game asks for more input than scripted."""


def feed(monkeypatch, items):
    items = list(items)

    def fake_input(prompt=""):
        if not items:
            raise InputsExhausted("game asked for unscripted input: %r" % prompt)
        return items.pop(0)

    monkeypatch.setattr(builtins, "input", fake_input)


def snapshot(player):
    return {
        "name": player.name,
        "MaxHealth": player.MaxHealth,
        "health": player.health,
        "MaxMana": player.MaxMana,
        "mana": player.mana,
        "coins": player.coins,
        "potions": dict(player.potions),
        "weapons": list(player.weapons),
        "currentWeapon": player.currentWeapon,
        "currLocation": player.currLocation,
        "base_attack": player.base_attack,
    }


@pytest.fixture(autouse=True)
def fresh_game(monkeypatch):
    monkeypatch.setattr(game.os, "system", lambda *a, **k: 0)
    monkeypatch.setattr(game.time, "sleep", lambda *a, **k: None)
    game.PlayerA = game.Player("Tester")
    game.enemy = game.Rat
    game.count = 0
    game.new_loc_1 = False
    game.new_loc_2 = False
    for monster in MONSTERS:
        monster.health = monster.MaxHealth
    yield


@pytest.fixture
def menu(monkeypatch):
    """Stub the main menu; records every entry into game1()."""
    calls = []
    monkeypatch.setattr(game, "game1", lambda: calls.append("game1"))
    return calls


@pytest.fixture
def combat_events(monkeypatch, menu):
    events = []
    orig_victory = game.victory
    orig_defeat = game.defeat

    def victory_spy():
        events.append("victory")
        orig_victory()

    def defeat_spy():
        events.append("defeat")
        orig_defeat()

    monkeypatch.setattr(game, "victory", victory_spy)
    monkeypatch.setattr(game, "defeat", defeat_spy)
    return events


# ---------------------------------------------------------------- combat

class TestCombatFlow:
    def test_attack_kill_never_lets_enemy_counterattack(self, combat_events):
        """After victory() the round must stop: no damage, no defeat."""
        for seed in range(30):
            game.count = 0
            game.PlayerA.health = 5
            game.Rat.health = 1
            game.Rat.attack = 30
            combat_events.clear()
            random.seed(seed)
            game.attack()
            if "victory" in combat_events:
                assert "defeat" not in combat_events
                assert game.PlayerA.health == 5
            game.Rat.health = game.Rat.MaxHealth

    def test_special_attack_kill_never_lets_enemy_counterattack(
            self, combat_events):
        for seed in range(30):
            game.count = 0
            game.PlayerA.health = 5
            game.PlayerA.mana = 20
            game.Rat.health = 1
            game.Rat.attack = 30
            combat_events.clear()
            random.seed(seed)
            game.special_attack()
            assert "victory" in combat_events  # Fire Strike always lands
            assert "defeat" not in combat_events
            assert game.PlayerA.health == 5
            assert game.PlayerA.mana == game.PlayerA.MaxMana  # victory refills
            game.Rat.health = game.Rat.MaxHealth

    def test_player_death_triggers_defeat_exactly_once(self, combat_events):
        game.PlayerA.health = 5
        game.Rat.health = 1000  # player cannot kill it
        game.Rat.attack = 30
        random.seed(1)
        game.attack()
        assert combat_events == ["defeat"]
        assert game.PlayerA.health == game.PlayerA.MaxHealth
        assert game.PlayerA.mana == game.PlayerA.MaxMana

    def test_defeat_never_makes_coins_negative(self, menu):
        game.PlayerA.coins = 5
        game.defeat()
        assert game.PlayerA.coins == 0
        game.PlayerA.coins = 30
        game.defeat()
        assert game.PlayerA.coins == 20
        assert menu == ["game1", "game1"]

    def test_fight_menu_enters_once_per_keypress(self, monkeypatch):
        entries = []
        original_fight = game.fight

        def counting_fight():
            entries.append(1)
            if len(entries) == 1:
                original_fight()

        monkeypatch.setattr(game, "fight", counting_fight)
        monkeypatch.setattr(game, "pre_attack", lambda: None)
        feed(monkeypatch, ["1"])
        game.fight()
        assert entries == [1]

    def test_fight_invalid_option_reasks(self, monkeypatch):
        chosen = []
        monkeypatch.setattr(game, "pre_attack", lambda: chosen.append("atk"))
        feed(monkeypatch, ["9", "1"])
        game.fight()
        assert chosen == ["atk"]

    def test_fight_option_routing(self, monkeypatch):
        called = []
        monkeypatch.setattr(game, "potion", lambda: called.append("potion"))
        monkeypatch.setattr(game, "run", lambda: called.append("run"))
        feed(monkeypatch, ["2"])
        game.fight()
        feed(monkeypatch, ["3"])
        game.fight()
        assert called == ["potion", "run"]


# ---------------------------------------------------------------- potions

class TestPotions:
    def test_potion_heals_30_and_decrements(self, monkeypatch):
        game.PlayerA.health = 50
        feed(monkeypatch, ["Potion"])
        game.potion1()
        assert game.PlayerA.health == 80
        assert game.PlayerA.potions["Potion"] == 2

    def test_potion_heal_clamped_at_max(self, monkeypatch):
        game.PlayerA.health = 90
        feed(monkeypatch, ["Potion"])
        game.potion1()
        assert game.PlayerA.health == game.PlayerA.MaxHealth
        assert game.PlayerA.potions["Potion"] == 2

    def test_potion_not_consumed_at_full_health(self, monkeypatch, capsys):
        game.PlayerA.health = game.PlayerA.MaxHealth
        feed(monkeypatch, ["Potion"])
        game.potion1()
        assert game.PlayerA.potions["Potion"] == 3
        assert game.PlayerA.health == game.PlayerA.MaxHealth
        assert "already full" in capsys.readouterr().out

    def test_ghp_heals_80_and_clamps(self, monkeypatch):
        game.PlayerA.health = 50
        game.PlayerA.potions["Greater Healing Potion"] = 1
        feed(monkeypatch, ["Greater Healing Potion"])
        game.potion1()
        assert game.PlayerA.health == game.PlayerA.MaxHealth
        assert game.PlayerA.potions["Greater Healing Potion"] == 0

    def test_potion_without_stock_is_a_noop(self, monkeypatch, capsys):
        game.PlayerA.health = 50
        game.PlayerA.potions["Potion"] = 0
        feed(monkeypatch, ["Potion"])
        game.potion1()
        assert game.PlayerA.health == 50
        assert "don't have any Potions" in capsys.readouterr().out

    def test_unknown_potion_is_a_noop(self, monkeypatch):
        game.PlayerA.health = 50
        feed(monkeypatch, ["Ultra Potion"])
        game.potion1()
        assert game.PlayerA.health == 50
        assert game.PlayerA.potions == {"Potion": 3,
                                        "Greater Healing Potion": 0}

    def test_potions_replay_until_empty(self, monkeypatch):
        game.PlayerA.health = 10
        feed(monkeypatch, ["Potion"])
        game.potion1()
        feed(monkeypatch, ["Potion"])
        game.potion1()
        assert game.PlayerA.health == 70
        assert game.PlayerA.potions["Potion"] == 1

# ------------------------------------------------------------------ shop

@pytest.mark.usefixtures("menu")
class TestShop:
    def test_buy_weapon_with_exact_coins(self, monkeypatch, menu):
        game.PlayerA.coins = 50
        feed(monkeypatch, ["1", "Steel Sword", "3"])
        game.shop()
        assert game.PlayerA.coins == 0
        assert "Steel Sword" in game.PlayerA.weapons

    def test_buy_weapon_with_insufficient_coins(self, monkeypatch):
        game.PlayerA.coins = 49
        feed(monkeypatch, ["1", "Steel Sword", "3"])
        game.shop()
        assert game.PlayerA.coins == 49
        assert "Steel Sword" not in game.PlayerA.weapons

    def test_cannot_buy_weapon_twice(self, monkeypatch):
        game.PlayerA.coins = 200
        game.PlayerA.weapons.append("Steel Sword")
        feed(monkeypatch, ["1", "Steel Sword", "3"])
        game.shop()
        assert game.PlayerA.coins == 200
        assert game.PlayerA.weapons.count("Steel Sword") == 1

    def test_buy_potions_success(self, monkeypatch):
        game.PlayerA.coins = 30
        feed(monkeypatch, ["2", "Potion", "2", "3"])
        game.shop()
        assert game.PlayerA.coins == 20
        assert game.PlayerA.potions["Potion"] == 5

    @pytest.mark.parametrize("count", ["0", "-3", "abc"])
    def test_invalid_potion_quantity_changes_nothing(self, monkeypatch, count):
        game.PlayerA.coins = 30
        potions_before = dict(game.PlayerA.potions)
        feed(monkeypatch, ["2", "Potion", count, "3"])
        game.shop()
        assert game.PlayerA.coins == 30
        assert game.PlayerA.potions == potions_before

    def test_unaffordable_potions_change_nothing(self, monkeypatch):
        game.PlayerA.coins = 12
        potions_before = dict(game.PlayerA.potions)
        feed(monkeypatch, ["2", "Potion", "3", "3"])
        game.shop()
        assert game.PlayerA.coins == 12
        assert game.PlayerA.potions == potions_before

    @pytest.mark.parametrize("count", ["0", "-1", "xyz"])
    def test_invalid_ghp_quantity_changes_nothing(self, monkeypatch, count):
        game.PlayerA.coins = 30
        potions_before = dict(game.PlayerA.potions)
        feed(monkeypatch, ["2", "Greater Healing Potion", count, "3"])
        game.shop()
        assert game.PlayerA.coins == 30
        assert game.PlayerA.potions == potions_before

    def test_coin_deduction_matches_items_received(self, monkeypatch):
        """Payment and inventory must stay consistent across a session."""
        game.PlayerA.coins = 30
        feed(monkeypatch, [
            "2", "Potion", "2",            # -5*2 = 10
            "2", "Potion", "-3",           # rejected
            "2", "Greater Healing Potion", "1",  # -20, exact boundary
            "3",
        ])
        game.shop()
        assert game.PlayerA.coins == 0
        assert game.PlayerA.potions == {"Potion": 5,
                                        "Greater Healing Potion": 1}


# ----------------------------------------------------------------- equip

@pytest.mark.usefixtures("menu")
class TestEquip:
    def test_initial_weapon_state(self):
        assert game.PlayerA.currentWeapon == "Fists"
        assert isinstance(game.PlayerA.currentWeapon, str)
        assert game.Player("x").attack == 10

    @pytest.mark.parametrize("weapon", ALL_WEAPONS)
    def test_every_weapon_gives_expected_attack(self, monkeypatch, weapon):
        player = game.PlayerA
        player.weapons = list(ALL_WEAPONS)
        feed(monkeypatch, [weapon, "Back"])
        game.equip()
        assert player.currentWeapon == weapon
        assert player.attack == EXPECTED_ATTACK[weapon]

    def test_switch_back_to_fists_restores_base(self, monkeypatch):
        player = game.PlayerA
        player.weapons = list(ALL_WEAPONS)
        feed(monkeypatch, ["God Killer"])
        game.equip()
        assert player.attack == 90
        feed(monkeypatch, ["Fists"])
        game.equip()
        assert player.currentWeapon == "Fists"
        assert player.attack == 10

    def test_equipping_unowned_weapon_is_rejected(self, monkeypatch):
        feed(monkeypatch, ["God Killer", "Back"])
        game.equip()
        assert game.PlayerA.currentWeapon == "Fists"

    @pytest.mark.parametrize("partial", ["ood", "Wood", "Sword", "f"])
    def test_substring_names_are_rejected(self, monkeypatch, partial):
        player = game.PlayerA
        feed(monkeypatch, ["Wooden Sword"])
        game.equip()
        feed(monkeypatch, [partial, "Back"])
        game.equip()
        assert player.currentWeapon == "Wooden Sword"

    def test_equipping_current_weapon_is_noop(self, monkeypatch, capsys):
        feed(monkeypatch, ["Fists", "Back"])
        game.equip()
        assert game.PlayerA.currentWeapon == "Fists"
        assert "Already equipped" in capsys.readouterr().out


# -------------------------------------------------------------------- run

class TestRun:
    def test_flee_with_exact_boundary_5_coins(self, monkeypatch, menu):
        game.PlayerA.coins = 5
        monkeypatch.setattr(game, "fight", lambda: None)
        game.run()
        assert game.PlayerA.coins == 0
        assert menu == ["game1"]

    def test_flee_with_4_coins_fails(self, monkeypatch):
        game.PlayerA.coins = 4
        forced = []
        monkeypatch.setattr(game, "fight", lambda: forced.append("fight"))
        game.run()
        assert game.PlayerA.coins == 4
        assert forced == ["fight"]

    def test_flee_with_6_coins_leaves_1(self, monkeypatch, menu):
        game.PlayerA.coins = 6
        monkeypatch.setattr(game, "fight", lambda: None)
        game.run()
        assert game.PlayerA.coins == 1


# ------------------------------------------------------------- victory

class TestVictory:
    def test_victory_awards_coins_and_resets_round(self, menu):
        game.Rat.health = 3
        game.PlayerA.mana = 0
        game.victory()
        assert game.PlayerA.coins == 30 + game.Rat.Gaincoins
        assert game.Rat.health == game.Rat.MaxHealth
        assert game.PlayerA.mana == game.PlayerA.MaxMana
        assert game.count == 1
        assert menu == ["game1"]

    def test_fifth_victory_unlocks_forest_of_elves(self, menu):
        game.count = 4
        game.Rat.health = 1
        game.victory()
        assert game.PlayerA.currLocation == "Forest of Elves"
        assert game.PlayerA.MaxHealth == 250
        assert game.PlayerA.health == 250
        assert game.PlayerA.MaxMana == 40
        assert game.new_loc_1 is True

    def test_fifteenth_victory_unlocks_heavenly_skies(self, menu):
        game.count = 14
        game.PlayerA.MaxHealth = 250
        game.PlayerA.MaxMana = 40
        game.Rat.health = 1
        game.victory()
        assert game.PlayerA.currLocation == "Heavenly Skies"
        assert game.PlayerA.MaxHealth == 650
        assert game.PlayerA.health == 650
        assert game.new_loc_2 is True

    def test_location_text_and_game_keys_are_unchanged(self):
        assert game.Locations == {
            0: "Void Cave", 1: "Forest of Elves", 2: "Heavenly Skies"}
        assert game.Mini_Games_List == [
            "Impossible Tic Tac Toe", "Snake Game", "Conquer the Maze"]
        assert set(game.Weapons_in_Shop) == {
            "Steel Sword", "Silver Sword", "Blaze Sword",
            "Z - Sword", "God Killer"}
        assert game.Potions_in_Shop == {"Potion": 5,
                                        "Greater Healing Potion": 20}


# ----------------------------------------------------------- mini-games

class TestMiniGameMenu:
    def test_exit_returns_to_main_menu_intact(self, monkeypatch, menu):
        before = snapshot(game.PlayerA)
        feed(monkeypatch, ["4"])
        game.minigame()
        assert menu == ["game1"]
        assert snapshot(game.PlayerA) == before

    def test_non_numeric_choice_is_rejected_then_exit(self, monkeypatch, menu):
        before = snapshot(game.PlayerA)
        feed(monkeypatch, ["abc", "4"])
        game.minigame()
        assert menu == ["game1"]
        assert snapshot(game.PlayerA) == before


class TestTicTacToe:
    MOVES = [str(n) for n in (5, 2, 3, 4, 6, 7, 8, 9, 1)] * 3

    def test_playing_second_ends_in_one_clean_menu_entry(
            self, monkeypatch, menu, capsys):
        before = snapshot(game.PlayerA)
        feed(monkeypatch, ["2"] + self.MOVES)
        game.TicTacToe()
        assert len(menu) == 1
        output = capsys.readouterr().out
        assert "Bot wins!" in output or "Draw!" in output
        assert "player wins!" not in output
        assert game.PlayerA.coins == before["coins"]
        assert snapshot(game.PlayerA) == before

    def test_playing_first_ends_in_one_clean_menu_entry(
            self, monkeypatch, menu):
        before = snapshot(game.PlayerA)
        feed(monkeypatch, ["1"] + self.MOVES)
        game.TicTacToe()
        assert len(menu) == 1
        assert snapshot(game.PlayerA) == before

    def test_invalid_and_out_of_range_inputs_are_recovered(
            self, monkeypatch, menu):
        before = snapshot(game.PlayerA)
        feed(monkeypatch, ["abc", "2", "99", "0", "-1"] + self.MOVES)
        game.TicTacToe()
        assert snapshot(game.PlayerA) == before

    def test_replay_keeps_state_intact(self, monkeypatch, menu):
        before = snapshot(game.PlayerA)
        feed(monkeypatch, ["2"] + self.MOVES)
        game.TicTacToe()
        feed(monkeypatch, ["1"] + self.MOVES)
        game.TicTacToe()
        assert len(menu) == 2
        assert snapshot(game.PlayerA) == before

    def test_abnormal_exit_does_not_corrupt_main_state(self, monkeypatch):
        before = snapshot(game.PlayerA)
        feed(monkeypatch, ["2"])  # input stream ends while playing
        with pytest.raises(InputsExhausted):
            game.TicTacToe()
        assert snapshot(game.PlayerA) == before


class TestSnake:
    def test_missing_pygame_returns_to_minigame_menu(
            self, monkeypatch, menu):
        before = snapshot(game.PlayerA)
        back_to_menu = []
        monkeypatch.setattr(game, "minigame", lambda: back_to_menu.append(1))
        monkeypatch.setitem(sys.modules, "pygame", None)
        game.snakegame()
        assert back_to_menu == [1]
        assert snapshot(game.PlayerA) == before


class TestMaze:
    @pytest.fixture
    def fixed_enemies(self, monkeypatch):
        # Every enemy lands at (2,2); start and exit stay free.
        monkeypatch.setattr(game.random, "randint", lambda a, b: 2)

    WIN_PATH = ["5", "D", "D", "D", "D", "S", "S", "S", "S"]
    MONSTER_PATH = ["5", "S", "S", "D", "D"]

    def test_win_awards_reward_exactly_once(self, monkeypatch, menu,
                                            fixed_enemies):
        before = snapshot(game.PlayerA)
        feed(monkeypatch, self.WIN_PATH)
        game.mazegame()
        assert len(menu) == 1
        assert game.PlayerA.coins == before["coins"] + 100
        expected = {**before, "coins": before["coins"] + 100}
        assert snapshot(game.PlayerA) == expected

    def test_monster_attack_ends_game_without_reward(
            self, monkeypatch, menu, fixed_enemies, capsys):
        before = snapshot(game.PlayerA)
        feed(monkeypatch, self.MONSTER_PATH)
        game.mazegame()
        assert len(menu) == 1
        assert "GAME OVER" in capsys.readouterr().out
        assert snapshot(game.PlayerA) == before

    def test_wall_hit_resets_position_and_win_still_works(
            self, monkeypatch, menu, fixed_enemies):
        before = snapshot(game.PlayerA)
        feed(monkeypatch, ["5", "W"] + self.WIN_PATH[1:])
        game.mazegame()
        assert game.PlayerA.coins == before["coins"] + 100

    def test_non_numeric_size_defaults_to_5(self, monkeypatch, menu,
                                            fixed_enemies):
        before = snapshot(game.PlayerA)
        feed(monkeypatch, ["abc"] + self.WIN_PATH[1:])
        game.mazegame()
        assert game.PlayerA.coins == before["coins"] + 100

    def test_replay_awards_each_win(self, monkeypatch, menu, fixed_enemies):
        before = snapshot(game.PlayerA)
        feed(monkeypatch, self.WIN_PATH)
        game.mazegame()
        feed(monkeypatch, self.WIN_PATH)
        game.mazegame()
        assert len(menu) == 2
        assert game.PlayerA.coins == before["coins"] + 200

    def test_abnormal_exit_does_not_corrupt_main_state(
            self, monkeypatch, fixed_enemies):
        before = snapshot(game.PlayerA)
        feed(monkeypatch, ["5"])  # input stream ends inside the maze
        with pytest.raises(InputsExhausted):
            game.mazegame()
        assert snapshot(game.PlayerA) == before


# ------------------------------------------------------------- main menu

class TestMainMenu:
    def test_exit_quits(self, monkeypatch):
        feed(monkeypatch, ["6"])
        with pytest.raises(SystemExit):
            game.game1()
