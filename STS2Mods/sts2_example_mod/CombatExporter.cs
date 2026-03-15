using System.Reflection;
using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Localization.DynamicVars;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.MonsterMoves.Intents;
using MegaCrit.Sts2.Core.Logging;

namespace FirstMod;

public static class CombatExporter
{
    private const int ThrottleMs = 300;

    private static readonly JsonSerializerOptions JsonOpts = new() { WriteIndented = false };

    private static CombatState? _combat;
    private static string? _lastJson;
    private static long _lastWriteTicks;
    private static bool _pending;
    private static System.Threading.Timer? _debounceTimer;
    private static string? _outputPath;

    private static List<SnapshotRelic>? _cachedRelics;
    private static int _cachedRelicCount = -1;

    private static List<MerchantRelicSnapshot>? _merchantRelics;

    public static void SetCombatState(CombatState? cs)
    {
        _combat = cs;
    }

    public static void SetMerchantRelics(MerchantInventory? inventory)
    {
        if (inventory == null)
        {
            _merchantRelics = null;
            RequestExport();
            return;
        }

        try
        {
            _merchantRelics = inventory.RelicEntries
                .Where(e => e.IsStocked && e.Model != null)
                .Select(e => new MerchantRelicSnapshot
                {
                    name = LocStr(e.Model!.Title) ?? e.Model.GetType().Name,
                    id = e.Model.GetType().Name,
                    rarity = e.Model.Rarity.ToString().ToLowerInvariant(),
                    cost = e.Cost,
                })
                .ToList();
            Log.Info($"[BoberInSpire] Merchant relics captured: {_merchantRelics.Count}");
            RequestExport();
        }
        catch (Exception ex)
        {
            Log.Error($"[BoberInSpire] Merchant relic capture failed: {ex.Message}");
        }
    }

    public static void ClearMerchant()
    {
        _merchantRelics = null;
    }

    public static void RequestExport()
    {
        if (_combat == null) return;

        var now = System.Environment.TickCount64;
        if (now - _lastWriteTicks < ThrottleMs)
        {
            ScheduleDebouncedExport();
            return;
        }

        DoExport();
    }

    public static void RequestExportFrom(Player? player)
    {
        if (player == null) return;

        if (_combat == null)
        {
            _combat = player.PlayerCombatState?.Hand?.Cards?.FirstOrDefault()?.CombatState
                      ?? player.PlayerCombatState?.DrawPile?.Cards?.FirstOrDefault()?.CombatState;
        }

        RequestExport();
    }

    public static void InvalidateRelicCache()
    {
        _cachedRelics = null;
        _cachedRelicCount = -1;
    }

    private static void ScheduleDebouncedExport()
    {
        if (_pending) return;
        _pending = true;

        _debounceTimer?.Dispose();
        _debounceTimer = new System.Threading.Timer(_ =>
        {
            _pending = false;
            DoExport();
        }, null, ThrottleMs, System.Threading.Timeout.Infinite);
    }

    private static void DoExport()
    {
        if (_combat == null) return;

        try
        {
            var player = _combat.Players.FirstOrDefault();
            if (player == null) return;

            var snapshot = BuildSnapshot(_combat, player);
            var json = JsonSerializer.Serialize(snapshot, JsonOpts);

            if (json == _lastJson) return;
            _lastJson = json;
            _lastWriteTicks = System.Environment.TickCount64;

            _outputPath ??= ProjectSettings.GlobalizePath("user://bober_combat_state.json");

            Task.Run(() =>
            {
                try { File.WriteAllText(_outputPath, json); }
                catch { }
            });
        }
        catch (Exception ex)
        {
            Log.Error($"[BoberInSpire] Export failed: {ex.Message}");
        }
    }

    private static Snapshot BuildSnapshot(CombatState combat, Player player)
    {
        var pcs = player.PlayerCombatState;
        var hand = pcs?.Hand?.Cards;
        var relicCount = player.Relics.Count;

        if (_cachedRelics == null || _cachedRelicCount != relicCount)
        {
            _cachedRelics = new List<SnapshotRelic>();
            foreach (var r in player.Relics)
            {
                try
                {
                    _cachedRelics.Add(BuildRelic(r));
                }
                catch (Exception ex)
                {
                    Log.Error($"[BoberInSpire] BuildRelic skip: {ex.Message}");
                }
            }
            _cachedRelicCount = relicCount;
        }

        var handCards = new List<SnapshotCard>();
        if (hand != null)
        {
            foreach (var card in hand)
            {
                try { handCards.Add(BuildCard(card)); }
                catch (Exception ex) { Log.Error($"[BoberInSpire] BuildCard skip {card?.GetType().Name}: {ex.Message}"); }
            }
        }

        return new Snapshot
        {
            player = BuildPlayer(player),
            hand = handCards,
            enemies = combat.Enemies.Where(e => e.IsAlive).Select(BuildEnemy).ToList(),
            relics = _cachedRelics,
            merchant_relics = _merchantRelics,
            turn = combat.RoundNumber,
            draw_pile_count = pcs?.DrawPile?.Cards?.Count ?? 0,
            discard_pile_count = pcs?.DiscardPile?.Cards?.Count ?? 0,
        };
    }

    private static SnapshotPlayer BuildPlayer(Player player)
    {
        var pcs = player.PlayerCombatState;
        var c = player.Creature;
        return new SnapshotPlayer
        {
            energy = pcs?.Energy ?? 0,
            max_energy = pcs?.MaxEnergy ?? player.MaxEnergy,
            strength = PowerAmount(c, "StrengthPower"),
            dexterity = PowerAmount(c, "DexterityPower"),
            vigor = PowerAmount(c, "VigorPower"),
            weak_turns = PowerAmount(c, "WeakPower"),
            frail_turns = PowerAmount(c, "FrailPower"),
            hp = c?.CurrentHp ?? 0,
            max_hp = c?.MaxHp ?? 0,
            block = c?.Block ?? 0,
        };
    }

    private static int DynInt(DynamicVarSet vars, string key) =>
        vars.TryGetValue(key, out var v) ? v.IntValue : 0;

    private static SnapshotCard BuildCard(CardModel card)
    {
        var vars = card.DynamicVars;
        var description = TryGetCardDescription(card);
        return new SnapshotCard
        {
            name        = card.Title ?? card.GetType().Name,
            damage      = DynInt(vars, "Damage"),
            block       = DynInt(vars, "Block"),
            hits        = Math.Max(DynInt(vars, "Repeat"), 1),
            energy_cost = card.EnergyCost?.Canonical ?? 0,
            card_type   = card.Type.ToString().ToLowerInvariant(),
            id          = card.GetType().Name,
            description = description ?? "",
        };
    }

    private static string? TryGetCardDescription(CardModel card)
    {
        try
        {
            var desc = card.GetType().GetProperty("Description")?.GetValue(card)
                ?? card.GetType().GetProperty("Body")?.GetValue(card)
                ?? card.GetType().GetProperty("BodyText")?.GetValue(card);
            return desc != null ? LocStr(desc) : null;
        }
        catch { return null; }
    }

    private static SnapshotEnemy BuildEnemy(Creature enemy)
    {
        var nextMove = enemy.Monster?.NextMove;
        var intents = nextMove?.Intents;
        var intentName = "UnknownIntent";
        var totalDmg = 0;
        var maxHits = 1;

        // Read enemy debuffs that affect their damage output
        var weakPower = PowerAmount(enemy, "WeakPower");

        if (intents != null)
        {
            foreach (var intent in intents)
            {
                if (intentName == "UnknownIntent")
                    intentName = intent.GetType().Name;

                if (intent is AttackIntent atk)
                {
                    var dmg = 0;
                    try { if (atk.DamageCalc != null) dmg = (int)Math.Floor(atk.DamageCalc()); }
                    catch { }

                    // Apply Weak: reduces attacker's damage by 25% (floor per hit, like STS1)
                    if (weakPower > 0)
                        dmg = (int)Math.Floor(dmg * 0.75m);

                    var reps = Math.Max(atk.Repeats, 1);
                    totalDmg += dmg * reps;
                    maxHits = Math.Max(maxHits, reps);
                }
            }
        }

        return new SnapshotEnemy
        {
            name = enemy.Name,
            hp = enemy.CurrentHp,
            max_hp = enemy.MaxHp,
            block = enemy.Block,
            vulnerable_turns = PowerAmount(enemy, "VulnerablePower"),
            weak_turns = weakPower,
            poison = PowerAmount(enemy, "PoisonPower"),
            intended_move = intentName,
            intended_damage = totalDmg,
            intended_hits = maxHits,
        };
    }

    private static SnapshotRelic BuildRelic(RelicModel relic)
    {
        return new SnapshotRelic
        {
            name = LocStr(relic.Title) ?? relic.GetType().Name,
            id = relic.GetType().Name,
            description = LocStr(relic.Description) ?? "",
            rarity = relic.Rarity.ToString().ToLowerInvariant(),
        };
    }

    private static string? LocStr(object? loc)
    {
        if (loc == null) return null;
        try
        {
            var m = loc.GetType().GetMethod("GetFormattedText", BindingFlags.Instance | BindingFlags.Public);
            if (m != null)
            {
                var s = m.Invoke(loc, null) as string;
                if (!string.IsNullOrEmpty(s) && !s.Contains("LocString")) return s;
            }
        }
        catch (Exception ex)
        {
            if (ex is System.Reflection.TargetInvocationException tie && tie.InnerException != null)
                Log.Error($"[BoberInSpire] LocStr: {tie.InnerException.Message}");
        }
        return null;
    }

    private static int PowerAmount(Creature? c, string typeName)
    {
        if (c == null) return 0;
        var p = c.Powers.FirstOrDefault(pw =>
            string.Equals(pw.GetType().Name, typeName, StringComparison.OrdinalIgnoreCase));
        return p?.Amount ?? 0;
    }

    internal sealed class Snapshot
    {
        public required SnapshotPlayer player { get; init; }
        public required List<SnapshotCard> hand { get; init; }
        public required List<SnapshotEnemy> enemies { get; init; }
        public required List<SnapshotRelic> relics { get; init; }
        public List<MerchantRelicSnapshot>? merchant_relics { get; init; }
        public required int turn { get; init; }
        public required int draw_pile_count { get; init; }
        public required int discard_pile_count { get; init; }
    }

    internal sealed class SnapshotPlayer
    {
        public required int energy { get; init; }
        public required int max_energy { get; init; }
        public required int strength { get; init; }
        public required int dexterity { get; init; }
        public required int vigor { get; init; }
        public required int weak_turns { get; init; }
        public int frail_turns { get; init; }
        public required int hp { get; init; }
        public required int max_hp { get; init; }
        public required int block { get; init; }
    }

    internal sealed class SnapshotCard
    {
        public required string name { get; init; }
        public required int damage { get; init; }
        public required int energy_cost { get; init; }
        public required string card_type { get; init; }
        public required int block { get; init; }
        public required int hits { get; init; }
        public required string id { get; init; }
        public string description { get; init; } = "";
    }

    internal sealed class SnapshotEnemy
    {
        public required string name { get; init; }
        public required int hp { get; init; }
        public required int max_hp { get; init; }
        public required int block { get; init; }
        public required int vulnerable_turns { get; init; }
        public required int weak_turns { get; init; }
        public int poison { get; init; }
        public required string intended_move { get; init; }
        public required int intended_damage { get; init; }
        public required int intended_hits { get; init; }
    }

    internal sealed class SnapshotRelic
    {
        public required string name { get; init; }
        public required string id { get; init; }
        public required string description { get; init; }
        public required string rarity { get; init; }
    }

    internal sealed class MerchantRelicSnapshot
    {
        public required string name { get; init; }
        public required string id { get; init; }
        public required string rarity { get; init; }
        public required int cost { get; init; }
    }
}
