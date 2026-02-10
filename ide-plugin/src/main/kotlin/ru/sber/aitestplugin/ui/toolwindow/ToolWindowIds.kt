package ru.sber.aitestplugin.ui.toolwindow

import com.intellij.openapi.project.Project
import com.intellij.openapi.wm.ToolWindow
import com.intellij.openapi.wm.ToolWindowManager

object ToolWindowIds {
    const val DISPLAY_NAME: String = "GigaCode Chat"
    const val ID: String = "GigaCode Chat"
    const val LEGACY_ID: String = "AI Cucumber Assistant"

    fun findToolWindow(project: Project): ToolWindow? {
        val manager = ToolWindowManager.getInstance(project)
        return manager.getToolWindow(ID) ?: manager.getToolWindow(LEGACY_ID)
    }
}
