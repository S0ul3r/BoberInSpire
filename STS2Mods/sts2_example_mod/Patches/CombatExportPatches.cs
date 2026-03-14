using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Logging;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes.Screens.Shops;

namespace FirstMod.Patches;

[HarmonyPatch]
public static class CombatExportPatches
{
    [HarmonyPatch(typeof(Player), nameof(Player.PopulateCombatState))]
    [HarmonyPostfix]
    public static void AfterPopulateCombatState(Player __instance)
    {
        CombatExporter.RequestExportFrom(__instance);
    }

    [HarmonyPatch(typeof(CombatState), nameof(CombatState.AddCreature), new[] { typeof(Creature) })]
    [HarmonyPostfix]
    public static void AfterAddCreature(CombatState __instance)
    {
        CombatExporter.SetCombatState(__instance);
        CombatExporter.RequestExport();
    }

    [HarmonyPatch(typeof(CombatState), nameof(CombatState.RemoveCreature), new[] { typeof(Creature), typeof(bool) })]
    [HarmonyPostfix]
    public static void AfterRemoveCreature(CombatState __instance)
    {
        CombatExporter.RequestExport();
    }

    [HarmonyPatch(typeof(CombatState), "set_CurrentSide")]
    [HarmonyPostfix]
    public static void AfterSideChanged(CombatState __instance)
    {
        CombatExporter.SetCombatState(__instance);
        CombatExporter.RequestExport();
    }

    [HarmonyPatch(typeof(CombatState), "set_RoundNumber")]
    [HarmonyPostfix]
    public static void AfterRoundChanged(CombatState __instance)
    {
        CombatExporter.RequestExport();
    }

    [HarmonyPatch(typeof(PlayerCombatState), "set_Energy")]
    [HarmonyPostfix]
    public static void AfterEnergyChanged(PlayerCombatState __instance)
    {
        try
        {
            var field = typeof(PlayerCombatState).GetField("_player",
                System.Reflection.BindingFlags.Instance | System.Reflection.BindingFlags.NonPublic);
            if (field?.GetValue(__instance) is Player player)
                CombatExporter.RequestExportFrom(player);
        }
        catch (Exception ex)
        {
            Log.Error($"[BoberInSpire] Energy patch: {ex.Message}");
        }
    }

    [HarmonyPatch(typeof(CardPile), nameof(CardPile.InvokeContentsChanged))]
    [HarmonyPostfix]
    public static void AfterCardPileChanged()
    {
        CombatExporter.RequestExport();
    }

    [HarmonyPatch(typeof(NMerchantInventory), nameof(NMerchantInventory.Open))]
    [HarmonyPostfix]
    public static void AfterMerchantOpen(NMerchantInventory __instance)
    {
        try
        {
            CombatExporter.SetMerchantRelics(__instance.Inventory);
        }
        catch (Exception ex)
        {
            Log.Error($"[BoberInSpire] Merchant open patch: {ex.Message}");
        }
    }

    [HarmonyPatch(typeof(NMerchantInventory), "Close")]
    [HarmonyPostfix]
    public static void AfterMerchantClose()
    {
        CombatExporter.ClearMerchant();
    }
}
