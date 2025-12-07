package ru.sber.aitestplugin.actions

import com.intellij.openapi.actionSystem.AnAction
import com.intellij.openapi.actionSystem.AnActionEvent
import ru.sber.aitestplugin.services.HttpBackendClient

/**
 * Действие, отправляющее текущий feature-текст в backend для записи в файловую систему проекта.
 */
class ApplyFeatureAction : AnAction() {
    private val backendClient = HttpBackendClient()

    override fun actionPerformed(e: AnActionEvent) {
        // TODO: считать текст из текущего редактора, спросить targetPath и вызвать applyFeature
    }
}
