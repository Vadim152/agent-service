package ru.sber.aitestplugin.actions

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import ru.sber.aitestplugin.model.FeatureResultDto

class GenerateFeatureFromSelectionActionMemorySummaryTest {

    @Test
    fun `returns null when memory stage has no effect`() {
        val result = FeatureResultDto(
            pipeline = listOf(
                mapOf(
                    "stage" to "memory_rules",
                    "details" to mapOf(
                        "appliedRuleIds" to emptyList<String>(),
                        "appliedTemplateIds" to emptyList<String>(),
                        "templateStepsAdded" to 0
                    )
                )
            )
        )

        assertNull(buildMemorySummaryFromPipeline(result))
    }

    @Test
    fun `summarizes applied memory pipeline stage`() {
        val result = FeatureResultDto(
            pipeline = listOf(
                mapOf(
                    "stage" to "memory_rules",
                    "details" to mapOf(
                        "appliedRuleIds" to listOf("rule-1"),
                        "appliedTemplateIds" to listOf("tpl-1", "tpl-2"),
                        "templateStepsAdded" to 3
                    )
                )
            )
        )

        assertEquals(
            "memory: rules=1, templates=2, injectedSteps=3",
            buildMemorySummaryFromPipeline(result)
        )
    }
}
