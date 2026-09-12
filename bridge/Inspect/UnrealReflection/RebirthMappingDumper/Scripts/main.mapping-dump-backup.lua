-- One-shot mapping dump for the installed Rebirth build.
-- UE4SS loads this after its reflection hooks are available.
local dumped = false

ExecuteWithDelay(90000, function()
    if dumped then
        return
    end
    dumped = true
    print("[RebirthMappingsDump] Writing Mappings.usmap for the running game build.\n")
    DumpUSMAP()
end)