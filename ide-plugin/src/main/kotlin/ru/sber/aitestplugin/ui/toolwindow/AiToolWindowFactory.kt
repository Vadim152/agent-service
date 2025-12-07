package ru.sber.aitestplugin.ui.toolwindow

import com.intellij.openapi.project.DumbAware
import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowFactory

/**
 * Регистрирует Tool Window "AI Cucumber Assistant".
 */
class AiToolWindowFactory : ToolWindowFactory, DumbAware {
    override fun createToolWindowContent(project: Project, toolWindow: ToolWindow) {
        val contentManager = toolWindow.contentManager
        val panel = AiToolWindowPanel(project)
        val content = contentManager.factory.createContent(panel, null, false)
        contentManager.addContent(content)
    }
}
