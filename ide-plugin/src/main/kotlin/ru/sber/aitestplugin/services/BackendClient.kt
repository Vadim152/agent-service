package ru.sber.aitestplugin.services

import ru.sber.aitestplugin.model.ApplyFeatureRequestDto
import ru.sber.aitestplugin.model.ApplyFeatureResponseDto
import ru.sber.aitestplugin.model.ChatHistoryResponseDto
import ru.sber.aitestplugin.model.ChatCommandRequestDto
import ru.sber.aitestplugin.model.ChatCommandResponseDto
import ru.sber.aitestplugin.model.ChatMessageAcceptedResponseDto
import ru.sber.aitestplugin.model.ChatMessageRequestDto
import ru.sber.aitestplugin.model.ChatSessionCreateRequestDto
import ru.sber.aitestplugin.model.ChatSessionCreateResponseDto
import ru.sber.aitestplugin.model.ChatSessionDiffResponseDto
import ru.sber.aitestplugin.model.ChatSessionsListResponseDto
import ru.sber.aitestplugin.model.ChatSessionStatusResponseDto
import ru.sber.aitestplugin.model.ChatToolDecisionRequestDto
import ru.sber.aitestplugin.model.ChatToolDecisionResponseDto
import ru.sber.aitestplugin.model.GenerateFeatureRequestDto
import ru.sber.aitestplugin.model.GenerateFeatureResponseDto
import ru.sber.aitestplugin.model.GenerationPreviewRequestDto
import ru.sber.aitestplugin.model.GenerationPreviewResponseDto
import ru.sber.aitestplugin.model.DeleteMemoryItemResponseDto
import ru.sber.aitestplugin.model.GenerationRuleCreateRequestDto
import ru.sber.aitestplugin.model.GenerationRuleDto
import ru.sber.aitestplugin.model.GenerationRuleListResponseDto
import ru.sber.aitestplugin.model.GenerationRulePatchRequestDto
import ru.sber.aitestplugin.model.GenerationResolvePreviewRequestDto
import ru.sber.aitestplugin.model.GenerationResolvePreviewResponseDto
import ru.sber.aitestplugin.model.OpenCodeAgentsResponseDto
import ru.sber.aitestplugin.model.OpenCodeCommandExecutionRequestDto
import ru.sber.aitestplugin.model.OpenCodeCommandExecutionResponseDto
import ru.sber.aitestplugin.model.OpenCodeCommandsResponseDto
import ru.sber.aitestplugin.model.OpenCodeConfigSnapshotDto
import ru.sber.aitestplugin.model.OpenCodeMcpsResponseDto
import ru.sber.aitestplugin.model.OpenCodeModelsResponseDto
import ru.sber.aitestplugin.model.OpenCodeProvidersResponseDto
import ru.sber.aitestplugin.model.OpenCodeResourcesResponseDto
import ru.sber.aitestplugin.model.OpenCodeSessionEventsResponseDto
import ru.sber.aitestplugin.model.OpenCodeSessionStatusDto
import ru.sber.aitestplugin.model.OpenCodeToolsResponseDto
import ru.sber.aitestplugin.model.ReviewLearningRequestDto
import ru.sber.aitestplugin.model.ReviewLearningResponseDto
import ru.sber.aitestplugin.model.ScanStepsResponseDto
import ru.sber.aitestplugin.model.StepDefinitionDto
import ru.sber.aitestplugin.model.StepTemplateCreateRequestDto
import ru.sber.aitestplugin.model.StepTemplateDto
import ru.sber.aitestplugin.model.StepTemplateListResponseDto
import ru.sber.aitestplugin.model.StepTemplatePatchRequestDto
import ru.sber.aitestplugin.model.RunCreateRequestDto
import ru.sber.aitestplugin.model.RunCreateResponseDto
import ru.sber.aitestplugin.model.RunArtifactsResponseDto
import ru.sber.aitestplugin.model.RunResultResponseDto
import ru.sber.aitestplugin.model.RunStatusResponseDto

/**
 * РђР±СЃС‚СЂР°РєС†РёСЏ РєР»РёРµРЅС‚Р°, РѕР±СЂР°С‰Р°СЋС‰РµРіРѕСЃСЏ Рє backend-СЃРµСЂРІРёСЃСѓ agent-service.
 * РњРµС‚РѕРґС‹ РїСЂРµРґРїРѕР»Р°РіР°СЋС‚ РІС‹РїРѕР»РЅРµРЅРёРµ РІ С„РѕРЅРѕРІС‹С… Р·Р°РґР°С‡Р°С…, С‡С‚РѕР±С‹ РЅРµ Р±Р»РѕРєРёСЂРѕРІР°С‚СЊ UI.
 */
interface BackendClient {
    fun scanSteps(
        projectRoot: String,
        additionalRoots: List<String> = emptyList(),
        providedSteps: List<StepDefinitionDto> = emptyList()
    ): ScanStepsResponseDto

    fun listSteps(projectRoot: String): List<StepDefinitionDto>

    fun generateFeature(request: GenerateFeatureRequestDto): GenerateFeatureResponseDto

    fun createRun(request: RunCreateRequestDto): RunCreateResponseDto

    fun getRun(runId: String): RunStatusResponseDto

    fun getRunResult(runId: String): RunResultResponseDto

    fun listRunArtifacts(runId: String): RunArtifactsResponseDto

    fun getRunArtifactContent(runId: String, artifactId: String): String

    fun applyFeature(request: ApplyFeatureRequestDto): ApplyFeatureResponseDto

    fun previewGenerationPlan(request: GenerationPreviewRequestDto): GenerationPreviewResponseDto

    fun reviewApplyFeature(request: ReviewLearningRequestDto): ReviewLearningResponseDto

    fun createChatSession(request: ChatSessionCreateRequestDto): ChatSessionCreateResponseDto

    fun listChatSessions(projectRoot: String, limit: Int = 50): ChatSessionsListResponseDto

    fun sendChatMessage(sessionId: String, request: ChatMessageRequestDto): ChatMessageAcceptedResponseDto

    fun getChatHistory(sessionId: String): ChatHistoryResponseDto

    fun getChatStatus(sessionId: String): ChatSessionStatusResponseDto

    fun getChatDiff(sessionId: String): ChatSessionDiffResponseDto

    fun executeChatCommand(sessionId: String, request: ChatCommandRequestDto): ChatCommandResponseDto

    fun submitChatToolDecision(sessionId: String, request: ChatToolDecisionRequestDto): ChatToolDecisionResponseDto

    fun listOpenCodeCommands(projectRoot: String): OpenCodeCommandsResponseDto

    fun listOpenCodeAgents(projectRoot: String): OpenCodeAgentsResponseDto

    fun listOpenCodeMcps(projectRoot: String): OpenCodeMcpsResponseDto

    fun listOpenCodeProviders(projectRoot: String): OpenCodeProvidersResponseDto

    fun listOpenCodeModels(projectRoot: String): OpenCodeModelsResponseDto

    fun listOpenCodeTools(projectRoot: String): OpenCodeToolsResponseDto

    fun listOpenCodeResources(kind: String, projectRoot: String): OpenCodeResourcesResponseDto

    fun getOpenCodeConfig(projectRoot: String): OpenCodeConfigSnapshotDto

    fun getOpenCodeSessionStatus(sessionId: String): OpenCodeSessionStatusDto

    fun getOpenCodeSessionEvents(sessionId: String, after: Int = 0, limit: Int = 200): OpenCodeSessionEventsResponseDto

    fun executeOpenCodeCommand(commandId: String, request: OpenCodeCommandExecutionRequestDto): OpenCodeCommandExecutionResponseDto

    fun listGenerationRules(projectRoot: String): GenerationRuleListResponseDto

    fun createGenerationRule(request: GenerationRuleCreateRequestDto): GenerationRuleDto

    fun updateGenerationRule(ruleId: String, request: GenerationRulePatchRequestDto): GenerationRuleDto

    fun deleteGenerationRule(ruleId: String, projectRoot: String): DeleteMemoryItemResponseDto

    fun listStepTemplates(projectRoot: String): StepTemplateListResponseDto

    fun createStepTemplate(request: StepTemplateCreateRequestDto): StepTemplateDto

    fun updateStepTemplate(templateId: String, request: StepTemplatePatchRequestDto): StepTemplateDto

    fun deleteStepTemplate(templateId: String, projectRoot: String): DeleteMemoryItemResponseDto

    fun resolveGenerationPreview(request: GenerationResolvePreviewRequestDto): GenerationResolvePreviewResponseDto
}
