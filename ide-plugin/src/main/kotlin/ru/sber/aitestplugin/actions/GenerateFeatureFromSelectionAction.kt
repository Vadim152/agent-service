package ru.sber.aitestplugin.actions

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import com.intellij.openapi.actionSystem.CommonDataKeys
import com.intellij.openapi.progress.ProgressManager
import ru.sber.aitestplugin.model.GenerateFeatureOptionsDto
import ru.sber.aitestplugin.model.GenerateFeatureRequestDto
import ru.sber.aitestplugin.services.HttpBackendClient
import javax.swing.JOptionPane

/**
 * Действие, генерирующее .feature из выделенного текста тесткейса.
 */
class GenerateFeatureFromSelectionAction : AnAction() {
    private val backendClient = HttpBackendClient()

    override fun actionPerformed(e: AnActionEvent) {
        val editor = e.getData(CommonDataKeys.EDITOR)
        val project = e.project
        if (editor == null || project == null) {
            JOptionPane.showMessageDialog(null, "Выделите текст тесткейса")
            return
        }
        val selectionModel = editor.selectionModel
        val selectedText = selectionModel.selectedText ?: run {
            JOptionPane.showMessageDialog(null, "Выделите текст тесткейса")
            return
        }
        val projectRoot = project.basePath ?: ""

        // TODO: вывести диалог с targetPath/createFile/overwriteExisting
        val request = GenerateFeatureRequestDto(
            projectRoot = projectRoot,
            testCaseText = selectedText,
            targetPath = null,
            options = GenerateFeatureOptionsDto()
        )

        ProgressManager.getInstance().runProcessWithProgressSynchronously(
            {
                try {
                    val response = backendClient.generateFeature(request)
                    // TODO: открыть редактор с featureText и подсветить unmapped steps
                } catch (ex: Exception) {
                    JOptionPane.showMessageDialog(null, "Generation failed: ${ex.message}")
                }
            },
            "Generating feature",
            true,
            project
        )
    }
}
