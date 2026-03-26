using System.Collections.Concurrent;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using System.Diagnostics;
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
    private const int ThrottleMs = 450;
    private const int PerfLogIntervalMs = 5000;

    private static readonly JsonSerializerOptions JsonOpts = new() { WriteIndented = false };

    private static CombatState? _combat;
    private static string? _lastJson;
    private static long _lastWriteTicks;
    private static bool _pending;
    private static System.Threading.Timer? _debounceTimer;
    private static string? _outputPath;
    private static readonly object _writeQueueLock = new();
    private static string? _pendingWriteJson;
    private static int _writerActive;
    private static int _exportInProgress;
    private static long _perfNextLogTicks;
    private static long _perfExports;
    private static long _perfSkippedSameJson;
    private static long _perfDroppedBusy;
    private static long _perfBuildMsTotal;
    private static long _perfSerializeMsTotal;
    private static long _perfWriteMsTotal;

    private static List<SnapshotRelic>? _cachedRelics;
    private static int _cachedRelicCount = -1;

    private static List<MerchantRelicSnapshot>? _merchantRelics;

    /// <summary>Player used for map-mode shop JSON when there is no active combat state; refreshed when the shop closes.</summary>
    private static Player? _playerForLastMerchantMapExport;

    // Reflection caches — BuildSnapshot hot path (see [BoberInSpire][Perf] avg build_ms).
    private static readonly ConcurrentDictionary<Type, MethodInfo[]> _locFormattedTextMethods = new();
    private static readonly ConcurrentDictionary<Type, PropertyInfo?[]> _cardModelBridgeProps = new();
    private static readonly ConcurrentDictionary<Type, PropertyInfo?> _cardDescSourceProp = new();
    private static readonly ConcurrentDictionary<Type, PropertyInfo?> _relicDynamicVarsProp = new();
    private static readonly ConcurrentDictionary<Type, PropertyInfo?[]> _handEnergyCostProps = new();
    private static readonly ConcurrentDictionary<Type, PropertyInfo?[]> _nestedCostIntProps = new();
    private static readonly ConcurrentDictionary<Type, PropertyInfo?[]> _energyCostStructIntProps = new();
    private static readonly ConcurrentDictionary<Type, MethodInfo?[]> _modelCostInvokeListByType = new();
    private static readonly ConcurrentDictionary<Type, PropertyInfo?[]> _playerCharacterProps = new();

    public static void SetCombatState(CombatState? cs)
    {
        _combat = cs;
    }

    public static void SetMerchantRelics(MerchantInventory? inventory)
    {
        if (inventory == null)
        {
            _merchantRelics = null;
            if (_combat != null)
                RequestExport();
            else if (_playerForLastMerchantMapExport != null)
                TryExportMerchantMapSnapshot(_playerForLastMerchantMapExport);
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
            if (_combat != null)
                RequestExport();
            else if (inventory.Player != null)
                TryExportMerchantMapSnapshot(inventory.Player);
        }
        catch (Exception ex)
        {
            Log.Error($"[BoberInSpire] Merchant relic capture failed: {ex.Message}");
        }
    }

    public static void ClearMerchant()
    {
        _merchantRelics = null;
        if (_combat != null)
            RequestExport();
        else if (_playerForLastMerchantMapExport != null)
            TryExportMerchantMapSnapshot(_playerForLastMerchantMapExport);
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
            // Do not touch game / localization objects from the thread-pool — can deadlock or freeze.
            try
            {
                if (Engine.GetMainLoop() is SceneTree)
                    Callable.From(RunDebouncedExport).CallDeferred();
                else
                {
                    _pending = false;
                    DoExport();
                }
            }
            catch
            {
                _pending = false;
                DoExport();
            }
        }, null, ThrottleMs, System.Threading.Timeout.Infinite);
    }

    private static void RunDebouncedExport()
    {
        _pending = false;
        DoExport();
    }

    private static void DoExport()
    {
        if (_combat == null) return;
        if (Interlocked.Exchange(ref _exportInProgress, 1) == 1)
        {
            Interlocked.Increment(ref _perfDroppedBusy);
            return;
        }

        try
        {
            var player = _combat.Players.FirstOrDefault();
            if (player == null) return;

            var swBuild = Stopwatch.StartNew();
            var snapshot = BuildSnapshot(_combat, player);
            swBuild.Stop();
            Interlocked.Add(ref _perfBuildMsTotal, swBuild.ElapsedMilliseconds);
            WriteCombatSnapshot(snapshot);
        }
        catch (Exception ex)
        {
            Log.Error($"[BoberInSpire] Export failed: {ex.Message}");
        }
        finally
        {
            Interlocked.Exchange(ref _exportInProgress, 0);
        }
    }

    private static void WriteCombatSnapshot(Snapshot snapshot)
    {
        var relicNames = snapshot.relics?.Select(r => r.name).ToList() ?? new List<string>();
        RewardExporter.CacheFromCombat(snapshot.deck, snapshot.character, relicNames);

        var swSerialize = Stopwatch.StartNew();
        var json = JsonSerializer.Serialize(snapshot, JsonOpts);
        swSerialize.Stop();
        Interlocked.Add(ref _perfSerializeMsTotal, swSerialize.ElapsedMilliseconds);

        if (json == _lastJson)
        {
            Interlocked.Increment(ref _perfSkippedSameJson);
            MaybeLogPerf();
            return;
        }
        _lastJson = json;
        _lastWriteTicks = System.Environment.TickCount64;
        Interlocked.Increment(ref _perfExports);

        _outputPath ??= ProjectSettings.GlobalizePath("user://bober_combat_state.json");
        EnqueueWrite(json);
        MaybeLogPerf();
    }

    private static void EnqueueWrite(string json)
    {
        lock (_writeQueueLock)
        {
            _pendingWriteJson = json;
        }

        StartWriteWorkerIfNeeded();
    }

    private static void StartWriteWorkerIfNeeded()
    {
        if (Interlocked.CompareExchange(ref _writerActive, 1, 0) != 0) return;
        Task.Run(() =>
        {
            try
            {
                while (true)
                {
                    string? next;
                    lock (_writeQueueLock)
                    {
                        next = _pendingWriteJson;
                        _pendingWriteJson = null;
                    }

                    if (string.IsNullOrEmpty(next)) break;
                    var swWrite = Stopwatch.StartNew();
                    try { File.WriteAllText(_outputPath!, next); }
                    catch { }
                    swWrite.Stop();
                    Interlocked.Add(ref _perfWriteMsTotal, swWrite.ElapsedMilliseconds);
                }
            }
            finally
            {
                Interlocked.Exchange(ref _writerActive, 0);
                // If a new payload arrived after we drained the queue and before _writerActive flipped to 0,
                // start the writer loop again.
                if (_pendingWriteJson != null)
                {
                    StartWriteWorkerIfNeeded();
                }
            }
        });
    }

    private static void MaybeLogPerf()
    {
        var now = System.Environment.TickCount64;
        var next = Interlocked.Read(ref _perfNextLogTicks);
        if (now < next) return;
        if (Interlocked.CompareExchange(ref _perfNextLogTicks, now + PerfLogIntervalMs, next) != next) return;

        var exports = Interlocked.Read(ref _perfExports);
        var same = Interlocked.Read(ref _perfSkippedSameJson);
        var busy = Interlocked.Read(ref _perfDroppedBusy);
        var buildMs = Interlocked.Read(ref _perfBuildMsTotal);
        var serMs = Interlocked.Read(ref _perfSerializeMsTotal);
        var writeMs = Interlocked.Read(ref _perfWriteMsTotal);
        var avgBuild = exports > 0 ? (double)buildMs / exports : 0;
        var avgSer = exports > 0 ? (double)serMs / exports : 0;
        var avgWrite = exports > 0 ? (double)writeMs / exports : 0;
        Log.Info($"[BoberInSpire][Perf] combat exports={exports} same_json={same} dropped_busy={busy} avg_ms(build/serialize/write)={avgBuild:F1}/{avgSer:F1}/{avgWrite:F1}");
    }

    /// <summary>Shop on the map: no active <see cref="CombatState"/>, but overlay still needs player + master deck + merchant relics.</summary>
    private static void TryExportMerchantMapSnapshot(Player player)
    {
        try
        {
            _playerForLastMerchantMapExport = player;
            InvalidateRelicCache();
            var snapshot = BuildMerchantMapSnapshot(player);
            WriteCombatSnapshot(snapshot);
        }
        catch (Exception ex)
        {
            Log.Error($"[BoberInSpire] Merchant map export failed: {ex.Message}");
        }
    }

    private static Snapshot BuildMerchantMapSnapshot(Player player)
    {
        var pcs = player.PlayerCombatState;
        var relicCount = player.Relics.Count;

        _cachedRelics = new List<SnapshotRelic>();
        foreach (var r in player.Relics)
        {
            try { _cachedRelics.Add(BuildRelic(r)); }
            catch (Exception ex) { Log.Error($"[BoberInSpire] BuildRelic skip: {ex.Message}"); }
        }

        _cachedRelicCount = relicCount;

        var handCards = new List<SnapshotCard>();
        var hand = pcs?.Hand?.Cards;
        if (hand != null)
        {
            foreach (var card in hand)
            {
                try { handCards.Add(BuildCard(card, null, player)); }
                catch (Exception ex) { Log.Error($"[BoberInSpire] BuildCard skip {card?.GetType().Name}: {ex.Message}"); }
            }
        }

        return new Snapshot
        {
            player = BuildPlayer(player),
            hand = handCards,
            enemies = new List<SnapshotEnemy>(),
            relics = _cachedRelics,
            merchant_relics = _merchantRelics,
            turn = 0,
            draw_pile_count = pcs?.DrawPile?.Cards?.Count ?? 0,
            discard_pile_count = pcs?.DiscardPile?.Cards?.Count ?? 0,
            deck = BuildMasterDeckNames(player),
            character = GetCharacterNameInternal(player),
        };
    }

    private static List<string> BuildMasterDeckNames(Player player)
    {
        var names = new List<string>();
        try
        {
            var cards = player.Deck?.Cards;
            if (cards == null) return names;
            foreach (var item in cards)
            {
                var model = GetCardModel(item);
                if (model == null) continue;
                var title = model.Title ?? model.GetType().Name;
                if (!string.IsNullOrEmpty(title)) names.Add(title);
            }
        }
        catch (Exception ex)
        {
            Log.Error($"[BoberInSpire] BuildMasterDeckNames: {ex.Message}");
        }

        return names;
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

        var deck = BuildAdvisorDeckList(pcs, combat, player);
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
    private static PropertyInfo?[] CardModelBridgeProps(Type t) =>
        _cardModelBridgeProps.GetOrAdd(t, static type =>
        {
            var list = new List<PropertyInfo?>();
            foreach (var propName in new[] { "Model", "CardModel", "Card" })
            {
                var p = type.GetProperty(propName, BindingFlags.Public | BindingFlags.Instance);
                if (p != null) list.Add(p);
            }
            return list.Count > 0 ? list.ToArray() : Array.Empty<PropertyInfo?>();
        });

    private static CardModel? GetCardModel(object handItem)
    {
        if (handItem is CardModel cm)
            return cm;
        try
        {
            var t = handItem.GetType();
            foreach (var p in CardModelBridgeProps(t))
            {
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
    private static PropertyInfo?[] HandEnergyCostProps(Type t) =>
        _handEnergyCostProps.GetOrAdd(t, static type =>
        {
            var list = new List<PropertyInfo?>();
            foreach (var propName in new[] { "Cost", "CurrentCost", "EnergyCost" })
            {
                var p = type.GetProperty(propName, BindingFlags.Public | BindingFlags.Instance);
                if (p != null) list.Add(p);
            }
            return list.Count > 0 ? list.ToArray() : Array.Empty<PropertyInfo?>();
        });

    private static PropertyInfo?[] NestedIntProps(Type vt) =>
        _nestedCostIntProps.GetOrAdd(vt, static type =>
        {
            var list = new List<PropertyInfo?>();
            foreach (var name in new[] { "Value", "Current", "Canonical" })
            {
                var p = type.GetProperty(name, BindingFlags.Public | BindingFlags.Instance);
                if (p != null) list.Add(p);
            }
            return list.Count > 0 ? list.ToArray() : Array.Empty<PropertyInfo?>();
        });

    private static PropertyInfo?[] EnergyCostStructIntProps(Type et) =>
        _energyCostStructIntProps.GetOrAdd(et, static type =>
        {
            var list = new List<PropertyInfo?>();
            foreach (var prop in new[] { "Value", "Current", "Effective", "IntValue" })
            {
                var ep = type.GetProperty(prop, BindingFlags.Public | BindingFlags.Instance);
                if (ep != null && ep.PropertyType == typeof(int))
                    list.Add(ep);
            }
            return list.Count > 0 ? list.ToArray() : Array.Empty<PropertyInfo?>();
        });

    /// <summary>Per model type: GetEnergyCost(CS), GetEnergyCost(P), GetCost(CS), GetCost(P), GetCurrentCost(CS), GetCurrentCost(P).</summary>
    private static MethodInfo?[] ModelCostInvokeList(Type modelType) =>
        _modelCostInvokeListByType.GetOrAdd(modelType, static t =>
        {
            var list = new List<MethodInfo?>();
            foreach (var methodName in new[] { "GetEnergyCost", "GetCost", "GetCurrentCost" })
            {
                list.Add(t.GetMethod(methodName, BindingFlags.Public | BindingFlags.Instance,
                    null, new[] { typeof(CombatState) }, null));
                list.Add(t.GetMethod(methodName, BindingFlags.Public | BindingFlags.Instance,
                    null, new[] { typeof(Player) }, null));
            }
            return list.ToArray();
        });

    private static int GetCurrentEnergyCost(object handItem, CardModel? model, CombatState? combat, Player? player)
    {
        try
        {
            var t = handItem.GetType();
            foreach (var p in HandEnergyCostProps(t))
            {
                if (p == null) continue;
                var val = p.GetValue(handItem);
                if (val is int i)
                    return i;
                if (val != null)
                {
                    var vt = val.GetType();
                    foreach (var vp in NestedIntProps(vt))
                    {
                        if (vp?.GetValue(val) is int j)
                            return j;
                    }
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
                    foreach (var ep in EnergyCostStructIntProps(et))
                    {
                        if (ep?.GetValue(ec) is int k)
                            return k;
                    }
                }
                var methods = ModelCostInvokeList(model.GetType());
                for (var i = 0; i < methods.Length; i++)
                {
                    var m = methods[i];
                    if (m == null) continue;
                    if (i % 2 == 0)
                    {
                        if (combat != null && m.Invoke(model, new object[] { combat }) is int k)
                            return k;
                    }
                    else
                    {
                        if (player != null && m.Invoke(model, new object[] { player }) is int costPlayer)
                            return costPlayer;
                    }
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
        var description = TryGetCardDescription(model, vars);
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

    private static PropertyInfo? CardDescSourceProp(Type cardType) =>
        _cardDescSourceProp.GetOrAdd(cardType, static t =>
        {
            foreach (var n in new[] { "Description", "Body", "BodyText" })
            {
                var p = t.GetProperty(n, BindingFlags.Public | BindingFlags.Instance);
                if (p != null) return p;
            }
            return null;
        });

    private static string? TryGetCardDescription(CardModel card, DynamicVarSet vars)
    {
        try
        {
            var desc = CardDescSourceProp(card.GetType())?.GetValue(card);
            // GetFormattedText() with no args leaves template variables empty → parse errors on {Damage:diff()} etc.
            return desc != null ? LocStr(desc, vars) : null;
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

    /// <summary>
    /// Cards currently in combat zones (hand, draw, discard, exhaust). Omits draw pile cards not yet in these piles.
    /// Prefer <see cref="BuildAdvisorDeckList"/> for reward-overlay deck synergy.
    /// </summary>
    internal static List<string> BuildDeckInternal(PlayerCombatState? pcs, CombatState? combat, Player? player)
    {
        var names = new List<string>();
        if (pcs == null || combat == null || player == null) return names;

        foreach (var pile in new[] { pcs.Hand?.Cards, pcs.DrawPile?.Cards, pcs.DiscardPile?.Cards, pcs.ExhaustPile?.Cards })
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

    /// <summary>
    /// Full run deck for card advisor: <see cref="Player.Deck"/> when populated; otherwise combat piles (including exhaust).
    /// </summary>
    internal static List<string> BuildAdvisorDeckList(PlayerCombatState? pcs, CombatState? combat, Player? player)
    {
        var master = player != null ? BuildMasterDeckNames(player) : new List<string>();
        if (master.Count > 0)
            return master;
        return BuildDeckInternal(pcs, combat, player);
    }

    private static PropertyInfo?[] PlayerCharacterProps(Type t) =>
        _playerCharacterProps.GetOrAdd(t, static type =>
        {
            var a = type.GetProperty("CharacterType", BindingFlags.Public | BindingFlags.Instance);
            var b = type.GetProperty("Character", BindingFlags.Public | BindingFlags.Instance);
            return new[] { a, b };
        });

    internal static string GetCharacterNameInternal(Player? player)
    {
        if (player == null) return "Unknown";
        try
        {
            var t = player.GetType();
            foreach (var prop in PlayerCharacterProps(t))
            {
                if (prop?.GetValue(player) is { } val && val != null)
                {
                    var s = val.ToString();
                    if (!string.IsNullOrEmpty(s)) return s;
                }
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
        var relicVars = TryRelicDynamicVars(relic);
        return new SnapshotRelic
        {
            name = LocStr(relic.Title) ?? relic.GetType().Name,
            id = relic.GetType().Name,
            description = LocStr(relic.Description, relicVars) ?? "",
            rarity = relic.Rarity.ToString().ToLowerInvariant(),
        };
    }

    private static DynamicVarSet? TryRelicDynamicVars(RelicModel relic)
    {
        try
        {
            var p = _relicDynamicVarsProp.GetOrAdd(relic.GetType(), static t =>
                t.GetProperty("DynamicVars", BindingFlags.Public | BindingFlags.Instance));
            return p?.GetValue(relic) as DynamicVarSet;
        }
        catch
        {
            return null;
        }
    }

    /// <summary>
    /// Resolve localized strings. Card/relic bodies need <see cref="DynamicVarSet"/> so templates like
    /// <c>{Damage:diff()}</c> format; parameterless <c>GetFormattedText()</c> triggers game errors and heavy log spam.
    /// </summary>
    private static MethodInfo[] LocFormattedTextMethods(Type type) =>
        _locFormattedTextMethods.GetOrAdd(type, static t =>
            t.GetMethods(BindingFlags.Instance | BindingFlags.Public)
                .Where(m => m.Name == "GetFormattedText" && m.ReturnType == typeof(string))
                .ToArray());

    private static string? LocStr(object? loc, DynamicVarSet? vars = null)
    {
        if (loc == null) return null;
        var type = loc.GetType();
        var methods = LocFormattedTextMethods(type);

        if (vars != null)
        {
            foreach (var m in methods)
            {
                var ps = m.GetParameters();
                if (ps.Length != 1 || !ps[0].ParameterType.IsInstanceOfType(vars)) continue;
                try
                {
                    if (m.Invoke(loc, new object[] { vars }) is string s
                        && !string.IsNullOrEmpty(s)
                        && !s.Contains("LocString"))
                        return s;
                }
                catch
                {
                    // Wrong overload or game version mismatch — try others / fall back.
                }
            }
        }

        foreach (var m in methods)
        {
            if (m.GetParameters().Length != 0) continue;
            try
            {
                if (m.Invoke(loc, null) is string s
                    && !string.IsNullOrEmpty(s)
                    && !s.Contains("LocString"))
                    return s;
            }
            catch
            {
                // Avoid per-call Log.Error: thousands of lines can stall the game.
            }
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
