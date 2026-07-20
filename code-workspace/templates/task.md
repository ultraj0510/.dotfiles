+++
schema_version = 1
id = "replace-with-task-id"
repo = "repo/replace-with-repository"
allowed_paths = ["src/", "tests/"]
minimum_level = "L1"
implementer = "replace-with-implementer-id"
acceptance = [
  { id = "focused-test", description = "Focused acceptance command passes", command = ["python3", "-m", "pytest", "tests/replace_me.py", "-q"] },
]

[risk]
local_change = true
reversible = true
external_side_effect = false
schema_or_contract_change = false
cross_module_change = false
public_behavior_change = false
persisted_data_change = false
dependency_change = false
money = false
production = false
security = false
credentials = false
destructive_migration = false
irreversible_external_action = false
+++

# Goal

# Scope

# Non-goals

# Reproduction

# Acceptance

# Stop conditions

# Completion evidence

由 `taskctl close` 推导，不手写 `COMPLETE`。
