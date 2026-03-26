using System.Text.Json;
using System.Diagnostics;
using Godot;
using MegaCrit.Sts2.Core.Logging;

namespace FirstMod;

/// <summary>
/// Exports card reward screen data (deck, relics, offered cards) for the overlay advisor.
/// Triggered when the post-combat card reward screen opens.
/// </summary>
public static class RewardExporter
{
    private static readonly JsonSerializerOptions JsonOpts = new() { WriteIndented = false };
    private const int PerfLogIntervalMs = 5000;

    private static List<string> _cachedDeck = new();
    private static List<string> _cachedRelicNames = new();
    private static string _cachedCharacter = "Unknown";
    private static string? _rewardOutputPath;
    private static string? _lastRewardJson;
    private static readonly object _writeQueueLock = new();
    private static string? _pendingWriteJson;
    private static int _writerActive;
    private static long _perfExports;
    private static long _perfSkippedSameJson;
    private static long _perfWriteMsTotal;
    private static long _perfNextLogTicks;

    /// <summary>
    /// Call from CombatExporter when we have valid combat state - cache deck/relics/character for reward export.
    /// </summary>
    public static void CacheFromCombat(IReadOnlyList<string> deck, string character, IReadOnlyList<string> relicNames)
    {
        if (deck != null) _cachedDeck = deck.ToList();
        if (!string.IsNullOrEmpty(character)) _cachedCharacter = character;
        if (relicNames != null) _cachedRelicNames = relicNames.ToList();
    }

    /// <summary>
    /// Export reward / shop card-pick state for the overlay advisor.
    /// <paramref name="screenType"/> is <c>card_reward</c> (post-combat) or <c>merchant_cards</c> (shop).
    /// </summary>
    public static void ExportRewardState(IReadOnlyList<string> rewardOptions, string screenType = "card_reward")
    {
        if (rewardOptions == null || rewardOptions.Count == 0) return;

        try
        {
            var snapshot = new RewardSnapshot
            {
                type = screenType,
                character = _cachedCharacter,
                deck = _cachedDeck.ToList(),
                relics = _cachedRelicNames.ToList(),
                options = rewardOptions.ToList(),
            };

            var json = JsonSerializer.Serialize(snapshot, JsonOpts);
            if (json == _lastRewardJson)
            {
                Interlocked.Increment(ref _perfSkippedSameJson);
                MaybeLogPerf();
                return;
            }
            _lastRewardJson = json;
            _rewardOutputPath ??= ProjectSettings.GlobalizePath("user://bober_reward_state.json");
            Interlocked.Increment(ref _perfExports);
            EnqueueWrite(json);
            MaybeLogPerf();

            Log.Info($"[BoberInSpire] Reward state exported: {rewardOptions.Count} options");
        }
        catch (Exception ex)
        {
            Log.Error($"[BoberInSpire] Reward export failed: {ex.Message}");
        }
    }

    /// <summary>
    /// Clear reward state when the reward screen is closed (e.g. after picking or skipping).
    /// </summary>
    public static void ClearRewardState()
    {
        try
        {
            _rewardOutputPath ??= ProjectSettings.GlobalizePath("user://bober_reward_state.json");
            if (File.Exists(_rewardOutputPath))
            {
                File.WriteAllText(_rewardOutputPath, "{}");
                _lastRewardJson = "{}";
            }
        }
        catch { }
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
                    var sw = Stopwatch.StartNew();
                    try { File.WriteAllText(_rewardOutputPath!, next); }
                    catch (Exception ex) { Log.Error($"[BoberInSpire] Reward export write failed: {ex.Message}"); }
                    sw.Stop();
                    Interlocked.Add(ref _perfWriteMsTotal, sw.ElapsedMilliseconds);
                }
            }
            finally
            {
                Interlocked.Exchange(ref _writerActive, 0);
                if (_pendingWriteJson != null)
                    StartWriteWorkerIfNeeded();
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
        var writeMs = Interlocked.Read(ref _perfWriteMsTotal);
        var avgWrite = exports > 0 ? (double)writeMs / exports : 0;
        Log.Info($"[BoberInSpire][Perf] rewards exports={exports} same_json={same} avg_write_ms={avgWrite:F1}");
    }

    internal sealed class RewardSnapshot
    {
        public string type { get; init; } = "card_reward";
        public string character { get; init; } = "Unknown";
        public List<string> deck { get; init; } = new();
        public List<string> relics { get; init; } = new();
        public List<string> options { get; init; } = new();
    }

}
