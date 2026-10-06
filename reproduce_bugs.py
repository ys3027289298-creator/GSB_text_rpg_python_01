"""Reproduce the six bug classes in game.py along the main flow.

Each check drives the real game functions with input/random/output
stubbed. It prints BUG (reproduced on the buggy code) or OK.
"""
import builtins
import contextlib
import io
import os
import random
import sys
import time

import game

os.system = lambda *a, **k: 0
time.sleep = lambda *a, **k: None

MONSTERS = [game.Rat, game.Vamp, game.BigBat,
            game.Archer_Elf, game.War_Elf, game.Elf_Chief,
            game.Giant_Eagle, game.Wind_Dragon, game.Sky_Monarch]

ORIG_INPUT = builtins.input
ORIG = {name: getattr(game, name) for name in
        ("game1", "fight", "victory", "defeat", "minigame",
         "pre_attack")}


class InputsExhausted(Exception):
    pass


class Feeder:
    def __init__(self, items):
        self.items = list(items)

    def __call__(self, prompt=""):
        if not self.items:
            raise InputsExhausted("no more scripted input for %r" % prompt)
        return self.items.pop(0)


@contextlib.contextmanager
def feed(items):
    feeder = Feeder(items)
    builtins.input = feeder
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            yield buf
    finally:
        builtins.input = ORIG_INPUT


def fresh_player(coins=30):
    game.PlayerA = game.Player("Hero")
    game.PlayerA.coins = coins
    game.enemy = game.Rat
    game.count = 0
    game.new_loc_1 = False
    game.new_loc_2 = False
    for monster in MONSTERS:
        monster.health = monster.MaxHealth
    return game.PlayerA


def reset_globals():
    for name, func in ORIG.items():
        setattr(game, name, func)


def find_seed(run_round, damaged):
    """Search for a random seed where the enemy counterattack lands."""
    for seed in range(500):
        fresh_player()
        game.PlayerA.health = 5
        game.Rat.health = 1
        game.Rat.attack = 30
        events = []
        game.victory = lambda: (events.append("victory"), ORIG["victory"]())
        game.defeat = lambda: (events.append("defeat"), ORIG["defeat"]())
        game.game1 = lambda: events.append("game1")
        random.seed(seed)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                run_round()
        except Exception:
            continue
        if damaged(events) and (game.PlayerA.health != 5 or "defeat" in events):
            return seed, events, game.PlayerA.health
    return None, [], 5


def check_attack_after_victory():
    """attack(): a killed enemy must not keep attacking (death after win)."""
    def run_round():
        game.attack()
    seed, events, health = find_seed(run_round, lambda ev: "victory" in ev)
    reset_globals()
    if seed is not None:
        return True, "seed=%s: after victory() the dead enemy still " \
                     "counter-attacked, health 5->%s, events=%s" % (
                         seed, health, events)
    return False, "killed enemy never counter-attacks"


def check_special_after_victory():
    """special_attack(): same fall-through after a Fire Strike kill."""
    def run_round():
        game.PlayerA.mana = 20
        game.special_attack()
    seed, events, health = find_seed(run_round, lambda ev: "victory" in ev)
    reset_globals()
    if seed is not None:
        return True, "seed=%s: Fire Strike killed enemy, then enemy " \
                     "counter-attacked anyway, health 5->%s, events=%s" % (
                         seed, health, events)
    return False, "no counter-attack after special-attack kill"


def check_fight_double_recursion():
    """fight(): picking one option must not re-enter fight() via the
    dangling else of the third if."""
    fresh_player()
    entries = []

    def counting_fight():
        entries.append(1)
        if len(entries) == 1:
            ORIG["fight"]()

    game.fight = counting_fight
    game.pre_attack = lambda: None
    with feed(["1"]):
        game.fight()
    reset_globals()
    if len(entries) > 1:
        return True, "fight() re-entered %i times from one keypress" % len(entries)
    return False, "single fight() entry per keypress"


def check_potion_at_full_health():
    """Potion must not be consumed when the heal overflows MaxHealth."""
    player = fresh_player()
    player.health = player.MaxHealth
    with feed(["Potion"]):
        game.potion1()
    if player.potions["Potion"] != 3:
        return True, "full-health potion consumed, potions 3->%s" % (
            player.potions["Potion"],)
    return False, "potion kept at full health"


def check_shop_negative_potions():
    """Negative quantity must not turn the shop into an ATM."""
    player = fresh_player(coins=30)
    game.game1 = lambda: None
    with feed(["2", "Potion", "-10", "3"]):
        game.shop()
    reset_globals()
    if player.coins != 30 or player.potions["Potion"] != 3:
        return True, "bought -10 potions: coins 30->%s, potions 3->%s" % (
            player.coins, player.potions["Potion"])
    return False, "negative quantity rejected"


def check_shop_duplicate_weapon():
    """A weapon already owned must not be sold twice."""
    player = fresh_player(coins=200)
    game.game1 = lambda: None
    with feed(["1", "Steel Sword", "1", "Steel Sword", "3"]):
        game.shop()
    reset_globals()
    copies = player.weapons.count("Steel Sword")
    if copies > 1 or player.coins < 200 - 50:
        return True, "Steel Sword owned x%s, coins 200->%s" % (copies, player.coins)
    return False, "duplicate purchase rejected"


def check_equip_state():
    """currentWeapon type and the substring 'already equipped' bug."""
    evidence = []
    if isinstance(game.Player("x").currentWeapon, list):
        evidence.append("currentWeapon initialised as a list ['Fists']")
    player = fresh_player()
    game.game1 = lambda: None
    with feed(["Wooden Sword"]):
        game.equip()
    with feed(["ood", "Back"]) as buf:
        game.equip()
    reset_globals()
    if "Already equipped ood" in buf.getvalue():
        evidence.append("'ood' accepted as already-equipped via substring")
    if evidence:
        return True, "; ".join(evidence)
    return False, "exact weapon matching, string weapon state"


def check_run_boundary():
    """Flee costs exactly 5 coins: 5 coins must be enough."""
    player = fresh_player(coins=5)
    events = []
    game.game1 = lambda: events.append("game1")
    game.fight = lambda: events.append("fight")
    with feed([]):
        game.run()
    reset_globals()
    if "fight" in events:
        return True, "5 coins refused for a 5-coin flee"
    if player.coins != 0:
        return True, "flee left %s coins (expected 0)" % player.coins
    return False, "5 coins exactly covers the flee fee"


def check_defeat_negative_coins():
    """Defeat penalty must not drive coins below zero."""
    player = fresh_player(coins=5)
    game.game1 = lambda: None
    game.defeat()
    reset_globals()
    if player.coins < 0:
        return True, "defeat made coins 5->%s" % player.coins
    return False, "defeat floored coins at 0"


def check_tictactoe_end():
    """When the board game ends the main game must not keep running."""
    player = fresh_player()
    calls = []
    game.game1 = lambda: calls.append("game1")
    moves = ["2"] + [str(n) for n in (5, 2, 3, 4, 6, 7, 8, 9, 1)] * 3
    crashed = None
    try:
        with feed(moves):
            game.TicTacToe()
    except InputsExhausted as exc:
        crashed = str(exc)
    reset_globals()
    if crashed is not None:
        return True, "after the game ended it kept asking for moves: %s" % crashed
    if len(calls) != 1 or player.coins != 30:
        return True, "game1 called %s time(s), coins 30->%s (bogus 'player " \
                     "wins' after bot win / double menu)" % (len(calls), player.coins)
    return False, "single clean exit, coins intact"


def check_maze_end(step, label, reward):
    player = fresh_player()
    calls = []
    game.game1 = lambda: calls.append("game1")
    orig_randint = random.randint
    random.randint = lambda a, b: 2
    crashed = None
    try:
        with feed(step):
            game.mazegame()
    except InputsExhausted as exc:
        crashed = str(exc)
    finally:
        random.randint = orig_randint
    reset_globals()
    if crashed is not None:
        return True, "%s: after %s the maze kept looping: %s" % (label, label, crashed)
    if len(calls) != 1 or player.coins != 30 + reward:
        return True, "%s: game1 called %s time(s), coins 30->%s" % (
            label, len(calls), player.coins)
    return False, "%s ends cleanly" % label


def check_snake_import():
    """Missing pygame must crash back to the minigame menu, not kill main."""
    fresh_player()
    calls = []
    game.minigame = lambda: calls.append("minigame")
    sys.modules["pygame"] = None
    crashed = None
    try:
        with feed([]):
            game.snakegame()
    except ImportError as exc:
        crashed = str(exc)
    finally:
        sys.modules.pop("pygame", None)
    reset_globals()
    if crashed is not None:
        return True, "ImportError escaped snakegame(): %s" % crashed
    if not calls:
        return True, "snake did not return to the minigame menu"
    return False, "missing pygame handled, back to menu"


def check_minigame_menu_bad_input():
    fresh_player()
    calls = []
    game.game1 = lambda: calls.append("game1")
    crashed = None
    try:
        with feed(["abc", "4"]):
            game.minigame()
    except ValueError as exc:
        crashed = str(exc)
    reset_globals()
    if crashed is not None:
        return True, "non-numeric menu choice crashed minigame(): %s" % crashed
    if len(calls) != 1:
        return True, "exit led to %s game1 calls" % len(calls)
    return False, "bad menu input handled, exit works"


CHECKS = [
    ("death/attack fall-through", check_attack_after_victory),
    ("death/special fall-through", check_special_after_victory),
    ("fight double recursion", check_fight_double_recursion),
    ("potion overflow at full hp", check_potion_at_full_health),
    ("shop negative quantity", check_shop_negative_potions),
    ("shop duplicate weapon", check_shop_duplicate_weapon),
    ("equip wrong state", check_equip_state),
    ("flee 5-coin boundary", check_run_boundary),
    ("defeat negative coins", check_defeat_negative_coins),
    ("tic-tac-toe end keeps running", check_tictactoe_end),
    ("maze monster hit keeps looping",
     lambda: check_maze_end(["5", "S", "S", "D", "D"], "monster hit", 0)),
    ("maze win keeps looping",
     lambda: check_maze_end(["5", "D", "D", "D", "D", "S", "S", "S", "S"],
                            "win", 100)),
    ("snake without pygame", check_snake_import),
    ("minigame menu bad input", check_minigame_menu_bad_input),
]


def main():
    bugs = 0
    for name, check in CHECKS:
        try:
            found, evidence = check()
        except Exception as exc:  # a crash here is itself a bug reproduction
            found, evidence = True, "%s: %s" % (type(exc).__name__, exc)
        status = "BUG " if found else " OK "
        print("[%s] %-34s %s" % (status, name, evidence))
        if found:
            bugs += 1
        reset_globals()
    print("\n%i/%i checks reproduce a bug" % (bugs, len(CHECKS)))
    return 1 if bugs else 0


if __name__ == "__main__":
    sys.exit(main())
