-- Read-only runtime inspection of the TailFire Niagara system.
--
-- This version deliberately addresses named properties instead of enumerating
-- FProperty objects: the installed UE4SS build can read property values but
-- faults when iterating part of this game's property chain.  It never assigns
-- a property or writes an Unreal asset.

local PREFIX = "[TailFireRuntimeProbe] "
local ran = false
local ENABLE_NIAGARA_PROBE = false

-- One permanently-attached system and two representative combat trails. All
-- three have the same missing cooked NiagaraSystem schema range, so this also
-- verifies that runtime inspection is useful beyond the original sample.
local TARGETS = {
    { label = "TailFire", path = "/Game/Effect/Character/Player/PC0004_RedXIII_Body/Particle/FX_PC0004_TailFire_01.FX_PC0004_TailFire_01" },
    { label = "Burst03Tail", path = "/Game/Effect/Character/Player/PC0004_RedXIII/Particle/FX_PC0004_Burst03_Tail_01.FX_PC0004_Burst03_Tail_01" },
    { label = "Burst10Trail", path = "/Game/Effect/Character/Player/PC0004_RedXIII/Particle/FX_PC0004_Burst10_Trail_01.FX_PC0004_Burst10_Trail_01" },
}

local SYSTEM_PROPERTIES = {
    "bSupportLargeWorldCoordinates", "bOverrideCastShadow", "bOverrideReceivesDecals",
    "bOverrideRenderCustomDepth", "bOverrideCustomDepthStencilValue",
    "bOverrideCustomDepthStencilWriteMask", "bOverrideTranslucencySortPriority",
    "bOverrideTranslucencySortDistanceOffset", "bCastShadow", "bReceivesDecals",
    "bRenderCustomDepth", "bDisableExperimentalVM", "CustomDepthStencilWriteMask",
    "CustomDepthStencilValue", "TranslucencySortPriority", "TranslucencySortDistanceOffset",
    "bDumpDebugSystemInfo", "bDumpDebugEmitterInfo", "bRequireCurrentFrameData",
    "bFixedBounds", "EffectType", "bOverrideScalabilitySettings",
    "bOverrideAllowCullingForLocalPlayers", "m_bVfxIgnoreLowPerformance_ScalabilitySettings_MaxDistance",
    "ScalabilityOverrides", "SystemScalabilityOverrides", "EmitterHandles",
    "ParameterCollectionOverrides", "SystemSpawnScript", "SystemUpdateScript",
    -- The installed UE4SS build has no MapProperty reader. This map is skipped
    -- so it cannot interrupt the subsequent readable values.
    "SystemCompiledData", "ExposedParameters",
    "FixedBounds", "bAutoDeactivate", "bDeterminism", "RandomSeed", "WarmupTime",
    "WarmupTickCount", "WarmupTickDelta", "bFixedTickDelta", "FixedTickDeltaTime",
    "bHasSystemScriptDIsWithPerInstanceData", "bNeedsGPUContextInitForDataInterfaces",
    "UserDINamesReadInSystemScripts", "MaxPoolSize", "PoolPrimeSize", "m_EndEffectExtraData",
}

local EFFECT_EXTRA_PROPERTIES = {
    "m_TranslucencyRenderLayer", "m_TranslucencySortPriority", "m_UseTranslucencySortOffset",
    "m_TranslucencySortOffset", "m_BindComponentName", "m_BindSocketName", "m_CharaScaleMin",
    "m_CharaScaleMax", "m_IgnoreBindScale", "m_IgnoreBindRot", "m_BindTime", "m_RenderTarget",
    "m_DisableCullingTick", "m_DisableCullingDraw", "m_IgnoreDynamicCoverage", "m_AbsoluteLocation",
    "m_AbsoluteRotation", "m_AbsoluteScale", "m_AbsoluteRotationActor", "m_RotationBeamTarget",
    "m_AttachCamera", "m_EnableDirectionRot", "m_DirectionRotVectorBaseAxis",
    "m_DirectionRotUpVectorLock", "m_DirectionRotHitNormal", "m_DirectionRotVectorIgnoreZ",
    "m_DirectionVectorReflectHitNormal", "m_bUseRayCast", "m_bUseOrthoGraphic",
    "m_bIgnoreTickPauseFarLevelEffect", "m_bIsLooping", "m_bIsLoopingFromData",
    "m_bInitSetBeamTarget", "m_bInitFieldGridFlow", "m_vRayVectorStartOffset", "m_vRayVector",
    "m_fHitNormalOffsetScale", "m_fBlendBeamTarget", "m_ExposureCondition", "m_Debug_SerializeTest",
}

local function log(message)
    print(PREFIX .. message .. "\n")
end

local function try_read(callback)
    local ok, value = pcall(callback)
    if ok then
        return true, value
    end
    return false, "<unreadable>"
end

local function describe(value)
    if value == nil then
        return "nil"
    end
    if type(value) ~= "userdata" then
        return tostring(value)
    end

    local has_count, count = try_read(function()
        return #value
    end)
    if has_count and type(count) == "number" then
        return "<array count=" .. tostring(count) .. ">"
    end

    local has_name, full_name = try_read(function()
        return value:GetFullName()
    end)
    if has_name and full_name then
        return tostring(full_name)
    end

    local has_type, unreal_type = try_read(function()
        return value:type()
    end)
    if has_type and unreal_type then
        return "<" .. tostring(unreal_type) .. ">"
    end

    return "<userdata>"
end

local function describe_name(value)
    return value:ToString()
end

local function describe_vector(value)
    return "(" .. tostring(value.X) .. ", " .. tostring(value.Y) .. ", " .. tostring(value.Z) .. ")"
end

local function dump_named_properties(label, object, property_names)
    for _, property_name in ipairs(property_names) do
        local readable, value = try_read(function()
            return object:GetPropertyValue(property_name)
        end)
        if readable then
            log(label .. "." .. property_name .. " = " .. describe(value))
        else
            log(label .. "." .. property_name .. " = <unreadable>")
        end
    end
end

local function dump_effect_extra_data(label, system)
    local readable, extra = try_read(function()
        return system:GetPropertyValue("m_EndEffectExtraData")
    end)
    if not readable or extra == nil then
        return
    end

    for _, property_name in ipairs(EFFECT_EXTRA_PROPERTIES) do
        local member_readable, value = try_read(function()
            return extra[property_name]
        end)
        if member_readable then
            local property_label = label .. ".m_EndEffectExtraData." .. property_name
            if property_name == "m_BindComponentName" then
                log(property_label .. " = " .. describe_name(value))
            elseif property_name == "m_BindSocketName" then
                log(property_label .. ".m_SocketName = " .. tostring(value.m_SocketName))
                log(property_label .. ".m_DirectName = " .. describe_name(value.m_DirectName))
            elseif property_name == "m_vRayVectorStartOffset" or property_name == "m_vRayVector" then
                log(property_label .. " = " .. describe_vector(value))
            else
                log(property_label .. " = " .. describe(value))
            end
        end
    end
end

local function dump_emitter_handles(label, system)
    local readable, handles = try_read(function()
        return system:GetPropertyValue("EmitterHandles")
    end)
    if not readable or handles == nil then
        return
    end

    local has_count, count = try_read(function()
        return #handles
    end)
    if not has_count or type(count) ~= "number" then
        return
    end

    log(label .. ".EmitterHandles = <array count=" .. tostring(count) .. ">")
    local iterated = try_read(function()
        handles:ForEach(function(index, element)
            local handle = element:get()
            local handle_label = label .. ".EmitterHandles[" .. tostring(index) .. "]"
            for _, property_name in ipairs({ "Id", "IdName", "bIsEnabled", "Name", "Instance" }) do
                local member_readable, value = try_read(function()
                    return handle[property_name]
                end)
                if member_readable then
                    if property_name == "IdName" or property_name == "Name" then
                        log(handle_label .. "." .. property_name .. " = " .. describe_name(value))
                    else
                        log(handle_label .. "." .. property_name .. " = " .. describe(value))
                    end
                end
            end
            return false
        end)
    end)
    if not iterated then
        log(label .. ".EmitterHandles = <array values unavailable>")
    end
end

ExecuteWithDelay(5000, function()
    if not ENABLE_NIAGARA_PROBE then
        return
    end
    if ran then
        return
    end
    ran = true

    ExecuteInGameThread(function()
        for _, target in ipairs(TARGETS) do
            log("starting named-property inspection for " .. target.path)
            local loaded_ok, asset, found, loaded = pcall(function()
                return LoadAsset(target.path)
            end)
            if not loaded_ok then
                log(target.label .. " LoadAsset failed")
            else
                log(target.label .. " LoadAsset found=" .. tostring(found) .. " loaded=" .. tostring(loaded))
                if asset and asset:IsValid() then
                    dump_named_properties(target.label, asset, SYSTEM_PROPERTIES)
                    dump_effect_extra_data(target.label, asset)
                    dump_emitter_handles(target.label, asset)
                else
                    log(target.label .. " system is not available as a valid UObject")
                end
            end
        end
        log("inspection complete")
    end)
end)

-- A second, read-only probe for the game-owned cutscene route.  Loading the
-- root sequence and enumerating relevant UFunctions does not create a player,
-- change a map, or invoke a cutscene.  It establishes which live controller
-- can perform the editor/test flow before we ever attempt that state change.
local CUT_PREFIX = "[CutsceneRuntimeProbe] "
local CUT_SEQUENCE_PATHS = {
    "/Game/Cut/Game/8400-GOLDE/EV_GOLDE_0500/EV_GOLDE_0500.EV_GOLDE_0500",
    "/Game/Cut/Game/8400-GOLDE/EV_GOLDE_0500/EV_GOLDE_0500",
    "/Game/Cut/Game/8400-GOLDE/EV_GOLDE_0500/EV_GOLDE_0500_CutEvent.EV_GOLDE_0500_CutEvent",
}

local function cut_log(message)
    print(CUT_PREFIX .. message .. "\n")
end

local function is_relevant_cut_function(full_name)
    local name = string.lower(tostring(full_name))
    return string.find(name, "cut", 1, true) ~= nil or
        string.find(name, "sequence", 1, true) ~= nil or
        string.find(name, "editor", 1, true) ~= nil or
        string.find(name, "location", 1, true) ~= nil or
        string.find(name, "play", 1, true) ~= nil or
        string.find(name, "debug", 1, true) ~= nil
end

local function dump_relevant_functions(label, object)
    if object == nil or not object:IsValid() then
        cut_log(label .. " = unavailable")
        return
    end

    local class_ok, class = try_read(function()
        return object:GetClass()
    end)
    if not class_ok or class == nil or not class:IsValid() then
        cut_log(label .. " class = unavailable")
        return
    end

    cut_log(label .. " = " .. describe(object))
    local seen = {}
    local depth = 0
    while class ~= nil and class:IsValid() and depth < 16 do
        local class_name = describe(class)
        cut_log(label .. " class[" .. tostring(depth) .. "] = " .. class_name)
        local walked = try_read(function()
            class:ForEachFunction(function(fn)
                local fn_name_ok, fn_name = try_read(function()
                    return fn:GetFullName()
                end)
                if fn_name_ok and is_relevant_cut_function(fn_name) and not seen[fn_name] then
                    seen[fn_name] = true
                    cut_log(label .. " function = " .. tostring(fn_name))
                end
                -- UE4SS's ForEachFunction keeps a literal false on its Lua
                -- stack and fails on the next callback.  nil means continue
                -- and is discarded correctly by this build.
                return nil
            end)
        end)
        if not walked then
            cut_log(label .. " functions = <unreadable>")
            break
        end
        local super_ok, super = try_read(function()
            return class:GetSuperStruct()
        end)
        if not super_ok or super == nil or not super:IsValid() then
            break
        end
        class = super
        depth = depth + 1
    end
end

local function find_runtime_instance(short_class_name)
    local found_ok, instance = try_read(function()
        return FindFirstOf(short_class_name)
    end)
    if found_ok then
        return instance
    end
    return nil
end

local function find_named_function(object, target_name)
    if object == nil or not object:IsValid() then
        return nil
    end
    local class_ok, class = try_read(function()
        return object:GetClass()
    end)
    if not class_ok or class == nil or not class:IsValid() then
        return nil
    end
    local found = nil
    local looked_up = try_read(function()
        class:ForEachFunction(function(fn)
            local name_ok, name = try_read(function()
                return fn:GetFName():ToString()
            end)
            if name_ok and name == target_name then
                found = fn
                return true
            end
            -- See the ForEachFunction stack workaround above.
            return nil
        end)
    end)
    if looked_up then
        return found
    end
    return nil
end

local function find_default_object(module_name, class_name)
    local found_ok, object = try_read(function()
        return StaticFindObject("/Script/" .. module_name .. ".Default__" .. class_name)
    end)
    if found_ok and object ~= nil and object:IsValid() then
        return object
    end
    return nil
end

local function find_function_by_path(path)
    local found_ok, fn = try_read(function()
        return StaticFindObject(path)
    end)
    if found_ok and fn ~= nil and fn:IsValid() then
        return fn
    end
    return nil
end

local function log_string_array(label, value)
    local count_ok, count = try_read(function()
        return #value
    end)
    if not count_ok or type(count) ~= "number" then
        cut_log(label .. " = " .. describe(value))
        return
    end
    cut_log(label .. " count=" .. tostring(count))
    for index = 1, count do
        local item_ok, element = try_read(function()
            return value[index]
        end)
        if item_ok then
            local text_ok, text = try_read(function()
                if type(element) == "userdata" then
                    return element:ToString()
                end
                return element
            end)
            if text_ok then
                cut_log(label .. "[" .. tostring(index) .. "] = " .. tostring(text))
            end
        else
            cut_log(label .. "[" .. tostring(index) .. "] = <unreadable>")
        end
    end
end

local function describe_string(value)
    if type(value) == "userdata" then
        local readable, text = try_read(function()
            return value:ToString()
        end)
        if readable then
            return tostring(text)
        end
    end
    return tostring(value)
end

local function inspect_cutscene_database()
    local data_api = find_default_object("EndDataBase", "EndDataBaseDataObjectAPI")
    if data_api == nil then
        cut_log("EndDataBaseDataObjectAPI default object = unavailable")
        return
    end

    local get_names = find_function_by_path("/Script/EndDataBase.EndDataBaseDataObjectAPI:GetTestCutSceneNameList")
    if get_names == nil then
        cut_log("GetTestCutSceneNameList = unavailable")
    else
        local call_ok, names = try_read(function()
            -- Functions returned by StaticFindObject have no bound context in
            -- this UE4SS build.  Invoke the UFunction directly and pass its
            -- class default object explicitly.
            return get_names(data_api, "8400-GOLDE")
        end)
        if call_ok then
            log_string_array("GetTestCutSceneNameList(8400-GOLDE)", names)
        else
            cut_log("GetTestCutSceneNameList(8400-GOLDE) = call failed")
        end
    end

    local get_locations = find_function_by_path("/Script/EndDataBase.EndDataBaseDataObjectAPI:GetLocationNames")
    if get_locations == nil then
        cut_log("GetLocationNames = unavailable")
    else
        local call_ok, locations = try_read(function()
            return get_locations(data_api)
        end)
        if call_ok then
            log_string_array("GetLocationNames", locations)
        else
            cut_log("GetLocationNames = call failed")
        end
    end

    local debug_api = find_default_object("EndGame", "EndDebugAPI")
    local get_action_id = find_function_by_path("/Script/EndGame.EndDebugAPI:GetCutSceneActionID")
    if get_action_id == nil then
        cut_log("GetCutSceneActionID = unavailable")
    else
        local call_ok, action_id = try_read(function()
            return get_action_id(debug_api, FName("EV_GOLDE_0500"))
        end)
        if call_ok then
            cut_log("GetCutSceneActionID(EV_GOLDE_0500) = " .. describe_string(action_id))
        else
            cut_log("GetCutSceneActionID(EV_GOLDE_0500) = call failed")
        end
    end
end

-- This follows the game's own test entry point.  It stays deliberately
-- disabled while we validate that the running game exposes its game mode and
-- UFunction.  Enabling it performs a map/state transition into the cutscene.
local CUTSCENE_TEST_ENABLED = false
local CUTSCENE_TEST_LOCATION = "8400-GOLDE"
local CUTSCENE_TEST_NAME = "EV_GOLDE_0500"
local CUTSCENE_TEST_HOOK_ARMED = false

-- UE4SS exposes live UFunction parameters to pre-hooks as writable wrappers.
-- Writing this already-allocated struct directly bypasses its broken Lua-table
-- conversion for nested ObjectProperty fields.
RegisterHook("/Script/EndGame.EndGameMode:InitEditorGameMode", function(self, world_context, location_name, quick_start, cutscene_name, latent_param)
    if not CUTSCENE_TEST_HOOK_ARMED then
        return
    end

    local configured = try_read(function()
        local callback_target = self:get()
        local latent_info = latent_param:get()
        latent_info.Linkage = -1
        latent_info.UUID = -424242
        latent_info.ExecutionFunction = FName("None")
        latent_info.CallbackTarget = callback_target
    end)
    CUTSCENE_TEST_HOOK_ARMED = false
    if configured then
        cut_log("injected latent callback into InitEditorGameMode")
    else
        cut_log("could not inject latent callback into InitEditorGameMode")
    end
end)

local function find_cutscene_game_mode()
    -- The active game mode is normally the Blueprint subclass.  Fall back to
    -- the native class name for builds/maps where the subclass name differs.
    for _, class_name in ipairs({ "EndGameModeBP_C", "EndGameMode" }) do
        local instance = find_runtime_instance(class_name)
        if instance ~= nil and instance:IsValid() then
            return instance
        end
    end
    return nil
end

local function stage_or_launch_cutscene_test()
    local game_mode = find_cutscene_game_mode()
    if game_mode == nil then
        cut_log("native cutscene test route = unavailable (no live EndGameMode)")
        return
    end

    local init_editor_game_mode = find_function_by_path("/Script/EndGame.EndGameMode:InitEditorGameMode")
    if init_editor_game_mode == nil then
        cut_log("native cutscene test route = unavailable (InitEditorGameMode not found)")
        return
    end

    cut_log("native cutscene test route ready: " .. describe(game_mode))
    cut_log("target: " .. CUTSCENE_TEST_LOCATION .. " / " .. CUTSCENE_TEST_NAME .. " (QuickStart=true)")

    if not CUTSCENE_TEST_ENABLED then
        cut_log("native launch remains disabled")
        return
    end

    -- No continuation is needed after invoking this native test route.  The
    -- UE4SS build shipped with Rebirth has a nested-struct table bug when an
    -- FLatentActionInfo contains an ObjectProperty, so keep this deliberately
    -- empty: the game receives a null callback target and performs the entry
    -- as a fire-and-forget latent request.
    local latent_info = {}

    -- Prevent another call in this Lua session if map travel reinstalls the
    -- callback before the user restores the source file to its disabled form.
    CUTSCENE_TEST_HOOK_ARMED = true
    CUTSCENE_TEST_ENABLED = false
    local launched = try_read(function()
        -- Static UFunctions found by path have no bound context in UE4SS.
        -- First argument binds ProcessEvent; second is the explicit
        -- WorldContextObject parameter declared by the game.
        return init_editor_game_mode(
            game_mode,
            game_mode,
            FName(CUTSCENE_TEST_LOCATION),
            true,
            FName(CUTSCENE_TEST_NAME),
            latent_info)
    end)
    if launched then
        cut_log("InitEditorGameMode invoked; the game is entering the cutscene-test flow")
    else
        cut_log("InitEditorGameMode invocation failed")
    end
end

ExecuteWithDelay(8000, function()
    ExecuteInGameThread(function()
        cut_log("starting read-only cutscene route inspection")

        for _, sequence_path in ipairs(CUT_SEQUENCE_PATHS) do
            local loaded_ok, sequence, found, loaded = pcall(function()
                return LoadAsset(sequence_path)
            end)
            if loaded_ok then
                cut_log("EV_GOLDE_0500 LoadAsset(" .. sequence_path .. ") found=" .. tostring(found) .. " loaded=" .. tostring(loaded))
                if sequence ~= nil and sequence:IsValid() then
                    cut_log("resolved sequence = " .. describe(sequence))
                    dump_named_properties("EV_GOLDE_0500", sequence, { "SequencerType", "MovieScene", "CompiledData", "Signature" })
                end
            else
                cut_log("EV_GOLDE_0500 LoadAsset(" .. sequence_path .. ") failed")
            end
        end

        inspect_cutscene_database()
        stage_or_launch_cutscene_test()

        cut_log("read-only cutscene route inspection complete")
    end)
end)
