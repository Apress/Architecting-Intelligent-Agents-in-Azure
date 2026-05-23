$ResourceGroupName = "rg-aiaa-book"
$Location = "eastus2"
$AcrName = "acrthainv0701"
$LogAnalyticsName = "law-thain-01"
$ContainerAppsEnvName = "cae-thain-01"
$ContainerAppName = "thain-01"
$ContainerAppStageName = "thain-01-stage"
$ImageRepository = "thain-01"
$ContainerAppPort = 8000
$KeyVaultName = "kv-thain-01"
$StorageAccountName = "stthainv0701"
$ContentSafetyName = "cs-thain-01"
$ContentSafetyKeySecretName = "thain-content-safety-key"
$SafetyTemplateHumanEscalateSecretName = "thain-safety-template-human-escalate"
$SafetyTemplateRefuseSecretName = "thain-safety-template-refuse"


# Optional resource IDs (set if you want scripts to avoid lookups)
$FoundryProjectResourceId = ""
$FoundryAccountResourceId = ""
$CosmosAccountName = "cosmos-thain"
$SearchServiceName = "ai-search-thain-1"

# Optional: user object id to allow seeding Key Vault secrets
$KeyVaultSeederObjectId = ""
