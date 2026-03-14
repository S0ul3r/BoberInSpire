using HarmonyLib;
using MegaCrit.Sts2.Core.Modding;
using MegaCrit.Sts2.Core.Logging;

[ModInitializer("Initialize")]
public class ModEntry
{
    public static void Initialize()
    {
        var harmony = new Harmony("boberinspire.patch");
        harmony.PatchAll();
        Log.Info("[BoberInSpire] Harmony patches initialized.");
    }
}