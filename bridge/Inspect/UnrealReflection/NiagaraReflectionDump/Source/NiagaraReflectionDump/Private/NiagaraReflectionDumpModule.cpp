// Read-only reflection probe for the hybrid Rebirth Niagara fork.  This is
// intentionally a module rather than a commandlet: it introduces no UCLASS,
// and its only work is gated behind -NiagaraReflectionDump.

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"
#include "Misc/CommandLine.h"
#include "Misc/FileHelper.h"
#include "Misc/Parse.h"
#include "Misc/Paths.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"
#include "UObject/UnrealType.h"

namespace
{
    FString DescribeProperty(const FProperty* Property)
    {
        FString Description = Property->GetClass()->GetName();
        if (const FStructProperty* StructProperty = CastField<FStructProperty>(Property))
            Description += FString::Printf(TEXT("<%s>"), *StructProperty->Struct->GetName());
        else if (const FObjectPropertyBase* ObjectProperty = CastField<FObjectPropertyBase>(Property))
            Description += FString::Printf(TEXT("<%s>"), *ObjectProperty->PropertyClass->GetName());
        else if (const FEnumProperty* EnumProperty = CastField<FEnumProperty>(Property))
            Description += FString::Printf(TEXT("<%s>"), *EnumProperty->GetEnum()->GetName());
        else if (const FByteProperty* ByteProperty = CastField<FByteProperty>(Property))
        {
            if (ByteProperty->Enum)
                Description += FString::Printf(TEXT("<%s>"), *ByteProperty->Enum->GetName());
        }
        else if (const FArrayProperty* ArrayProperty = CastField<FArrayProperty>(Property))
            Description += FString::Printf(TEXT("<%s>"), *DescribeProperty(ArrayProperty->Inner));
        else if (const FSetProperty* SetProperty = CastField<FSetProperty>(Property))
            Description += FString::Printf(TEXT("<%s>"), *DescribeProperty(SetProperty->ElementProp));
        else if (const FMapProperty* MapProperty = CastField<FMapProperty>(Property))
            Description += FString::Printf(TEXT("<%s, %s>"), *DescribeProperty(MapProperty->KeyProp), *DescribeProperty(MapProperty->ValueProp));
        return Description;
    }

    TSharedPtr<FJsonObject> DescribeStruct(UStruct* Struct)
    {
        TSharedRef<FJsonObject> Result = MakeShared<FJsonObject>();
        Result->SetStringField(TEXT("path"), Struct ? Struct->GetPathName() : TEXT(""));
        if (!Struct)
            return Result;

        TArray<TSharedPtr<FJsonValue>> Properties;
        int32 TraversalIndex = 0;
        for (TFieldIterator<FProperty> It(Struct, EFieldIteratorFlags::IncludeSuper); It; ++It, ++TraversalIndex)
        {
            const FProperty* Property = *It;
            TSharedRef<FJsonObject> PropertyInfo = MakeShared<FJsonObject>();
            PropertyInfo->SetNumberField(TEXT("traversalIndex"), TraversalIndex);
            PropertyInfo->SetStringField(TEXT("name"), Property->GetName());
            PropertyInfo->SetStringField(TEXT("owner"), Property->GetOwnerStruct() ? Property->GetOwnerStruct()->GetPathName() : TEXT(""));
            PropertyInfo->SetStringField(TEXT("type"), DescribeProperty(Property));
            PropertyInfo->SetNumberField(TEXT("offset"), Property->GetOffset_ForInternal());
            PropertyInfo->SetNumberField(TEXT("arrayDim"), Property->ArrayDim);
            PropertyInfo->SetStringField(TEXT("flagsHex"), FString::Printf(TEXT("0x%llX"), static_cast<unsigned long long>(Property->PropertyFlags)));
            Properties.Add(MakeShared<FJsonValueObject>(PropertyInfo));
        }
        Result->SetArrayField(TEXT("propertiesInTFieldIteratorOrder"), Properties);
        return Result;
    }

    UClass* FindReflectedClass(const TCHAR* Path)
    {
        return LoadObject<UClass>(nullptr, Path);
    }

    UScriptStruct* FindReflectedScriptStruct(const TCHAR* Path)
    {
        return LoadObject<UScriptStruct>(nullptr, Path);
    }

    void WriteReflectionReport()
    {
        static const TCHAR* ClassPaths[] =
        {
            TEXT("/Script/Niagara.NiagaraSystem"),
            TEXT("/Script/Niagara.NiagaraEmitter"),
            TEXT("/Script/Niagara.NiagaraScript"),
            TEXT("/Script/Niagara.NiagaraMeshRendererProperties"),
            TEXT("/Script/Niagara.NiagaraSpriteRendererProperties"),
            TEXT("/Script/Niagara.NiagaraComponent"),
            TEXT("/Script/Engine.FXSystemAsset"),
            TEXT("/Script/VFXNiagara.VFXNiagaraDataInterfaceFunctionLibrary"),
            TEXT("/Script/VFXNiagara.VFXNiagaraDataInterfaceMaterial"),
            TEXT("/Script/VFXNiagara.VFXNiagaraDataInterfaceMaterialParameter"),
            TEXT("/Script/VFXNiagara.VFXNiagaraDataInterfaceSpawnEmitter"),
            TEXT("/Script/VFXNiagara.VFXNiagaraDataInterfaceNoiseCurve"),
            TEXT("/Script/EndGame.EndNiagaraDataInterfaceTransformContext"),
            TEXT("/Script/EndGame.EndNiagaraDataInterfaceFunctionLibrary"),
            TEXT("/Script/EndGame.EndNiagaraDataInterfaceLight"),
            TEXT("/Script/EndGame.EndNiagaraDataInterfaceTrail"),
            TEXT("/Script/EndGame.EndNiagaraDataInterfaceLensFlare"),
            TEXT("/Script/EndGame.EndNiagaraDataInterfacePostProcessParameter"),
        };
        static const TCHAR* StructPaths[] =
        {
            TEXT("/Script/Engine.EndEffectExtraData"),
            TEXT("/Script/VFXNiagara.VFXNiagaraCreateParams"),
            TEXT("/Script/VFXNiagara.VFXNiagaraParameterInfo"),
            TEXT("/Script/VFXNiagara.VFXNiagaraUserParameter"),
            TEXT("/Script/VFXNiagara.VFXNiagaraCharacterInfo"),
            TEXT("/Script/VFXNiagara.VFXRefActorTransformInfo"),
            TEXT("/Script/VFXNiagara.VFXMaterialScalarParameter"),
            TEXT("/Script/VFXNiagara.VFXMaterialVectorParameter"),
            TEXT("/Script/VFXNiagara.VFXMaterialTextureParameter"),
            TEXT("/Script/EndGame.EndEffectAttachInfo"),
        };

        TSharedRef<FJsonObject> Root = MakeShared<FJsonObject>();
        Root->SetStringField(TEXT("engineVersion"), FEngineVersion::Current().ToString());
        TArray<TSharedPtr<FJsonValue>> Classes;
        for (const TCHAR* ClassPath : ClassPaths)
            Classes.Add(MakeShared<FJsonValueObject>(DescribeStruct(FindReflectedClass(ClassPath))));
        Root->SetArrayField(TEXT("classes"), Classes);
        TArray<TSharedPtr<FJsonValue>> Structs;
        for (const TCHAR* StructPath : StructPaths)
            Structs.Add(MakeShared<FJsonValueObject>(DescribeStruct(FindReflectedScriptStruct(StructPath))));
        Root->SetArrayField(TEXT("structs"), Structs);

        FString Text;
        const TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Text);
        FJsonSerializer::Serialize(Root, Writer);
        const FString Output = FPaths::Combine(FPaths::ProjectSavedDir(), TEXT("NiagaraReflectionDump.json"));
        if (FFileHelper::SaveStringToFile(Text, *Output))
        {
            UE_LOG(LogTemp, Display, TEXT("Niagara reflection report: %s"), *Output);
        }
        else
        {
            UE_LOG(LogTemp, Error, TEXT("Could not write Niagara reflection report: %s"), *Output);
        }
    }
}

class FNiagaraReflectionDumpModule final : public IModuleInterface
{
public:
    virtual void StartupModule() override
    {
        if (FParse::Param(FCommandLine::Get(), TEXT("NiagaraReflectionDump")))
            WriteReflectionReport();
    }
};

IMPLEMENT_MODULE(FNiagaraReflectionDumpModule, NiagaraReflectionDump)
