# Material MCP Expansion — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Expand unreal-material-mcp from 28 to 48 tools with a MaterialMCPReader C++ plugin for native-speed operations.

**Architecture:** Three pillars — (1) MaterialMCPReader C++ plugin in UE project providing native expression iteration, property reflection, graph serialization, preview rendering, and undo support; (2) 12 new structured Python tools for creation, wiring, inspection, validation, graph transfer; (3) 8 procedural Python tools for batch graph building, templates, previews, and auto-builders. Python helpers detect C++ plugin and use fast path when available, falling back to pure-Python.

**Tech Stack:** C++ (UE 5.7 Editor plugin), Python 3.11+ (FastMCP server), UE MaterialEditingLibrary, UE Python Remote Execution protocol.

**Design doc:** `D:/Unreal Projects/Leviathan/Docs/plans/2026-03-05-material-mcp-expansion-design.md`

**Server location:** `C:/Users/lucas/AppData/Local/Temp/unreal-material-mcp/`
**UE project:** `D:/Unreal Projects/Leviathan/`

**Test command:** `cd /c/Users/lucas/AppData/Local/Temp/unreal-material-mcp && uv run pytest tests/ -v`
**Build command (C++):** Use `trigger_build` MCP tool (editor must be open)

---

## Phase 1: MaterialMCPReader C++ Plugin

### Task 1: Plugin Scaffolding

**Files:**
- Create: `D:/Unreal Projects/Leviathan/Plugins/MaterialMCPReader/MaterialMCPReader.uplugin`
- Create: `D:/Unreal Projects/Leviathan/Plugins/MaterialMCPReader/Source/MaterialMCPReader/MaterialMCPReader.Build.cs`
- Create: `D:/Unreal Projects/Leviathan/Plugins/MaterialMCPReader/Source/MaterialMCPReader/Public/MaterialMCPReaderModule.h`
- Create: `D:/Unreal Projects/Leviathan/Plugins/MaterialMCPReader/Source/MaterialMCPReader/Private/MaterialMCPReaderModule.cpp`
- Create: `D:/Unreal Projects/Leviathan/Plugins/MaterialMCPReader/Source/MaterialMCPReader/Public/MaterialMCPReaderLibrary.h`
- Create: `D:/Unreal Projects/Leviathan/Plugins/MaterialMCPReader/Source/MaterialMCPReader/Private/MaterialMCPReaderLibrary.cpp`

**Step 1: Create .uplugin**

```json
{
    "FileVersion": 3,
    "Version": 1,
    "VersionName": "1.0",
    "FriendlyName": "Material MCP Reader",
    "Description": "C++ companion plugin for unreal-material MCP server. Provides native expression iteration, property reflection, graph serialization, and preview rendering.",
    "Category": "Editor",
    "CreatedBy": "Leviathan",
    "EnabledByDefault": true,
    "CanContainContent": false,
    "Modules": [
        {
            "Name": "MaterialMCPReader",
            "Type": "Editor",
            "LoadingPhase": "Default"
        }
    ]
}
```

**Step 2: Create Build.cs**

```csharp
using UnrealBuildTool;

public class MaterialMCPReader : ModuleRules
{
    public MaterialMCPReader(ReadOnlyTargetRules Target) : base(Target)
    {
        PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

        PublicDependencyModuleNames.AddRange(new string[]
        {
            "Core",
            "CoreUObject",
            "Engine",
        });

        PrivateDependencyModuleNames.AddRange(new string[]
        {
            "UnrealEd",
            "MaterialEditor",
            "RenderCore",
            "RHI",
            "Slate",
            "SlateCore",
            "Json",
            "JsonUtilities",
        });
    }
}
```

**Step 3: Create module header/cpp (minimal IModuleInterface)**

`MaterialMCPReaderModule.h`:
```cpp
#pragma once
#include "Modules/ModuleManager.h"

class FMaterialMCPReaderModule : public IModuleInterface
{
public:
    virtual void StartupModule() override;
    virtual void ShutdownModule() override;
};
```

`MaterialMCPReaderModule.cpp`:
```cpp
#include "MaterialMCPReaderModule.h"

#define LOCTEXT_NAMESPACE "FMaterialMCPReaderModule"

void FMaterialMCPReaderModule::StartupModule() {}
void FMaterialMCPReaderModule::ShutdownModule() {}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FMaterialMCPReaderModule, MaterialMCPReader)
```

**Step 4: Create empty library header**

`MaterialMCPReaderLibrary.h`:
```cpp
#pragma once
#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "MaterialMCPReaderLibrary.generated.h"

UCLASS()
class MATERIALMCPREADER_API UMaterialMCPReaderLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()
};
```

`MaterialMCPReaderLibrary.cpp`:
```cpp
#include "MaterialMCPReaderLibrary.h"
```

**Step 5: Build and verify plugin loads**

Trigger Live Coding build via `trigger_build`. Check build succeeds. Verify in editor Output Log that MaterialMCPReader module loads.

**Step 6: Commit**
```bash
cd "D:/Unreal Projects/Leviathan"
# Use diversion
/c/Users/lucas/.diversion/bin/dv.exe commit -a -m "feat: scaffold MaterialMCPReader plugin"
```

---

### Task 2: GetAllExpressions — Native Expression Iteration

**Files:**
- Modify: `D:/Unreal Projects/Leviathan/Plugins/MaterialMCPReader/Source/MaterialMCPReader/Public/MaterialMCPReaderLibrary.h`
- Modify: `D:/Unreal Projects/Leviathan/Plugins/MaterialMCPReader/Source/MaterialMCPReader/Private/MaterialMCPReaderLibrary.cpp`

**Step 1: Add GetAllExpressions declaration**

In `MaterialMCPReaderLibrary.h`, add:
```cpp
#pragma once
#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "MaterialMCPReaderLibrary.generated.h"

UCLASS()
class MATERIALMCPREADER_API UMaterialMCPReaderLibrary : public UBlueprintFunctionLibrary
{
    GENERATED_BODY()

public:
    /** Returns JSON array of all expressions in a material with class, name, position, and key properties. */
    UFUNCTION(BlueprintCallable, Category = "MaterialMCPReader")
    static FString GetAllExpressions(const FString& AssetPath);

private:
    /** Load a material asset, returns nullptr on failure. */
    static UMaterial* LoadBaseMaterial(const FString& AssetPath);

    /** Serialize an expression's key properties to JSON. */
    static TSharedPtr<FJsonObject> SerializeExpression(UMaterialExpression* Expr);
};
```

**Step 2: Implement GetAllExpressions**

In `MaterialMCPReaderLibrary.cpp`:
```cpp
#include "MaterialMCPReaderLibrary.h"
#include "Materials/Material.h"
#include "Materials/MaterialExpression.h"
#include "Materials/MaterialExpressionParameter.h"
#include "Materials/MaterialExpressionTextureBase.h"
#include "Materials/MaterialExpressionTextureSampleParameter.h"
#include "Materials/MaterialExpressionCustom.h"
#include "Materials/MaterialExpressionComment.h"
#include "Materials/MaterialExpressionMaterialFunctionCall.h"
#include "Materials/MaterialFunction.h"
#include "EditorAssetLibrary.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

UMaterial* UMaterialMCPReaderLibrary::LoadBaseMaterial(const FString& AssetPath)
{
    UObject* Obj = UEditorAssetLibrary::LoadAsset(AssetPath);
    return Cast<UMaterial>(Obj);
}

TSharedPtr<FJsonObject> UMaterialMCPReaderLibrary::SerializeExpression(UMaterialExpression* Expr)
{
    auto JsonExpr = MakeShared<FJsonObject>();
    JsonExpr->SetStringField(TEXT("name"), Expr->GetName());
    JsonExpr->SetStringField(TEXT("class"), Expr->GetClass()->GetName());
    JsonExpr->SetNumberField(TEXT("pos_x"), Expr->MaterialExpressionEditorX);
    JsonExpr->SetNumberField(TEXT("pos_y"), Expr->MaterialExpressionEditorY);

    // Parameter name
    if (UMaterialExpressionParameter* Param = Cast<UMaterialExpressionParameter>(Expr))
    {
        JsonExpr->SetStringField(TEXT("parameter_name"), Param->ParameterName.ToString());
    }
    else if (UMaterialExpressionTextureSampleParameter* TexParam = Cast<UMaterialExpressionTextureSampleParameter>(Expr))
    {
        JsonExpr->SetStringField(TEXT("parameter_name"), TexParam->ParameterName.ToString());
        if (TexParam->Texture)
        {
            JsonExpr->SetStringField(TEXT("texture"), TexParam->Texture->GetPathName());
        }
    }

    // Texture on non-parameter texture nodes
    if (UMaterialExpressionTextureBase* TexBase = Cast<UMaterialExpressionTextureBase>(Expr))
    {
        if (TexBase->Texture)
        {
            JsonExpr->SetStringField(TEXT("texture"), TexBase->Texture->GetPathName());
        }
    }

    // Custom HLSL
    if (UMaterialExpressionCustom* Custom = Cast<UMaterialExpressionCustom>(Expr))
    {
        JsonExpr->SetStringField(TEXT("description"), Custom->Description);
        FString CodePreview = Custom->Code.Left(100);
        JsonExpr->SetStringField(TEXT("code"), CodePreview);
    }

    // Comment
    if (UMaterialExpressionComment* Comment = Cast<UMaterialExpressionComment>(Expr))
    {
        JsonExpr->SetStringField(TEXT("text"), Comment->Text);
    }

    // Material function call
    if (UMaterialExpressionMaterialFunctionCall* FuncCall = Cast<UMaterialExpressionMaterialFunctionCall>(Expr))
    {
        if (FuncCall->MaterialFunction)
        {
            JsonExpr->SetStringField(TEXT("function"), FuncCall->MaterialFunction->GetPathName());
        }
    }

    return JsonExpr;
}

FString UMaterialMCPReaderLibrary::GetAllExpressions(const FString& AssetPath)
{
    auto ResultJson = MakeShared<FJsonObject>();

    UMaterial* Mat = LoadBaseMaterial(AssetPath);
    if (!Mat)
    {
        ResultJson->SetBoolField(TEXT("success"), false);
        ResultJson->SetStringField(TEXT("error"), FString::Printf(TEXT("Material not found or not a base Material: %s"), *AssetPath));
        FString Output;
        auto Writer = TJsonWriterFactory<>::Create(&Output);
        FJsonSerializer::Serialize(ResultJson, Writer);
        return Output;
    }

    ResultJson->SetBoolField(TEXT("success"), true);
    ResultJson->SetStringField(TEXT("asset_path"), AssetPath);

    TArray<TSharedPtr<FJsonValue>> ExprArray;

    // Direct iteration — the whole point of the C++ plugin
    for (UMaterialExpression* Expr : Mat->GetExpressions())
    {
        if (!Expr) continue;
        auto JsonExpr = SerializeExpression(Expr);
        ExprArray.Add(MakeShared<FJsonValueObject>(JsonExpr));
    }

    ResultJson->SetNumberField(TEXT("expression_count"), ExprArray.Num());
    ResultJson->SetArrayField(TEXT("expressions"), ExprArray);

    FString Output;
    auto Writer = TJsonWriterFactory<>::Create(&Output);
    FJsonSerializer::Serialize(ResultJson, Writer);
    return Output;
}
```

**Step 3: Build and verify**

Trigger Live Coding build. Test via Python Remote Execution:
```python
result = unreal.MaterialMCPReaderLibrary.get_all_expressions("/Game/Materials/M_Test")
print(result)
```

**Step 4: Commit**
```bash
/c/Users/lucas/.diversion/bin/dv.exe commit -a -m "feat(MaterialMCPReader): add GetAllExpressions — native expression iteration"
```

---

### Task 3: GetExpressionDetails — Full Property Reflection

**Files:**
- Modify: `MaterialMCPReaderLibrary.h`
- Modify: `MaterialMCPReaderLibrary.cpp`

**Step 1: Add declaration**

```cpp
/** Returns JSON with full property dump of a single expression: all UProperties, input pins, output pins. */
UFUNCTION(BlueprintCallable, Category = "MaterialMCPReader")
static FString GetExpressionDetails(const FString& AssetPath, const FString& ExpressionName);
```

**Step 2: Implement**

```cpp
FString UMaterialMCPReaderLibrary::GetExpressionDetails(const FString& AssetPath, const FString& ExpressionName)
{
    auto ResultJson = MakeShared<FJsonObject>();

    UMaterial* Mat = LoadBaseMaterial(AssetPath);
    if (!Mat)
    {
        ResultJson->SetBoolField(TEXT("success"), false);
        ResultJson->SetStringField(TEXT("error"), TEXT("Material not found"));
        FString Output;
        auto Writer = TJsonWriterFactory<>::Create(&Output);
        FJsonSerializer::Serialize(ResultJson, Writer);
        return Output;
    }

    // Find expression by name
    UMaterialExpression* FoundExpr = nullptr;
    for (UMaterialExpression* Expr : Mat->GetExpressions())
    {
        if (Expr && Expr->GetName() == ExpressionName)
        {
            FoundExpr = Expr;
            break;
        }
    }

    if (!FoundExpr)
    {
        ResultJson->SetBoolField(TEXT("success"), false);
        ResultJson->SetStringField(TEXT("error"), FString::Printf(TEXT("Expression not found: %s"), *ExpressionName));
        FString Output;
        auto Writer = TJsonWriterFactory<>::Create(&Output);
        FJsonSerializer::Serialize(ResultJson, Writer);
        return Output;
    }

    ResultJson->SetBoolField(TEXT("success"), true);
    ResultJson->SetStringField(TEXT("asset_path"), AssetPath);
    ResultJson->SetStringField(TEXT("expression_name"), ExpressionName);
    ResultJson->SetStringField(TEXT("class"), FoundExpr->GetClass()->GetName());

    // Enumerate ALL UProperties via reflection
    auto PropsJson = MakeShared<FJsonObject>();
    for (TFieldIterator<FProperty> PropIt(FoundExpr->GetClass()); PropIt; ++PropIt)
    {
        FProperty* Prop = *PropIt;
        if (!Prop) continue;

        // Skip internal/transient properties
        if (Prop->HasAnyPropertyFlags(CPF_Transient | CPF_DuplicateTransient))
            continue;

        FString ValueStr;
        const void* ValuePtr = Prop->ContainerPtrToValuePtr<void>(FoundExpr);
        Prop->ExportTextItem_Direct(ValueStr, ValuePtr, nullptr, nullptr, PPF_None);

        if (!ValueStr.IsEmpty())
        {
            PropsJson->SetStringField(Prop->GetName(), ValueStr);
        }
    }
    ResultJson->SetObjectField(TEXT("properties"), PropsJson);

    // Input pins
    TArray<TSharedPtr<FJsonValue>> InputsArray;
    const TArray<FExpressionInput*> Inputs = FoundExpr->GetInputs();
    for (int32 i = 0; i < Inputs.Num(); i++)
    {
        FExpressionInput* Input = Inputs[i];
        auto InputJson = MakeShared<FJsonObject>();
        InputJson->SetStringField(TEXT("name"), FoundExpr->GetInputName(i).ToString());
        InputJson->SetBoolField(TEXT("connected"), Input->Expression != nullptr);
        if (Input->Expression)
        {
            InputJson->SetStringField(TEXT("connected_to"), Input->Expression->GetName());
            InputJson->SetNumberField(TEXT("output_index"), Input->OutputIndex);
        }
        InputsArray.Add(MakeShared<FJsonValueObject>(InputJson));
    }
    ResultJson->SetArrayField(TEXT("inputs"), InputsArray);

    // Output pins
    TArray<TSharedPtr<FJsonValue>> OutputsArray;
    TArray<FExpressionOutput>& Outputs = FoundExpr->GetOutputs();
    for (const FExpressionOutput& Output : Outputs)
    {
        auto OutputJson = MakeShared<FJsonObject>();
        OutputJson->SetStringField(TEXT("name"), Output.OutputName.ToString());
        OutputsArray.Add(MakeShared<FJsonValueObject>(OutputJson));
    }
    ResultJson->SetArrayField(TEXT("outputs"), OutputsArray);

    FString Output;
    auto Writer = TJsonWriterFactory<>::Create(&Output);
    FJsonSerializer::Serialize(ResultJson, Writer);
    return Output;
}
```

**Step 3: Build, test via Python, commit**

---

### Task 4: GetFullConnectionGraph — Complete Wire Map

**Files:**
- Modify: `MaterialMCPReaderLibrary.h`
- Modify: `MaterialMCPReaderLibrary.cpp`

**Step 1: Add declaration**

```cpp
/** Returns JSON with complete connection graph: every expression and every wire. */
UFUNCTION(BlueprintCallable, Category = "MaterialMCPReader")
static FString GetFullConnectionGraph(const FString& AssetPath);
```

**Step 2: Implement**

```cpp
FString UMaterialMCPReaderLibrary::GetFullConnectionGraph(const FString& AssetPath)
{
    auto ResultJson = MakeShared<FJsonObject>();

    UMaterial* Mat = LoadBaseMaterial(AssetPath);
    if (!Mat)
    {
        ResultJson->SetBoolField(TEXT("success"), false);
        ResultJson->SetStringField(TEXT("error"), TEXT("Material not found"));
        FString Output;
        auto Writer = TJsonWriterFactory<>::Create(&Output);
        FJsonSerializer::Serialize(ResultJson, Writer);
        return Output;
    }

    ResultJson->SetBoolField(TEXT("success"), true);
    ResultJson->SetStringField(TEXT("asset_path"), AssetPath);

    // All wires
    TArray<TSharedPtr<FJsonValue>> ConnectionsArray;

    for (UMaterialExpression* Expr : Mat->GetExpressions())
    {
        if (!Expr) continue;

        const TArray<FExpressionInput*> Inputs = Expr->GetInputs();
        for (int32 i = 0; i < Inputs.Num(); i++)
        {
            FExpressionInput* Input = Inputs[i];
            if (!Input->Expression) continue;

            auto ConnJson = MakeShared<FJsonObject>();
            ConnJson->SetStringField(TEXT("from"), Input->Expression->GetName());
            ConnJson->SetNumberField(TEXT("from_output_index"), Input->OutputIndex);

            // Get output pin name
            TArray<FExpressionOutput>& FromOutputs = Input->Expression->GetOutputs();
            if (FromOutputs.IsValidIndex(Input->OutputIndex))
            {
                ConnJson->SetStringField(TEXT("from_output"), FromOutputs[Input->OutputIndex].OutputName.ToString());
            }

            ConnJson->SetStringField(TEXT("to"), Expr->GetName());
            ConnJson->SetStringField(TEXT("to_input"), Expr->GetInputName(i).ToString());

            ConnectionsArray.Add(MakeShared<FJsonValueObject>(ConnJson));
        }
    }
    ResultJson->SetArrayField(TEXT("connections"), ConnectionsArray);

    // Material output connections
    TArray<TSharedPtr<FJsonValue>> MaterialOutputs;
    struct FMatPropEntry { const TCHAR* Label; EMaterialProperty Prop; };
    static const FMatPropEntry MatProps[] = {
        {TEXT("BaseColor"), MP_BaseColor},
        {TEXT("Metallic"), MP_Metallic},
        {TEXT("Specular"), MP_Specular},
        {TEXT("Roughness"), MP_Roughness},
        {TEXT("Anisotropy"), MP_Anisotropy},
        {TEXT("EmissiveColor"), MP_EmissiveColor},
        {TEXT("Opacity"), MP_Opacity},
        {TEXT("OpacityMask"), MP_OpacityMask},
        {TEXT("Normal"), MP_Normal},
        {TEXT("WorldPositionOffset"), MP_WorldPositionOffset},
        {TEXT("SubsurfaceColor"), MP_SubsurfaceColor},
        {TEXT("AmbientOcclusion"), MP_AmbientOcclusion},
        {TEXT("Refraction"), MP_Refraction},
        {TEXT("PixelDepthOffset"), MP_PixelDepthOffset},
        {TEXT("ShadingModelFromMaterialExpression"), MP_ShadingModel},
    };

    for (const auto& Entry : MatProps)
    {
        FExpressionInput* Input = Mat->GetExpressionInputForProperty(Entry.Prop);
        if (Input && Input->Expression)
        {
            auto OutJson = MakeShared<FJsonObject>();
            OutJson->SetStringField(TEXT("property"), Entry.Label);
            OutJson->SetStringField(TEXT("expression"), Input->Expression->GetName());
            OutJson->SetNumberField(TEXT("output_index"), Input->OutputIndex);
            MaterialOutputs.Add(MakeShared<FJsonValueObject>(OutJson));
        }
    }
    ResultJson->SetArrayField(TEXT("material_outputs"), MaterialOutputs);

    FString Output;
    auto Writer = TJsonWriterFactory<>::Create(&Output);
    FJsonSerializer::Serialize(ResultJson, Writer);
    return Output;
}
```

**Step 3: Build, test, commit**

---

### Task 5: DisconnectExpression

**Files:**
- Modify: `MaterialMCPReaderLibrary.h`
- Modify: `MaterialMCPReaderLibrary.cpp`

**Step 1: Add declaration**

```cpp
/** Disconnect wires on an expression. If InputName is empty, disconnects all inputs. If bDisconnectOutputs, disconnects downstream instead. */
UFUNCTION(BlueprintCallable, Category = "MaterialMCPReader")
static FString DisconnectExpression(const FString& AssetPath, const FString& ExpressionName,
    const FString& InputName, bool bDisconnectOutputs);
```

**Step 2: Implement**

```cpp
FString UMaterialMCPReaderLibrary::DisconnectExpression(const FString& AssetPath,
    const FString& ExpressionName, const FString& InputName, bool bDisconnectOutputs)
{
    auto ResultJson = MakeShared<FJsonObject>();

    UMaterial* Mat = LoadBaseMaterial(AssetPath);
    if (!Mat)
    {
        ResultJson->SetBoolField(TEXT("success"), false);
        ResultJson->SetStringField(TEXT("error"), TEXT("Material not found"));
        FString Output;
        auto Writer = TJsonWriterFactory<>::Create(&Output);
        FJsonSerializer::Serialize(ResultJson, Writer);
        return Output;
    }

    UMaterialExpression* TargetExpr = nullptr;
    for (UMaterialExpression* Expr : Mat->GetExpressions())
    {
        if (Expr && Expr->GetName() == ExpressionName)
        {
            TargetExpr = Expr;
            break;
        }
    }

    if (!TargetExpr)
    {
        ResultJson->SetBoolField(TEXT("success"), false);
        ResultJson->SetStringField(TEXT("error"), FString::Printf(TEXT("Expression not found: %s"), *ExpressionName));
        FString Output;
        auto Writer = TJsonWriterFactory<>::Create(&Output);
        FJsonSerializer::Serialize(ResultJson, Writer);
        return Output;
    }

    TArray<TSharedPtr<FJsonValue>> DisconnectedArray;
    Mat->Modify();

    if (!bDisconnectOutputs)
    {
        // Disconnect inputs on this expression
        const TArray<FExpressionInput*> Inputs = TargetExpr->GetInputs();
        for (int32 i = 0; i < Inputs.Num(); i++)
        {
            FExpressionInput* Input = Inputs[i];
            FString PinName = TargetExpr->GetInputName(i).ToString();

            if (!InputName.IsEmpty() && PinName != InputName)
                continue;

            if (Input->Expression)
            {
                auto DisconnJson = MakeShared<FJsonObject>();
                DisconnJson->SetStringField(TEXT("pin"), PinName);
                DisconnJson->SetStringField(TEXT("was_connected_to"), Input->Expression->GetName());
                DisconnectedArray.Add(MakeShared<FJsonValueObject>(DisconnJson));

                Input->Expression = nullptr;
                Input->OutputIndex = 0;
            }
        }
    }
    else
    {
        // Disconnect all downstream references to this expression
        for (UMaterialExpression* Expr : Mat->GetExpressions())
        {
            if (!Expr || Expr == TargetExpr) continue;

            const TArray<FExpressionInput*> Inputs = Expr->GetInputs();
            for (int32 i = 0; i < Inputs.Num(); i++)
            {
                if (Inputs[i]->Expression == TargetExpr)
                {
                    auto DisconnJson = MakeShared<FJsonObject>();
                    DisconnJson->SetStringField(TEXT("expression"), Expr->GetName());
                    DisconnJson->SetStringField(TEXT("pin"), Expr->GetInputName(i).ToString());
                    DisconnectedArray.Add(MakeShared<FJsonValueObject>(DisconnJson));

                    Inputs[i]->Expression = nullptr;
                    Inputs[i]->OutputIndex = 0;
                }
            }
        }
    }

    ResultJson->SetBoolField(TEXT("success"), true);
    ResultJson->SetStringField(TEXT("asset_path"), AssetPath);
    ResultJson->SetArrayField(TEXT("disconnected"), DisconnectedArray);
    ResultJson->SetNumberField(TEXT("count"), DisconnectedArray.Num());

    FString Output;
    auto Writer = TJsonWriterFactory<>::Create(&Output);
    FJsonSerializer::Serialize(ResultJson, Writer);
    return Output;
}
```

**Step 3: Build, test, commit**

---

### Task 6: BuildMaterialGraph — Native-Speed Batch Graph Builder

**Files:**
- Modify: `MaterialMCPReaderLibrary.h`
- Modify: `MaterialMCPReaderLibrary.cpp`

This is the most complex C++ function. It takes a JSON graph spec and creates all nodes + wires in a single undo transaction.

**Step 1: Add declarations**

```cpp
/** Build entire graph from JSON spec in a single undo transaction. */
UFUNCTION(BlueprintCallable, Category = "MaterialMCPReader")
static FString BuildMaterialGraph(const FString& AssetPath, const FString& GraphSpecJson, bool bClearExisting);

/** Begin a named undo transaction for batching edits. */
UFUNCTION(BlueprintCallable, Category = "MaterialMCPReader")
static void BeginMaterialTransaction(const FString& TransactionName);

/** End the current undo transaction. */
UFUNCTION(BlueprintCallable, Category = "MaterialMCPReader")
static void EndMaterialTransaction();
```

**Step 2: Implement transaction helpers**

```cpp
void UMaterialMCPReaderLibrary::BeginMaterialTransaction(const FString& TransactionName)
{
    GEditor->BeginTransaction(*TransactionName);
}

void UMaterialMCPReaderLibrary::EndMaterialTransaction()
{
    GEditor->EndTransaction();
}
```

**Step 3: Implement BuildMaterialGraph**

```cpp
FString UMaterialMCPReaderLibrary::BuildMaterialGraph(const FString& AssetPath,
    const FString& GraphSpecJson, bool bClearExisting)
{
    auto ResultJson = MakeShared<FJsonObject>();

    UMaterial* Mat = LoadBaseMaterial(AssetPath);
    if (!Mat)
    {
        ResultJson->SetBoolField(TEXT("success"), false);
        ResultJson->SetStringField(TEXT("error"), TEXT("Material not found"));
        FString Output;
        auto Writer = TJsonWriterFactory<>::Create(&Output);
        FJsonSerializer::Serialize(ResultJson, Writer);
        return Output;
    }

    // Parse the graph spec
    TSharedPtr<FJsonObject> SpecJson;
    auto Reader = TJsonReaderFactory<>::Create(GraphSpecJson);
    if (!FJsonSerializer::Deserialize(Reader, SpecJson) || !SpecJson.IsValid())
    {
        ResultJson->SetBoolField(TEXT("success"), false);
        ResultJson->SetStringField(TEXT("error"), TEXT("Invalid graph spec JSON"));
        FString Output;
        auto Writer = TJsonWriterFactory<>::Create(&Output);
        FJsonSerializer::Serialize(ResultJson, Writer);
        return Output;
    }

    GEditor->BeginTransaction(TEXT("Build Material Graph"));
    Mat->Modify();

    // Clear existing if requested
    if (bClearExisting)
    {
        TArray<UMaterialExpression*> ToDelete;
        for (UMaterialExpression* Expr : Mat->GetExpressions())
        {
            if (Expr) ToDelete.Add(Expr);
        }
        UMaterialEditingLibrary* MEL = nullptr;
        // Use MEL to properly delete expressions
        for (UMaterialExpression* Expr : ToDelete)
        {
            UMaterialEditingLibrary::DeleteMaterialExpression(Mat, Expr);
        }
    }

    // ID -> created expression mapping
    TMap<FString, UMaterialExpression*> IdToExpr;
    TArray<TSharedPtr<FJsonValue>> Errors;

    // Phase 1: Create all nodes
    const TArray<TSharedPtr<FJsonValue>>* NodesArray;
    if (SpecJson->TryGetArrayField(TEXT("nodes"), NodesArray))
    {
        for (const auto& NodeVal : *NodesArray)
        {
            auto NodeJson = NodeVal->AsObject();
            if (!NodeJson) continue;

            FString Id = NodeJson->GetStringField(TEXT("id"));
            FString ClassName = NodeJson->GetStringField(TEXT("class"));

            // Resolve class
            FString FullClassName = FString::Printf(TEXT("MaterialExpression%s"), *ClassName);
            UClass* ExprClass = FindObject<UClass>(ANY_PACKAGE, *FullClassName);
            if (!ExprClass)
            {
                auto ErrJson = MakeShared<FJsonObject>();
                ErrJson->SetStringField(TEXT("id"), Id);
                ErrJson->SetStringField(TEXT("error"), FString::Printf(TEXT("Unknown class: %s"), *FullClassName));
                Errors.Add(MakeShared<FJsonValueObject>(ErrJson));
                continue;
            }

            // Position
            const TArray<TSharedPtr<FJsonValue>>* PosArray;
            int32 PosX = 0, PosY = 0;
            if (NodeJson->TryGetArrayField(TEXT("pos"), PosArray) && PosArray->Num() >= 2)
            {
                PosX = (int32)(*PosArray)[0]->AsNumber();
                PosY = (int32)(*PosArray)[1]->AsNumber();
            }

            UMaterialExpression* NewExpr = UMaterialEditingLibrary::CreateMaterialExpression(
                Mat, ExprClass, PosX, PosY);

            if (!NewExpr)
            {
                auto ErrJson = MakeShared<FJsonObject>();
                ErrJson->SetStringField(TEXT("id"), Id);
                ErrJson->SetStringField(TEXT("error"), TEXT("Failed to create expression"));
                Errors.Add(MakeShared<FJsonValueObject>(ErrJson));
                continue;
            }

            // Set properties
            const TSharedPtr<FJsonObject>* PropsObj;
            if (NodeJson->TryGetObjectField(TEXT("props"), PropsObj))
            {
                for (auto& Pair : (*PropsObj)->Values)
                {
                    FProperty* Prop = NewExpr->GetClass()->FindPropertyByName(*Pair.Key);
                    if (!Prop) continue;

                    // Handle common property types
                    if (Pair.Value->Type == EJson::String)
                    {
                        FString StrVal = Pair.Value->AsString();
                        Prop->ImportText_Direct(*StrVal, Prop->ContainerPtrToValuePtr<void>(NewExpr), NewExpr, PPF_None);
                    }
                    else if (Pair.Value->Type == EJson::Number)
                    {
                        double NumVal = Pair.Value->AsNumber();
                        if (FFloatProperty* FloatProp = CastField<FFloatProperty>(Prop))
                        {
                            FloatProp->SetPropertyValue_InContainer(NewExpr, (float)NumVal);
                        }
                        else if (FDoubleProperty* DoubleProp = CastField<FDoubleProperty>(Prop))
                        {
                            DoubleProp->SetPropertyValue_InContainer(NewExpr, NumVal);
                        }
                        else if (FIntProperty* IntProp = CastField<FIntProperty>(Prop))
                        {
                            IntProp->SetPropertyValue_InContainer(NewExpr, (int32)NumVal);
                        }
                    }
                    else if (Pair.Value->Type == EJson::Boolean)
                    {
                        if (FBoolProperty* BoolProp = CastField<FBoolProperty>(Prop))
                        {
                            BoolProp->SetPropertyValue_InContainer(NewExpr, Pair.Value->AsBool());
                        }
                    }
                }
            }

            IdToExpr.Add(Id, NewExpr);
        }
    }

    // Phase 2: Create custom HLSL nodes (need special input/output array handling)
    const TArray<TSharedPtr<FJsonValue>>* CustomNodes;
    if (SpecJson->TryGetArrayField(TEXT("custom_hlsl_nodes"), CustomNodes))
    {
        for (const auto& NodeVal : *CustomNodes)
        {
            auto NodeJson = NodeVal->AsObject();
            if (!NodeJson) continue;

            FString Id = NodeJson->GetStringField(TEXT("id"));

            const TArray<TSharedPtr<FJsonValue>>* PosArray;
            int32 PosX = 0, PosY = 0;
            if (NodeJson->TryGetArrayField(TEXT("pos"), PosArray) && PosArray->Num() >= 2)
            {
                PosX = (int32)(*PosArray)[0]->AsNumber();
                PosY = (int32)(*PosArray)[1]->AsNumber();
            }

            UMaterialExpressionCustom* CustomExpr = Cast<UMaterialExpressionCustom>(
                UMaterialEditingLibrary::CreateMaterialExpression(
                    Mat, UMaterialExpressionCustom::StaticClass(), PosX, PosY));

            if (!CustomExpr)
            {
                auto ErrJson = MakeShared<FJsonObject>();
                ErrJson->SetStringField(TEXT("id"), Id);
                ErrJson->SetStringField(TEXT("error"), TEXT("Failed to create Custom HLSL node"));
                Errors.Add(MakeShared<FJsonValueObject>(ErrJson));
                continue;
            }

            CustomExpr->Code = NodeJson->GetStringField(TEXT("code"));
            CustomExpr->Description = NodeJson->GetStringField(TEXT("description"));

            // Output type
            FString OutTypeStr = NodeJson->GetStringField(TEXT("output_type"));
            if (OutTypeStr == TEXT("CMOT_FLOAT1")) CustomExpr->OutputType = CMOT_Float1;
            else if (OutTypeStr == TEXT("CMOT_FLOAT2")) CustomExpr->OutputType = CMOT_Float2;
            else if (OutTypeStr == TEXT("CMOT_FLOAT3")) CustomExpr->OutputType = CMOT_Float3;
            else if (OutTypeStr == TEXT("CMOT_FLOAT4")) CustomExpr->OutputType = CMOT_Float4;

            // Inputs
            const TArray<TSharedPtr<FJsonValue>>* InputsArr;
            if (NodeJson->TryGetArrayField(TEXT("inputs"), InputsArr))
            {
                CustomExpr->Inputs.Empty();
                for (const auto& InVal : *InputsArr)
                {
                    auto InJson = InVal->AsObject();
                    FCustomInput NewInput;
                    NewInput.InputName = FName(*InJson->GetStringField(TEXT("name")));
                    CustomExpr->Inputs.Add(NewInput);
                }
            }

            // Additional outputs
            const TArray<TSharedPtr<FJsonValue>>* AdditionalOutArr;
            if (NodeJson->TryGetArrayField(TEXT("additional_outputs"), AdditionalOutArr))
            {
                CustomExpr->AdditionalOutputs.Empty();
                for (const auto& OutVal : *AdditionalOutArr)
                {
                    auto OutJson = OutVal->AsObject();
                    FCustomOutput NewOutput;
                    NewOutput.OutputName = FName(*OutJson->GetStringField(TEXT("name")));
                    FString TypeStr = OutJson->GetStringField(TEXT("type"));
                    if (TypeStr == TEXT("CMOT_FLOAT1")) NewOutput.OutputType = CMOT_Float1;
                    else if (TypeStr == TEXT("CMOT_FLOAT2")) NewOutput.OutputType = CMOT_Float2;
                    else if (TypeStr == TEXT("CMOT_FLOAT3")) NewOutput.OutputType = CMOT_Float3;
                    else if (TypeStr == TEXT("CMOT_FLOAT4")) NewOutput.OutputType = CMOT_Float4;
                    CustomExpr->AdditionalOutputs.Add(NewOutput);
                }
            }

            IdToExpr.Add(Id, CustomExpr);
        }
    }

    // Phase 3: Wire connections
    int32 ConnectionCount = 0;
    const TArray<TSharedPtr<FJsonValue>>* ConnsArray;
    if (SpecJson->TryGetArrayField(TEXT("connections"), ConnsArray))
    {
        for (const auto& ConnVal : *ConnsArray)
        {
            auto ConnJson = ConnVal->AsObject();
            if (!ConnJson) continue;

            FString FromId = ConnJson->GetStringField(TEXT("from"));
            FString ToId = ConnJson->GetStringField(TEXT("to"));
            FString FromPin = ConnJson->GetStringField(TEXT("from_pin"));
            FString ToPin = ConnJson->GetStringField(TEXT("to_pin"));

            UMaterialExpression** FromExprPtr = IdToExpr.Find(FromId);
            UMaterialExpression** ToExprPtr = IdToExpr.Find(ToId);

            if (!FromExprPtr || !ToExprPtr)
            {
                auto ErrJson = MakeShared<FJsonObject>();
                ErrJson->SetStringField(TEXT("connection"), FString::Printf(TEXT("%s -> %s"), *FromId, *ToId));
                ErrJson->SetStringField(TEXT("error"), TEXT("Node not found"));
                Errors.Add(MakeShared<FJsonValueObject>(ErrJson));
                continue;
            }

            bool Ok = UMaterialEditingLibrary::ConnectMaterialExpressions(
                *FromExprPtr, FName(*FromPin), *ToExprPtr, FName(*ToPin));

            if (Ok) ConnectionCount++;
        }
    }

    // Phase 4: Wire material outputs
    const TArray<TSharedPtr<FJsonValue>>* OutputsArr;
    if (SpecJson->TryGetArrayField(TEXT("outputs"), OutputsArr))
    {
        // Map labels to EMaterialProperty
        static const TMap<FString, EMaterialProperty> PropMap = {
            {TEXT("BaseColor"), MP_BaseColor},
            {TEXT("Metallic"), MP_Metallic},
            {TEXT("Specular"), MP_Specular},
            {TEXT("Roughness"), MP_Roughness},
            {TEXT("EmissiveColor"), MP_EmissiveColor},
            {TEXT("Opacity"), MP_Opacity},
            {TEXT("OpacityMask"), MP_OpacityMask},
            {TEXT("Normal"), MP_Normal},
            {TEXT("WorldPositionOffset"), MP_WorldPositionOffset},
            {TEXT("AmbientOcclusion"), MP_AmbientOcclusion},
            {TEXT("Refraction"), MP_Refraction},
            {TEXT("SubsurfaceColor"), MP_SubsurfaceColor},
            {TEXT("PixelDepthOffset"), MP_PixelDepthOffset},
        };

        for (const auto& OutVal : *OutputsArr)
        {
            auto OutJson = OutVal->AsObject();
            if (!OutJson) continue;

            FString FromId = OutJson->GetStringField(TEXT("from"));
            FString FromPin = OutJson->GetStringField(TEXT("from_pin"));
            FString ToProp = OutJson->GetStringField(TEXT("to_property"));

            UMaterialExpression** FromExprPtr = IdToExpr.Find(FromId);
            const EMaterialProperty* MatProp = PropMap.Find(ToProp);

            if (FromExprPtr && MatProp)
            {
                UMaterialEditingLibrary::ConnectMaterialProperty(
                    *FromExprPtr, FName(*FromPin), *MatProp);
                ConnectionCount++;
            }
        }
    }

    GEditor->EndTransaction();

    // Build result with ID -> actual name mapping
    auto MappingJson = MakeShared<FJsonObject>();
    for (auto& Pair : IdToExpr)
    {
        if (Pair.Value)
        {
            MappingJson->SetStringField(Pair.Key, Pair.Value->GetName());
        }
    }

    ResultJson->SetBoolField(TEXT("success"), true);
    ResultJson->SetStringField(TEXT("asset_path"), AssetPath);
    ResultJson->SetObjectField(TEXT("id_to_name"), MappingJson);
    ResultJson->SetNumberField(TEXT("nodes_created"), IdToExpr.Num());
    ResultJson->SetNumberField(TEXT("connections_made"), ConnectionCount);
    if (Errors.Num() > 0)
    {
        ResultJson->SetArrayField(TEXT("errors"), Errors);
    }

    FString Output;
    auto Writer = TJsonWriterFactory<>::Create(&Output);
    FJsonSerializer::Serialize(ResultJson, Writer);
    return Output;
}
```

**Step 4: Build, test with a simple graph spec, commit**

---

### Task 7: ExportMaterialGraph & ImportMaterialGraph

**Files:**
- Modify: `MaterialMCPReaderLibrary.h`
- Modify: `MaterialMCPReaderLibrary.cpp`

**Step 1: Add declarations**

```cpp
/** Export complete material graph to JSON string. */
UFUNCTION(BlueprintCallable, Category = "MaterialMCPReader")
static FString ExportMaterialGraph(const FString& AssetPath);

/** Import material graph from JSON string. Mode: "overwrite" or "merge". */
UFUNCTION(BlueprintCallable, Category = "MaterialMCPReader")
static FString ImportMaterialGraph(const FString& AssetPath, const FString& GraphJson, const FString& Mode);
```

**Step 2: Implement ExportMaterialGraph**

Uses `GetAllExpressions` + `GetFullConnectionGraph` logic combined, plus material properties export. Serializes everything into the graph spec format so it can be round-tripped through `BuildMaterialGraph`.

Key logic:
- Iterate all expressions, serialize each with full properties via reflection
- Iterate all connections via `FExpressionInput`
- Capture material output connections
- Capture material-level properties (blend mode, shading model, etc.)
- Return as JSON matching the `build_material_graph` spec format

**Step 3: Implement ImportMaterialGraph**

- Parse the graph JSON
- If mode == "overwrite": delete all existing expressions
- If mode == "merge": offset positions by +500 on X
- Call `BuildMaterialGraph` logic internally
- Return results

**Step 4: Build, test round-trip (export → import into new material → compare), commit**

---

### Task 8: ValidateMaterial

**Files:**
- Modify: `MaterialMCPReaderLibrary.h`
- Modify: `MaterialMCPReaderLibrary.cpp`

**Step 1: Add declaration**

```cpp
/** Validate material graph health: islands, broken refs, naming conflicts, unused params. */
UFUNCTION(BlueprintCallable, Category = "MaterialMCPReader")
static FString ValidateMaterial(const FString& AssetPath, bool bFixIssues);
```

**Step 2: Implement**

Checks:
1. **Disconnected islands** — BFS from material outputs, mark reachable expressions. Anything not reachable is an island. If `bFixIssues`, delete islands (except Comments).
2. **Broken texture refs** — Texture parameters/samples pointing to null textures.
3. **Duplicate parameter names** — Two different parameter expressions with the same name.
4. **Missing material functions** — `MaterialFunctionCall` with null function reference.
5. **Unused parameters** — Parameter nodes not connected to any output path.
6. **Expression count warning** — Flag if >200 expressions (performance concern).

Each issue gets a severity (error/warning/info) and description.

**Step 3: Build, test, commit**

---

### Task 9: RenderMaterialPreview & GetMaterialThumbnail

**Files:**
- Modify: `MaterialMCPReaderLibrary.h`
- Modify: `MaterialMCPReaderLibrary.cpp`

**Step 1: Add declarations**

```cpp
/** Render material preview to a PNG file in Saved/MaterialMCP/previews/. */
UFUNCTION(BlueprintCallable, Category = "MaterialMCPReader")
static FString RenderMaterialPreview(const FString& AssetPath, int32 Resolution);

/** Get material thumbnail image. */
UFUNCTION(BlueprintCallable, Category = "MaterialMCPReader")
static FString GetMaterialThumbnail(const FString& AssetPath, int32 Resolution);
```

**Step 2: Implement using FObjectThumbnail**

Uses `ThumbnailTools::RenderThumbnail()` to generate a preview image, then saves to PNG in `{ProjectDir}/Saved/MaterialMCP/previews/`. Returns the file path.

Note: This requires `#include "ThumbnailRendering/ThumbnailManager.h"` and possibly `ThumbnailRendering` module dependency in Build.cs.

**Step 3: Build, test, commit**

---

### Task 10: CreateCustomHLSLNode & GetMaterialLayerInfo

**Files:**
- Modify: `MaterialMCPReaderLibrary.h`
- Modify: `MaterialMCPReaderLibrary.cpp`

**Step 1: Add declarations**

```cpp
/** Create a Custom HLSL expression node with inputs, outputs, and code in one call. */
UFUNCTION(BlueprintCallable, Category = "MaterialMCPReader")
static FString CreateCustomHLSLNode(const FString& AssetPath, const FString& Code,
    const FString& Description, const FString& OutputType,
    const FString& InputsJson, const FString& AdditionalOutputsJson,
    int32 PosX, int32 PosY);

/** Get Material Layer or Material Layer Blend info. */
UFUNCTION(BlueprintCallable, Category = "MaterialMCPReader")
static FString GetMaterialLayerInfo(const FString& AssetPath);
```

**Step 2: Implement CreateCustomHLSLNode** (extracted from BuildMaterialGraph's custom node logic into standalone function)

**Step 3: Implement GetMaterialLayerInfo**
- Load asset, check if `UMaterialFunctionMaterialLayer` or `UMaterialFunctionMaterialLayerBlend`
- Enumerate expressions, inputs, outputs
- Report layer type and parameters

**Step 4: Build, test, commit**

---

## Phase 2: Python MCP Server — New Structured Tools (12)

### Task 11: C++ Plugin Detection in material_helpers.py

**Files:**
- Modify: `C:/Users/lucas/AppData/Local/Temp/unreal-material-mcp/src/unreal_material_mcp/helpers/material_helpers.py`

**Step 1: Add detection function at top of helpers**

After the existing `_eal()` function, add:
```python
def _has_cpp_plugin():
    """Check if MaterialMCPReader C++ plugin is available."""
    try:
        return hasattr(unreal, 'MaterialMCPReaderLibrary')
    except Exception:
        return False

def _cpp():
    """Return MaterialMCPReaderLibrary (lazy)."""
    return unreal.MaterialMCPReaderLibrary
```

**Step 2: Update `scan_all_expressions` with fast path**

Add at the top of the function body:
```python
def scan_all_expressions(asset_path, class_filter=None):
    try:
        # Fast path: C++ plugin
        if _has_cpp_plugin():
            raw = _cpp().get_all_expressions(asset_path)
            data = json.loads(raw)
            if not data.get('success'):
                return raw
            if class_filter:
                data['expressions'] = [
                    e for e in data.get('expressions', [])
                    if class_filter.lower() in e.get('class', '').lower()
                ]
                data['found_expression_count'] = len(data['expressions'])
            else:
                data['found_expression_count'] = len(data.get('expressions', []))
            data['expected_expression_count'] = data.get('expression_count', -1)
            return json.dumps(data)

        # Slow path: brute-force scan (existing code below)
        ...
```

**Step 3: Run existing tests to verify no regressions**

```bash
cd /c/Users/lucas/AppData/Local/Temp/unreal-material-mcp && uv run pytest tests/ -v
```

**Step 4: Commit**

---

### Task 12: Helper Functions for New Structured Tools

**Files:**
- Modify: `material_helpers.py`

Add these helper functions at the end of the file (before any existing final comments):

**Step 1: create_material**

```python
def create_material(asset_path, blend_mode="Opaque", shading_model="DefaultLit",
                    material_domain="Surface", two_sided=False):
    """Create a new base Material asset."""
    try:
        eal = _eal()
        if eal.does_asset_exist(asset_path):
            return _error_json(f"Asset already exists: {asset_path}")

        pkg, name = _asset_parts(asset_path)

        factory = unreal.MaterialFactoryNew()
        tools = unreal.AssetToolsHelpers.get_asset_tools()
        mat = tools.create_asset(name, pkg, unreal.Material, factory)

        if mat is None:
            return _error_json(f"Failed to create material at {asset_path}")

        # Set properties
        try:
            mat.set_editor_property("blend_mode", getattr(unreal.BlendMode, blend_mode.upper()))
        except Exception:
            pass
        try:
            mat.set_editor_property("shading_model", getattr(unreal.MaterialShadingModel, shading_model.upper()))
        except Exception:
            pass
        try:
            mat.set_editor_property("material_domain", getattr(unreal.MaterialDomain, material_domain.upper()))
        except Exception:
            pass
        if two_sided:
            mat.set_editor_property("two_sided", True)

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "blend_mode": blend_mode,
            "shading_model": shading_model,
            "material_domain": material_domain,
            "two_sided": two_sided,
        })
    except Exception as exc:
        return _error_json(exc)
```

**Step 2: duplicate_material**

```python
def duplicate_material(source_path, destination_path):
    """Deep-copy a material to a new path."""
    try:
        eal = _eal()
        if not eal.does_asset_exist(source_path):
            return _error_json(f"Source not found: {source_path}")

        result = eal.duplicate_asset(source_path, destination_path)
        if not result:
            return _error_json(f"Failed to duplicate {source_path} to {destination_path}")

        # Get stats on the copy
        copy = _load_material(destination_path)
        expr_count = -1
        try:
            expr_count = int(_mel().get_num_material_expressions(copy))
        except Exception:
            pass

        return json.dumps({
            "success": True,
            "source_path": source_path,
            "destination_path": destination_path,
            "expression_count": expr_count,
        })
    except Exception as exc:
        return _error_json(exc)
```

**Step 3: save_material**

```python
def save_material(asset_path):
    """Save a material asset to disk."""
    try:
        eal = _eal()
        if not eal.does_asset_exist(asset_path):
            return _error_json(f"Asset not found: {asset_path}")

        result = eal.save_asset(asset_path)

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "saved": bool(result),
        })
    except Exception as exc:
        return _error_json(exc)
```

**Step 4: disconnect_expressions**

```python
def disconnect_expressions(asset_path, expression_name, input_name="", disconnect_outputs=False):
    """Disconnect wires on an expression without deleting it."""
    try:
        # Fast path
        if _has_cpp_plugin():
            raw = _cpp().disconnect_expression(asset_path, expression_name, input_name, disconnect_outputs)
            return raw

        # Slow path: Python-only
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json("Cannot disconnect on a MaterialInstanceConstant.")

        mel = _mel()
        full_path = _full_object_path(asset_path)

        if not expression_name.startswith("MaterialExpression"):
            expression_name = f"MaterialExpression{expression_name}"

        target = unreal.find_object(None, f"{full_path}:{expression_name}")
        if target is None:
            return _error_json(f"Expression not found: {expression_name}")

        # For Python-only path, we can only disconnect inputs by creating a dummy
        # and reconnecting, or use the C++ plugin. Report limitation.
        return _error_json(
            "disconnect_expressions requires the MaterialMCPReader C++ plugin. "
            "Without it, use delete_expression or manually reconnect."
        )
    except Exception as exc:
        return _error_json(exc)
```

**Step 5: create_custom_hlsl_node**

```python
def create_custom_hlsl_node(asset_path, code, description="", output_type="CMOT_FLOAT3",
                            inputs=None, additional_outputs=None, pos_x=0, pos_y=0):
    """Create a MaterialExpressionCustom with code, inputs, and outputs in one call."""
    try:
        # Fast path
        if _has_cpp_plugin():
            inputs_json = json.dumps(inputs or [])
            outputs_json = json.dumps(additional_outputs or [])
            raw = _cpp().create_custom_hlsl_node(
                asset_path, code, description, output_type,
                inputs_json, outputs_json, pos_x, pos_y
            )
            return raw

        # Slow path: Python MEL
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json("Cannot create expressions on a MaterialInstanceConstant.")

        mel = _mel()
        custom = mel.create_material_expression(mat, unreal.MaterialExpressionCustom, pos_x, pos_y)

        custom.set_editor_property("code", code)
        if description:
            custom.set_editor_property("description", description)

        # Output type
        otype_map = {
            "CMOT_FLOAT1": unreal.CustomMaterialOutputType.CMOT_FLOAT1,
            "CMOT_FLOAT2": unreal.CustomMaterialOutputType.CMOT_FLOAT2,
            "CMOT_FLOAT3": unreal.CustomMaterialOutputType.CMOT_FLOAT3,
            "CMOT_FLOAT4": unreal.CustomMaterialOutputType.CMOT_FLOAT4,
        }
        if output_type in otype_map:
            custom.set_editor_property("output_type", otype_map[output_type])

        # Inputs
        if inputs:
            input_array = unreal.Array(unreal.CustomInput)
            for inp_def in inputs:
                ci = unreal.CustomInput()
                ci.set_editor_property("input_name", inp_def.get("name", "Input"))
                input_array.append(ci)
            custom.set_editor_property("inputs", input_array)

        # Additional outputs
        if additional_outputs:
            ao_array = unreal.Array(unreal.CustomOutput)
            for out_def in additional_outputs:
                co = unreal.CustomOutput()
                co.set_editor_property("output_name", out_def.get("name", "Output"))
                out_type = out_def.get("type", "CMOT_FLOAT1")
                if out_type in otype_map:
                    co.set_editor_property("output_type", otype_map[out_type])
                ao_array.append(co)
            custom.set_editor_property("additional_outputs", ao_array)

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "expression_name": _expr_id(custom),
            "code_length": len(code),
            "input_count": len(inputs) if inputs else 0,
            "output_count": 1 + (len(additional_outputs) if additional_outputs else 0),
        })
    except Exception as exc:
        return _error_json(exc)
```

**Step 6: get_expression_details, validate_material, export/import/copy graph, run_script**

These all follow the same C++-fast-path / Python-fallback pattern. For `get_expression_details` and `validate_material`, the C++ plugin does the heavy lifting. For `export_material_graph`, `import_material_graph`, `copy_material_graph`, the helpers delegate to C++ functions. For `run_script`, it's just a passthrough.

```python
def get_expression_details(asset_path, expression_name):
    """Full property dump of a single expression."""
    try:
        if _has_cpp_plugin():
            return _cpp().get_expression_details(asset_path, expression_name)
        # Python fallback: limited property dump
        mat = _load_material(asset_path)
        full_path = _full_object_path(asset_path)
        if not expression_name.startswith("MaterialExpression"):
            expression_name = f"MaterialExpression{expression_name}"
        expr = unreal.find_object(None, f"{full_path}:{expression_name}")
        if expr is None:
            return _error_json(f"Expression not found: {expression_name}")
        mel = _mel()
        props = _extract_expression_props(expr, expr.get_class().get_name())
        inputs = mel.get_inputs_for_material_expression(mat, expr)
        input_names = [str(n) for n in mel.get_material_expression_input_names(expr)]
        input_data = []
        for i, inp in enumerate(inputs):
            pin_name = input_names[i] if i < len(input_names) else f"Input_{i}"
            input_data.append({
                "name": pin_name,
                "connected": inp is not None,
                "connected_to": _expr_id(inp) if inp else None,
            })
        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "expression_name": expression_name,
            "class": expr.get_class().get_name(),
            "properties": props,
            "inputs": input_data,
        })
    except Exception as exc:
        return _error_json(exc)


def get_material_layer_info(asset_path):
    """Inspect Material Layer or Material Layer Blend."""
    try:
        if _has_cpp_plugin():
            return _cpp().get_material_layer_info(asset_path)
        return _error_json("get_material_layer_info requires the MaterialMCPReader C++ plugin.")
    except Exception as exc:
        return _error_json(exc)


def validate_material(asset_path, fix_issues=False):
    """Validate material graph health."""
    try:
        if _has_cpp_plugin():
            return _cpp().validate_material(asset_path, fix_issues)
        # Basic Python fallback
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json("Cannot validate a MaterialInstanceConstant directly.")
        mel = _mel()
        issues = []
        expr_count = mel.get_num_material_expressions(mat)
        if expr_count > 200:
            issues.append({"severity": "warning", "message": f"High expression count: {expr_count}"})
        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "issues": issues,
            "issue_count": len(issues),
            "note": "Full validation requires MaterialMCPReader C++ plugin",
        })
    except Exception as exc:
        return _error_json(exc)


def export_material_graph(asset_path, export_name=""):
    """Export material graph to JSON."""
    try:
        if _has_cpp_plugin():
            raw = _cpp().export_material_graph(asset_path)
            data = json.loads(raw)
            if not data.get("success"):
                return raw
            # Save to file
            import os
            if not export_name:
                _, export_name = _asset_parts(asset_path)
            save_dir = os.path.join(os.environ.get("UE_PROJECT_PATH", "."), "Saved", "MaterialMCP", "exports")
            os.makedirs(save_dir, exist_ok=True)
            file_path = os.path.join(save_dir, f"{export_name}.json")
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            data["export_path"] = file_path
            return json.dumps(data)
        return _error_json("export_material_graph requires the MaterialMCPReader C++ plugin.")
    except Exception as exc:
        return _error_json(exc)


def import_material_graph(asset_path, export_path, mode="overwrite"):
    """Import a graph from JSON file."""
    try:
        import os
        # Resolve export path
        if not os.path.isabs(export_path):
            save_dir = os.path.join(os.environ.get("UE_PROJECT_PATH", "."), "Saved", "MaterialMCP", "exports")
            export_path = os.path.join(save_dir, f"{export_path}.json")
        with open(export_path, "r", encoding="utf-8") as f:
            graph_json = f.read()
        if _has_cpp_plugin():
            return _cpp().import_material_graph(asset_path, graph_json, mode)
        return _error_json("import_material_graph requires the MaterialMCPReader C++ plugin.")
    except Exception as exc:
        return _error_json(exc)


def copy_material_graph(source_path, destination_path, include_properties=False, offset_x=0, offset_y=0):
    """Copy graph from one material to another."""
    try:
        if _has_cpp_plugin():
            # Export source, import into dest with merge
            raw = _cpp().export_material_graph(source_path)
            data = json.loads(raw)
            if not data.get("success"):
                return raw
            return _cpp().import_material_graph(destination_path, json.dumps(data), "merge")
        return _error_json("copy_material_graph requires the MaterialMCPReader C++ plugin.")
    except Exception as exc:
        return _error_json(exc)
```

**Step 7: Run tests, commit**

---

### Task 13: Server Tools 29-40 (Structured)

**Files:**
- Modify: `C:/Users/lucas/AppData/Local/Temp/unreal-material-mcp/src/unreal_material_mcp/server.py`
- Modify: `C:/Users/lucas/AppData/Local/Temp/unreal-material-mcp/tests/test_server.py`

Add 12 new `@mcp.tool()` functions following the exact existing pattern. Each tool:
1. Builds a script calling the corresponding `material_helpers` function
2. Runs via `_run_material_script()`
3. Checks `_format_error()`
4. Formats output as human-readable text

**Step 1: Add all 12 server tools**

Pattern for each (example: `create_material`):
```python
@mcp.tool()
def create_material(
    asset_path: str,
    blend_mode: str = "Opaque",
    shading_model: str = "DefaultLit",
    material_domain: str = "Surface",
    two_sided: bool = False,
) -> str:
    """Create a new base Material asset from scratch.

    Args:
        asset_path: Save path, e.g. '/Game/Materials/M_NewMaterial'
        blend_mode: Blend mode (Opaque, Masked, Translucent, etc.)
        shading_model: Shading model (DefaultLit, Unlit, SubsurfaceProfile, etc.)
        material_domain: Material domain (Surface, DeferredDecal, PostProcess, etc.)
        two_sided: Whether the material renders on both sides
    """
    script = (
        f"result = material_helpers.create_material("
        f"'{_escape_py_string(asset_path)}', "
        f"blend_mode='{_escape_py_string(blend_mode)}', "
        f"shading_model='{_escape_py_string(shading_model)}', "
        f"material_domain='{_escape_py_string(material_domain)}', "
        f"two_sided={two_sided})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"

    lines = [
        f"Created: {data.get('asset_path', asset_path)}",
        f"  Blend Mode: {data.get('blend_mode', 'N/A')}",
        f"  Shading Model: {data.get('shading_model', 'N/A')}",
        f"  Domain: {data.get('material_domain', 'N/A')}",
        f"  Two Sided: {data.get('two_sided', False)}",
    ]
    return "\n".join(lines)
```

Repeat the pattern for: `duplicate_material`, `save_material`, `disconnect_expressions`, `create_custom_hlsl_node`, `get_expression_details`, `get_material_layer_info`, `validate_material`, `export_material_graph`, `import_material_graph`, `copy_material_graph`, `run_material_script`.

For `run_material_script`, the escape hatch:
```python
@mcp.tool()
def run_material_script(code: str) -> str:
    """Execute arbitrary Python in the editor with material helpers pre-imported.

    The material_helpers module is available as 'material_helpers'.
    The 'unreal' and 'json' modules are also imported.

    Args:
        code: Python code to execute. Must print output to stdout.
    """
    _ensure_helper_uploaded()
    saved_dir = _project_path.replace("\\", "/") + "/Saved/MaterialMCP"
    preamble = (
        "import sys, json\n"
        f"sys.path.insert(0, '{saved_dir}')\n"
        "import importlib, material_helpers\n"
        "importlib.reload(material_helpers)\n"
    )
    full_script = preamble + code
    bridge = _get_bridge()
    result = bridge.run_command(full_script)
    output = result.get("output", "") or result.get("result", "") or ""
    if isinstance(output, list):
        parts = []
        for item in output:
            if isinstance(item, dict):
                parts.append(item.get("output", str(item)))
            else:
                parts.append(str(item))
        output = "\n".join(parts)
    return str(output).strip()
```

**Step 2: Add tests for each new tool**

Follow existing test pattern with `_setup_tool_mock`. Example:
```python
class TestCreateMaterial:
    @patch.object(server, "_get_helper_source", return_value="# src\n")
    def test_formats_creation(self, _src):
        _setup_tool_mock({
            "success": True,
            "asset_path": "/Game/Materials/M_New",
            "blend_mode": "Opaque",
            "shading_model": "DefaultLit",
            "material_domain": "Surface",
            "two_sided": False,
        })
        result = server.create_material("/Game/Materials/M_New")
        assert "Created: /Game/Materials/M_New" in result
        assert "Blend Mode: Opaque" in result
```

**Step 3: Run all tests**
```bash
cd /c/Users/lucas/AppData/Local/Temp/unreal-material-mcp && uv run pytest tests/ -v
```

**Step 4: Commit**

---

## Phase 3: Python MCP Server — Procedural Tools (8)

### Task 14: build_material_graph Server Tool

**Files:**
- Modify: `server.py`
- Modify: `material_helpers.py`
- Modify: `tests/test_server.py`

**Step 1: Add helper function**

```python
def build_material_graph(asset_path, graph_spec, clear_existing=False):
    """Build entire graph from declarative spec."""
    try:
        if _has_cpp_plugin():
            spec_json = json.dumps(graph_spec) if isinstance(graph_spec, dict) else graph_spec
            return _cpp().build_material_graph(asset_path, spec_json, clear_existing)

        # Python fallback: create nodes one by one, wire connections
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json("Cannot build graph on a MaterialInstanceConstant.")

        mel = _mel()
        full_path = _full_object_path(asset_path)

        if clear_existing:
            # Delete all existing expressions
            for cls_name in KNOWN_EXPRESSION_CLASSES:
                for i in range(200):
                    obj = unreal.find_object(None, f"{full_path}:MaterialExpression{cls_name}_{i}")
                    if obj is None:
                        if i > 30:
                            break
                        continue
                    mel.delete_material_expression(mat, obj)

        spec = graph_spec if isinstance(graph_spec, dict) else json.loads(graph_spec)
        id_to_name = {}
        errors = []

        # Phase 1: Create nodes
        for node in spec.get("nodes", []):
            nid = node.get("id", "")
            cls = node.get("class", "")
            pos = node.get("pos", [0, 0])
            props = node.get("props", {})

            full_class = f"MaterialExpression{cls}"
            expr_class = getattr(unreal, full_class, None)
            if expr_class is None:
                errors.append({"id": nid, "error": f"Unknown class: {full_class}"})
                continue

            expr = mel.create_material_expression(mat, expr_class, int(pos[0]), int(pos[1]))
            if expr is None:
                errors.append({"id": nid, "error": "Failed to create"})
                continue

            for pk, pv in props.items():
                try:
                    if pk == "texture" and isinstance(pv, str):
                        tex = _eal().load_asset(pv)
                        expr.set_editor_property(pk, tex)
                    elif pk == "default_value" and isinstance(pv, dict):
                        lc = unreal.LinearColor(
                            r=float(pv.get("r", 0)), g=float(pv.get("g", 0)),
                            b=float(pv.get("b", 0)), a=float(pv.get("a", 1)))
                        expr.set_editor_property(pk, lc)
                    else:
                        expr.set_editor_property(pk, pv)
                except Exception:
                    pass

            id_to_name[nid] = _expr_id(expr)

        # Phase 2: Custom HLSL nodes
        for node in spec.get("custom_hlsl_nodes", []):
            nid = node.get("id", "")
            pos = node.get("pos", [0, 0])
            result_raw = create_custom_hlsl_node(
                asset_path, node.get("code", "return 0;"),
                node.get("description", ""),
                node.get("output_type", "CMOT_FLOAT3"),
                node.get("inputs", []),
                node.get("additional_outputs", []),
                int(pos[0]), int(pos[1])
            )
            data = json.loads(result_raw)
            if data.get("success"):
                id_to_name[nid] = data.get("expression_name", "")
            else:
                errors.append({"id": nid, "error": data.get("error", "Unknown")})

        # Phase 3: Wire connections
        conn_count = 0
        for conn in spec.get("connections", []):
            from_name = id_to_name.get(conn.get("from", ""))
            to_name = id_to_name.get(conn.get("to", ""))
            if not from_name or not to_name:
                continue
            result_raw = connect_expressions(
                asset_path, from_name, to_name,
                conn.get("from_pin", ""), conn.get("to_pin", ""))
            data = json.loads(result_raw)
            if data.get("success"):
                conn_count += 1

        # Phase 4: Material outputs
        for out in spec.get("outputs", []):
            from_name = id_to_name.get(out.get("from", ""))
            if not from_name:
                continue
            connect_expressions(
                asset_path, from_name, out.get("to_property", ""),
                out.get("from_pin", ""), "")
            conn_count += 1

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "id_to_name": id_to_name,
            "nodes_created": len(id_to_name),
            "connections_made": conn_count,
            "errors": errors,
        })
    except Exception as exc:
        return _error_json(exc)
```

**Step 2: Add server tool**

```python
@mcp.tool()
def build_material_graph(
    asset_path: str,
    graph_spec: str,
    clear_existing: bool = False,
) -> str:
    """Build an entire material node graph from a declarative JSON spec in one call.

    The spec defines nodes with IDs, connections between them, and material output wiring.
    Custom HLSL nodes get special handling with inputs/outputs/code.

    Args:
        asset_path: Material to build graph in
        graph_spec: JSON string with nodes, connections, outputs, custom_hlsl_nodes arrays
        clear_existing: If True, delete all existing expressions first
    """
    try:
        spec = json.loads(graph_spec)
    except (json.JSONDecodeError, TypeError):
        return f"Error: Invalid JSON for graph_spec"

    script = (
        f"result = material_helpers.build_material_graph("
        f"'{_escape_py_string(asset_path)}', "
        f"{repr(spec)}, "
        f"clear_existing={clear_existing})\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"

    lines = [
        f"Material: {data.get('asset_path', asset_path)}",
        f"  Nodes created: {data.get('nodes_created', 0)}",
        f"  Connections made: {data.get('connections_made', 0)}",
    ]

    id_map = data.get("id_to_name", {})
    if id_map:
        lines.append("  ID -> Expression mapping:")
        for spec_id, expr_name in id_map.items():
            lines.append(f"    {spec_id} -> {expr_name}")

    errors = data.get("errors", [])
    if errors:
        lines.append(f"  Errors ({len(errors)}):")
        for e in errors:
            lines.append(f"    {e.get('id', '?')}: {e.get('error', '?')}")

    return "\n".join(lines)
```

**Step 3: Add test, run tests, commit**

---

### Task 15: Templates Module & create_subgraph_from_template

**Files:**
- Create: `C:/Users/lucas/AppData/Local/Temp/unreal-material-mcp/src/unreal_material_mcp/templates/__init__.py`
- Create: `C:/Users/lucas/AppData/Local/Temp/unreal-material-mcp/src/unreal_material_mcp/templates/material_templates.py`
- Modify: `material_helpers.py`
- Modify: `server.py`
- Modify: `tests/test_server.py`

**Step 1: Create templates module**

Each template is a function returning a `graph_spec` dict. Example templates:

```python
"""Material graph templates — each returns a graph_spec dict for build_material_graph."""


def noise_blend(params=None):
    """Two-input blend driven by noise."""
    p = params or {}
    scale = p.get("scale", 10.0)
    contrast = p.get("contrast", 2.0)

    return {
        "nodes": [
            {"id": "noise", "class": "Noise", "pos": [-800, 0]},
            {"id": "multiply", "class": "Multiply", "pos": [-600, 0]},
            {"id": "contrast_const", "class": "Constant", "pos": [-800, 100],
             "props": {"r": contrast}},
            {"id": "saturate", "class": "Saturate", "pos": [-400, 0]},
            {"id": "lerp", "class": "LinearInterpolate", "pos": [-200, 0]},
            {"id": "input_a", "class": "VectorParameter", "pos": [-600, -200],
             "props": {"parameter_name": p.get("param_a", "Blend Color A"),
                       "default_value": {"r": 0.8, "g": 0.2, "b": 0.1, "a": 1.0}}},
            {"id": "input_b", "class": "VectorParameter", "pos": [-600, -100],
             "props": {"parameter_name": p.get("param_b", "Blend Color B"),
                       "default_value": {"r": 0.2, "g": 0.4, "b": 0.6, "a": 1.0}}},
            {"id": "scale_param", "class": "ScalarParameter", "pos": [-1000, 0],
             "props": {"parameter_name": "Noise Scale", "default_value": scale}},
        ],
        "connections": [
            {"from": "noise", "from_pin": "", "to": "multiply", "to_pin": "A"},
            {"from": "contrast_const", "from_pin": "", "to": "multiply", "to_pin": "B"},
            {"from": "multiply", "from_pin": "", "to": "saturate", "to_pin": ""},
            {"from": "saturate", "from_pin": "", "to": "lerp", "to_pin": "Alpha"},
            {"from": "input_a", "from_pin": "", "to": "lerp", "to_pin": "A"},
            {"from": "input_b", "from_pin": "", "to": "lerp", "to_pin": "B"},
        ],
        "outputs": [],
        "_output_node": "lerp",
        "_output_pin": "",
        "_exposed_params": ["Blend Color A", "Blend Color B", "Noise Scale"],
    }


def pbr_texture_set(params=None):
    """Full PBR texture wiring: albedo, normal, roughness, AO, emissive."""
    p = params or {}
    tiling = p.get("tiling", 1.0)
    prefix = p.get("param_prefix", "")

    nodes = [
        {"id": "tiling", "class": "ScalarParameter", "pos": [-1200, 0],
         "props": {"parameter_name": f"{prefix}Tiling", "default_value": tiling}},
        {"id": "texcoord", "class": "TextureCoordinate", "pos": [-1000, 0]},
        {"id": "multiply_uv", "class": "Multiply", "pos": [-800, 0]},
        {"id": "albedo", "class": "TextureSampleParameter2D", "pos": [-500, -400],
         "props": {"parameter_name": f"{prefix}Albedo"}},
        {"id": "normal", "class": "TextureSampleParameter2D", "pos": [-500, -200],
         "props": {"parameter_name": f"{prefix}Normal"}},
        {"id": "roughness", "class": "TextureSampleParameter2D", "pos": [-500, 0],
         "props": {"parameter_name": f"{prefix}Roughness"}},
        {"id": "ao", "class": "TextureSampleParameter2D", "pos": [-500, 200],
         "props": {"parameter_name": f"{prefix}AO"}},
    ]

    connections = [
        {"from": "tiling", "from_pin": "", "to": "multiply_uv", "to_pin": "A"},
        {"from": "texcoord", "from_pin": "", "to": "multiply_uv", "to_pin": "B"},
        {"from": "multiply_uv", "from_pin": "", "to": "albedo", "to_pin": "UVs"},
        {"from": "multiply_uv", "from_pin": "", "to": "normal", "to_pin": "UVs"},
        {"from": "multiply_uv", "from_pin": "", "to": "roughness", "to_pin": "UVs"},
        {"from": "multiply_uv", "from_pin": "", "to": "ao", "to_pin": "UVs"},
    ]

    outputs = [
        {"from": "albedo", "from_pin": "RGB", "to_property": "BaseColor"},
        {"from": "normal", "from_pin": "RGB", "to_property": "Normal"},
        {"from": "roughness", "from_pin": "R", "to_property": "Roughness"},
        {"from": "ao", "from_pin": "R", "to_property": "AmbientOcclusion"},
    ]

    return {
        "nodes": nodes,
        "connections": connections,
        "outputs": outputs,
        "_exposed_params": [f"{prefix}Tiling", f"{prefix}Albedo", f"{prefix}Normal",
                           f"{prefix}Roughness", f"{prefix}AO"],
    }


def fresnel_glow(params=None):
    """Fresnel-driven emissive effect."""
    p = params or {}
    return {
        "nodes": [
            {"id": "fresnel", "class": "Fresnel", "pos": [-600, 0]},
            {"id": "power_param", "class": "ScalarParameter", "pos": [-800, 0],
             "props": {"parameter_name": "Fresnel Power", "default_value": p.get("power", 3.0)}},
            {"id": "color_param", "class": "VectorParameter", "pos": [-600, -200],
             "props": {"parameter_name": "Glow Color",
                       "default_value": p.get("color", {"r": 0.0, "g": 0.5, "b": 1.0, "a": 1.0})}},
            {"id": "intensity", "class": "ScalarParameter", "pos": [-600, -100],
             "props": {"parameter_name": "Glow Intensity", "default_value": p.get("intensity", 5.0)}},
            {"id": "multiply_color", "class": "Multiply", "pos": [-400, -150]},
            {"id": "multiply_fresnel", "class": "Multiply", "pos": [-200, 0]},
        ],
        "connections": [
            {"from": "color_param", "from_pin": "", "to": "multiply_color", "to_pin": "A"},
            {"from": "intensity", "from_pin": "", "to": "multiply_color", "to_pin": "B"},
            {"from": "multiply_color", "from_pin": "", "to": "multiply_fresnel", "to_pin": "A"},
            {"from": "fresnel", "from_pin": "", "to": "multiply_fresnel", "to_pin": "B"},
        ],
        "outputs": [
            {"from": "multiply_fresnel", "from_pin": "", "to_property": "EmissiveColor"},
        ],
        "_output_node": "multiply_fresnel",
        "_exposed_params": ["Fresnel Power", "Glow Color", "Glow Intensity"],
    }


# Registry of all templates
TEMPLATES = {
    "noise_blend": noise_blend,
    "pbr_texture_set": pbr_texture_set,
    "fresnel_glow": fresnel_glow,
    # Add more templates here as they are built:
    # "triplanar": triplanar,
    # "height_blend": height_blend,
    # "detail_normal": detail_normal,
    # "parallax_occlusion": parallax_occlusion,
    # "distance_fade": distance_fade,
    # "world_aligned_blend": world_aligned_blend,
    # "vertex_color_blend": vertex_color_blend,
    # "wetness": wetness,
    # "tiling_break": tiling_break,
    # "edge_wear": edge_wear,
    # "emissive_pulse": emissive_pulse,
}


def get_template_spec(template_name, params=None):
    """Get a graph spec from a template name."""
    func = TEMPLATES.get(template_name)
    if func is None:
        return None
    return func(params)


def list_templates():
    """Return list of available template names."""
    return list(TEMPLATES.keys())
```

**Step 2: Add `create_subgraph_from_template` helper in material_helpers.py**

```python
def create_subgraph_from_template(asset_path, template_name, params=None, pos_x=0, pos_y=0):
    """Create a subgraph from a pre-built template."""
    try:
        # Templates are server-side, so the server will pass the spec directly
        # This function receives the already-resolved spec
        return _error_json(
            "create_subgraph_from_template should be called via the server, "
            "which resolves templates before sending to the editor."
        )
    except Exception as exc:
        return _error_json(exc)
```

**Step 3: Add server tool that resolves template → spec → build_material_graph**

```python
@mcp.tool()
def create_subgraph_from_template(
    asset_path: str,
    template_name: str,
    params: str = "{}",
    node_pos_x: int = 0,
    node_pos_y: int = 0,
) -> str:
    """Create a pre-built procedural pattern as a subgraph.

    Available templates: noise_blend, pbr_texture_set, fresnel_glow,
    triplanar, height_blend, detail_normal, parallax_occlusion,
    distance_fade, world_aligned_blend, vertex_color_blend, wetness,
    tiling_break, edge_wear, emissive_pulse.

    Args:
        asset_path: Material to add subgraph to
        template_name: Template identifier
        params: JSON string with template-specific parameter overrides
        node_pos_x: X offset for the subgraph position
        node_pos_y: Y offset for the subgraph position
    """
    from unreal_material_mcp.templates.material_templates import get_template_spec, list_templates

    try:
        template_params = json.loads(params)
    except (json.JSONDecodeError, TypeError):
        return f"Error: Invalid JSON for params"

    spec = get_template_spec(template_name, template_params)
    if spec is None:
        available = ", ".join(list_templates())
        return f"Error: Unknown template '{template_name}'. Available: {available}"

    # Apply position offset to all nodes
    for node in spec.get("nodes", []):
        pos = node.get("pos", [0, 0])
        node["pos"] = [pos[0] + node_pos_x, pos[1] + node_pos_y]
    for node in spec.get("custom_hlsl_nodes", []):
        pos = node.get("pos", [0, 0])
        node["pos"] = [pos[0] + node_pos_x, pos[1] + node_pos_y]

    # Use build_material_graph to create the subgraph
    spec_json = json.dumps(spec)
    script = (
        f"result = material_helpers.build_material_graph("
        f"'{_escape_py_string(asset_path)}', "
        f"{repr(spec)}, "
        f"clear_existing=False)\n"
        "print(result)\n"
    )
    data = _run_material_script(script)
    err = _format_error(data)
    if err:
        return f"Error: {err}"

    exposed = spec.get("_exposed_params", [])
    output_node = spec.get("_output_node", "")
    output_pin = spec.get("_output_pin", "")

    lines = [
        f"Template: {template_name}",
        f"  Nodes created: {data.get('nodes_created', 0)}",
        f"  Connections made: {data.get('connections_made', 0)}",
    ]
    if exposed:
        lines.append(f"  Exposed parameters: {', '.join(exposed)}")
    if output_node:
        mapped_name = data.get("id_to_name", {}).get(output_node, output_node)
        lines.append(f"  Output node: {mapped_name} (pin: {output_pin or 'default'})")
        lines.append("  Wire this to a material output or another subgraph.")

    return "\n".join(lines)
```

**Step 4: Add tests, run tests, commit**

---

### Task 16: Preview, Auto-Builder, and Iteration Tools (Tools 43-48)

**Files:**
- Modify: `material_helpers.py`
- Modify: `server.py`
- Modify: `tests/test_server.py`

**Step 1: Add remaining helper functions**

```python
def preview_material(asset_path, preview_mesh="sphere", resolution=512):
    """Render material preview."""
    try:
        if _has_cpp_plugin():
            return _cpp().render_material_preview(asset_path, resolution)
        return _error_json("preview_material requires the MaterialMCPReader C++ plugin.")
    except Exception as exc:
        return _error_json(exc)


def get_material_preview(asset_path, resolution=256):
    """Get material thumbnail."""
    try:
        if _has_cpp_plugin():
            return _cpp().get_material_thumbnail(asset_path, resolution)
        return _error_json("get_material_preview requires the MaterialMCPReader C++ plugin.")
    except Exception as exc:
        return _error_json(exc)


def create_material_from_textures(asset_path, textures, tiling=1.0,
                                   normal_strength=1.0, use_parallax=False):
    """Auto-build a PBR material from texture paths."""
    try:
        # Create the material first
        result = create_material(asset_path)
        data = json.loads(result)
        if not data.get("success"):
            return result

        # Build graph spec based on provided textures
        nodes = [
            {"id": "tiling_param", "class": "ScalarParameter", "pos": [-1200, 0],
             "props": {"parameter_name": "Tiling", "default_value": tiling}},
            {"id": "texcoord", "class": "TextureCoordinate", "pos": [-1000, 0]},
            {"id": "uv_multiply", "class": "Multiply", "pos": [-800, 0]},
        ]
        connections = [
            {"from": "tiling_param", "from_pin": "", "to": "uv_multiply", "to_pin": "A"},
            {"from": "texcoord", "from_pin": "", "to": "uv_multiply", "to_pin": "B"},
        ]
        outputs = []

        channel_map = {
            "base_color": ("BaseColor", "RGB", -400),
            "normal": ("Normal", "RGB", -200),
            "roughness": ("Roughness", "R", 0),
            "metallic": ("Metallic", "R", 100),
            "ao": ("AmbientOcclusion", "R", 200),
            "emissive": ("EmissiveColor", "RGB", 300),
            "opacity": ("Opacity", "R", 400),
            "height": (None, "R", 500),
        }

        for channel, tex_path in textures.items():
            if channel not in channel_map:
                continue
            mat_prop, out_pin, y_offset = channel_map[channel]
            node_id = f"tex_{channel}"
            nodes.append({
                "id": node_id,
                "class": "TextureSampleParameter2D",
                "pos": [-500, y_offset],
                "props": {"parameter_name": channel.replace("_", " ").title(), "texture": tex_path},
            })
            connections.append(
                {"from": "uv_multiply", "from_pin": "", "to": node_id, "to_pin": "UVs"}
            )
            if mat_prop:
                outputs.append({"from": node_id, "from_pin": out_pin, "to_property": mat_prop})

        spec = {"nodes": nodes, "connections": connections, "outputs": outputs}
        return build_material_graph(asset_path, spec)
    except Exception as exc:
        return _error_json(exc)


def set_multiple_properties(asset_path, updates):
    """Batch-set properties on multiple expressions."""
    try:
        if _has_cpp_plugin():
            _cpp().begin_material_transaction("Set Multiple Properties")

        results = []
        for upd in updates:
            expr_name = upd.get("expression", "")
            prop_name = upd.get("property", "")
            value = upd.get("value")
            raw = set_expression_property(asset_path, expr_name, prop_name, value)
            data = json.loads(raw)
            results.append({
                "expression": expr_name,
                "property": prop_name,
                "success": data.get("success", False),
                "error": data.get("error") if not data.get("success") else None,
            })

        if _has_cpp_plugin():
            _cpp().end_material_transaction()

        succeeded = sum(1 for r in results if r["success"])
        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "total": len(results),
            "succeeded": succeeded,
            "failed": len(results) - succeeded,
            "results": results,
        })
    except Exception as exc:
        return _error_json(exc)


def swap_subgraph(asset_path, target_expression, new_subgraph, output_node_id):
    """Replace a node's upstream subgraph with a new one."""
    try:
        mat = _load_material(asset_path)
        if _is_material_instance(mat):
            return _error_json("Cannot swap on a MaterialInstanceConstant.")

        mel = _mel()
        full_path = _full_object_path(asset_path)

        if not target_expression.startswith("MaterialExpression"):
            target_expression = f"MaterialExpression{target_expression}"

        target = unreal.find_object(None, f"{full_path}:{target_expression}")
        if target is None:
            return _error_json(f"Target expression not found: {target_expression}")

        # 1. Record downstream connections FROM target
        # (what is connected TO target's outputs)
        downstream = []
        if _has_cpp_plugin():
            graph_raw = _cpp().get_full_connection_graph(asset_path)
            graph_data = json.loads(graph_raw)
            for conn in graph_data.get("connections", []):
                if conn.get("from") == target_expression:
                    downstream.append(conn)

        # 2. Collect upstream subgraph (BFS from target's inputs)
        to_delete = set()
        to_visit = []
        try:
            inputs = mel.get_inputs_for_material_expression(mat, target)
            for inp in inputs:
                if inp is not None:
                    to_visit.append(inp)
        except Exception:
            pass

        while to_visit:
            expr = to_visit.pop(0)
            eid = _expr_id(expr)
            if eid in to_delete:
                continue
            to_delete.add(eid)
            try:
                sub_inputs = mel.get_inputs_for_material_expression(mat, expr)
                for si in sub_inputs:
                    if si is not None:
                        to_visit.append(si)
            except Exception:
                pass

        # Also delete the target itself
        to_delete.add(_expr_id(target))

        # 3. Delete old subgraph
        for eid in to_delete:
            obj = unreal.find_object(None, f"{full_path}:{eid}")
            if obj:
                mel.delete_material_expression(mat, obj)

        # 4. Build new subgraph
        spec = new_subgraph if isinstance(new_subgraph, dict) else json.loads(new_subgraph)
        result_raw = build_material_graph(asset_path, spec)
        build_data = json.loads(result_raw)

        # 5. Reconnect downstream
        new_output_name = build_data.get("id_to_name", {}).get(output_node_id, "")
        reconnected = 0
        if new_output_name and downstream:
            for conn in downstream:
                connect_expressions(
                    asset_path, new_output_name, conn.get("to", ""),
                    conn.get("from_output", ""), conn.get("to_input", ""))
                reconnected += 1

        return json.dumps({
            "success": True,
            "asset_path": asset_path,
            "removed_nodes": list(to_delete),
            "new_nodes": build_data.get("id_to_name", {}),
            "downstream_reconnected": reconnected,
        })
    except Exception as exc:
        return _error_json(exc)
```

**Step 2: Add server tools 43-48**

Follow the standard pattern for each: build script → `_run_material_script()` → format output. The `create_material_from_description` tool works by mapping keywords to templates server-side (similar to `create_subgraph_from_template`).

**Step 3: Add tests for each tool**

**Step 4: Run all tests**
```bash
cd /c/Users/lucas/AppData/Local/Temp/unreal-material-mcp && uv run pytest tests/ -v
```

**Step 5: Commit**

---

### Task 17: Update CLAUDE.md and Documentation

**Files:**
- Modify: `C:/Users/lucas/AppData/Local/Temp/unreal-material-mcp/CLAUDE.md`
- Modify: `C:/Users/lucas/AppData/Local/Temp/unreal-material-mcp/README.md`
- Modify: `D:/Unreal Projects/Leviathan/CLAUDE.md`

**Step 1: Update server CLAUDE.md**
- Update tool count from 28 to 48
- Add new tools to the tool table
- Document C++ plugin detection pattern
- Document templates module

**Step 2: Update project CLAUDE.md**
- Update unreal-material MCP section with new capabilities
- Note MaterialMCPReader plugin in plugins table

**Step 3: Update README.md**
- Add new tool descriptions
- Document C++ plugin requirement for preview/validation features
- Add template list

**Step 4: Commit**

---

### Task 18: Integration Testing

**Step 1: End-to-end test with editor running**

Test sequence:
1. `create_material("/Game/Test/M_IntegrationTest")`
2. `build_material_graph` with a noise_blend spec
3. `validate_material` — should pass
4. `preview_material` — verify PNG is created
5. `export_material_graph` — verify JSON export
6. `create_material("/Game/Test/M_IntegrationTest_Copy")`
7. `import_material_graph` — import export into copy
8. `compare_materials` — should match
9. `save_material` on both
10. Clean up test assets

**Step 2: Template test**

Create material → apply each template → recompile → verify no errors.

**Step 3: Commit final state**

---

## Summary

| Phase | Tasks | Tools Added | Key Deliverable |
|-------|-------|-------------|-----------------|
| 1: C++ Plugin | 1-10 | — | MaterialMCPReader with 15 C++ functions |
| 2: Structured Tools | 11-13 | 29-40 | Creation, wiring, inspection, validation, graph transfer |
| 3: Procedural Tools | 14-16 | 41-48 | Batch builder, templates, preview, auto-builders |
| 4: Docs & Integration | 17-18 | — | Updated docs, end-to-end verification |

Total: 18 tasks, 20 new tools, 1 C++ plugin.
