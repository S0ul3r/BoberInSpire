using System.Text.Json;
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

    private static List<string> _cachedDeck = new();
    private static List<string> _cachedRelicNames = new();
    private static string _cachedCharacter = "Unknown";
    private static string? _rewardOutputPath;

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
    /// Export reward state when the card reward screen is shown.
    /// </summary>
    public static void ExportRewardState(IReadOnlyList<string> rewardOptions)
    {
        if (rewardOptions == null || rewardOptions.Count == 0) return;

        try
        {
            var snapshot = new RewardSnapshot
            {
                type = "card_reward",
                character = _cachedCharacter,
                deck = _cachedDeck.ToList(),
                relics = _cachedRelicNames.ToList(),
                options = rewardOptions.ToList(),
            };

            var json = JsonSerializer.Serialize(snapshot, JsonOpts);
            _rewardOutputPath ??= ProjectSettings.GlobalizePath("user://bober_reward_state.json");

            Task.Run(() =>
            {
                try { File.WriteAllText(_rewardOutputPath, json); }
                catch (Exception ex) { Log.Error($"[BoberInSpire] Reward export write failed: {ex.Message}"); }
            });

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
            }
        }
        catch { }
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
