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
            var relicNames = snapshot.relics?.Select(r => r.name).ToList() ?? new List<string>();
            RewardExporter.CacheFromCombat(snapshot.deck, snapshot.character, relicNames);

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
                try { handCards.Add(BuildCard(card, combat, player)); }
                catch (Exception ex) { Log.Error($"[BoberInSpire] BuildCard skip {card?.GetType().Name}: {ex.Message}"); }
            }
        }

        var deck = BuildDeckInternal(pcs, combat, player);
        var character = GetCharacterNameInternal(player);

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
            deck = deck,
            character = character,
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
            plating = PowerAmount(c, "PlatingPower"),
        };
    }

    private static int DynInt(DynamicVarSet vars, string key) =>
        vars.TryGetValue(key, out var v) ? v.IntValue : 0;

    /// <summary>
    /// Get the card model from a hand item. Hand may contain CardModel directly or a wrapper (e.g. CardInHand) with Model/CardModel property.
    /// </summary>
    private static CardModel? GetCardModel(object handItem)
    {
        if (handItem is CardModel cm)
            return cm;
        try
        {
            var t = handItem.GetType();
            foreach (var propName in new[] { "Model", "CardModel", "Card" })
            {
                var p = t.GetProperty(propName, BindingFlags.Public | BindingFlags.Instance);
                if (p?.GetValue(handItem) is CardModel m)
                    return m;
            }
        }
        catch (Exception ex)
        {
            Log.Error($"[BoberInSpire] GetCardModel: {ex.Message}");
        }
        return null;
    }

    /// <summary>
    /// Get current energy cost: first from the hand item (card instance often has Cost/CurrentCost), then from CardModel.
    /// So we respect Tezcatara's Ember and other in-combat cost modifiers.
    /// </summary>
    private static int GetCurrentEnergyCost(object handItem, CardModel? model, CombatState? combat, Player? player)
    {
        try
        {
            var t = handItem.GetType();
            foreach (var propName in new[] { "Cost", "CurrentCost", "EnergyCost" })
            {
                var p = t.GetProperty(propName, BindingFlags.Public | BindingFlags.Instance);
                if (p == null) continue;
                var val = p.GetValue(handItem);
                if (val is int i)
                    return i;
                if (val != null)
                {
                    var vt = val.GetType();
                    var vp = vt.GetProperty("Value", BindingFlags.Public | BindingFlags.Instance)
                        ?? vt.GetProperty("Current", BindingFlags.Public | BindingFlags.Instance)
                        ?? vt.GetProperty("Canonical", BindingFlags.Public | BindingFlags.Instance);
                    if (vp?.GetValue(val) is int j)
                        return j;
                }
            }
        }
        catch (Exception ex)
        {
            Log.Error($"[BoberInSpire] GetCurrentEnergyCost(handItem): {ex.Message}");
        }

        if (model != null)
        {
            var canonical = model.EnergyCost?.Canonical ?? 0;
            try
            {
                var ec = model.EnergyCost;
                if (ec != null)
                {
                    var et = ec.GetType();
                    foreach (var prop in new[] { "Value", "Current", "Effective", "IntValue" })
                    {
                        var ep = et.GetProperty(prop, BindingFlags.Public | BindingFlags.Instance);
                        if (ep != null && ep.PropertyType == typeof(int) && ep.GetValue(ec) is int k)
                            return k;
                    }
                }
                foreach (var methodName in new[] { "GetEnergyCost", "GetCost", "GetCurrentCost" })
                {
                    var m = model.GetType().GetMethod(methodName, BindingFlags.Public | BindingFlags.Instance,
                        null, new[] { typeof(CombatState) }, null);
                    if (m != null && combat != null && m.Invoke(model, new object[] { combat }) is int k)
                        return k;
                    m = model.GetType().GetMethod(methodName, BindingFlags.Public | BindingFlags.Instance,
                        null, new[] { typeof(Player) }, null);
                    if (m != null && player != null && m.Invoke(model, new object[] { player }) is int costPlayer)
                        return costPlayer;
                }
            }
            catch (Exception ex)
            {
                Log.Error($"[BoberInSpire] GetCurrentEnergyCost(model): {ex.Message}");
            }
            return canonical;
        }

        return 0;
    }

    private static SnapshotCard BuildCard(object handItem, CombatState? combat, Player? player)
    {
        var model = GetCardModel(handItem);
        if (model == null)
        {
            Log.Error("[BoberInSpire] BuildCard: could not get CardModel from hand item");
            return new SnapshotCard
            {
                name = "?", damage = 0, block = 0, hits = 1, energy_cost = 0,
                card_type = "skill", id = "?", description = "",
            };
        }

        var vars = model.DynamicVars;
        var description = TryGetCardDescription(model);
        var energyCost = GetCurrentEnergyCost(handItem, model, combat, player);
        return new SnapshotCard
        {
            name        = model.Title ?? model.GetType().Name,
            damage      = DynInt(vars, "Damage"),
            block       = DynInt(vars, "Block"),
            hits        = Math.Max(DynInt(vars, "Repeat"), 1),
            energy_cost = energyCost,
            card_type   = model.Type.ToString().ToLowerInvariant(),
            id          = model.GetType().Name,
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

        // Read enemy debuffs/buffs that affect their damage output
        var weakPower = PowerAmount(enemy, "WeakPower");
        var strengthPower = PowerAmount(enemy, "StrengthPower"); // can be negative (e.g. "decreases attack damage by 5")

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

                    // Apply Strength first (enemy can have negative Strength = reduced attack damage)
                    dmg = Math.Max(0, dmg + strengthPower);

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
            strength = strengthPower,
            poison = PowerAmount(enemy, "PoisonPower"),
            intended_move = intentName,
            intended_damage = totalDmg,
            intended_hits = maxHits,
        };
    }

    internal static List<string> BuildDeckInternal(PlayerCombatState? pcs, CombatState? combat, Player? player)
    {
        var names = new List<string>();
        if (pcs == null || combat == null || player == null) return names;

        foreach (var pile in new[] { pcs.Hand?.Cards, pcs.DrawPile?.Cards, pcs.DiscardPile?.Cards })
        {
            if (pile == null) continue;
            foreach (var item in pile)
            {
                try
                {
                    var model = GetCardModel(item);
                    if (model != null)
                    {
                        var title = model.Title ?? model.GetType().Name;
                        if (!string.IsNullOrEmpty(title)) names.Add(title);
                    }
                }
                catch { }
            }
        }
        return names;
    }

    internal static string GetCharacterNameInternal(Player? player)
    {
        if (player == null) return "Unknown";
        try
        {
            var t = player.GetType();
            var prop = t.GetProperty("CharacterType", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance)
                ?? t.GetProperty("Character", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Instance);
            if (prop?.GetValue(player) is { } val && val != null)
            {
                var s = val.ToString();
                if (!string.IsNullOrEmpty(s)) return s;
            }
            var baseType = t.BaseType?.Name ?? "";
            if (baseType.Contains("Ironclad")) return "Ironclad";
            if (baseType.Contains("Silent")) return "Silent";
            if (baseType.Contains("Defect")) return "Defect";
            if (baseType.Contains("Necrobinder")) return "Necrobinder";
            if (baseType.Contains("Regent")) return "Regent";
        }
        catch { }
        return "Unknown";
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
        public List<string> deck { get; init; } = new();
        public string character { get; init; } = "Unknown";
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
        public int plating { get; init; }
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
        public int strength { get; init; }
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
