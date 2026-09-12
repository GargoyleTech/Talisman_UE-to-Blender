using UnrealBuildTool;

public class NiagaraReflectionDump : ModuleRules
{
    public NiagaraReflectionDump(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
        PrivateDependencyModuleNames.AddRange(new[]
        {
            "Core",
            "CoreUObject",
            "Engine",
            "Json",
            "JsonUtilities",
            "Niagara",
            "VFXNiagara",
        });
    }
}
