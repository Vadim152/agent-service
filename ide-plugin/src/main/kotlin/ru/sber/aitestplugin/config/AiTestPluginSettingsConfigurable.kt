package ru.sber.aitestplugin.config

import com.intellij.openapi.options.ConfigurationException
import javax.swing.JComponent
import javax.swing.JPanel
import javax.swing.JTextField
import java.net.MalformedURLException
import java.net.URL

/**
 * Панель настроек плагина (Settings/Preferences → "AI Test Agent").
 * Позволит редактировать URL backend и таймауты.
 */
class AiTestPluginSettingsConfigurable : com.intellij.openapi.options.Configurable {
    private val backendUrlField = JTextField(AiTestPluginSettings.DEFAULT_BACKEND_URL)
    private val settingsService = AiTestPluginSettingsService.getInstance()
    private val rootPanel: JPanel = JPanel().apply {
        add(backendUrlField)
    }

    override fun getDisplayName(): String = "AI Test Agent"

    override fun createComponent(): JComponent = rootPanel

    override fun isModified(): Boolean {
        val savedState = settingsService.settings
        return backendUrlField.text.trim() != savedState.backendUrl
    }

    override fun apply() {
        val backendUrl = backendUrlField.text.trim()
        validateBackendUrl(backendUrl)
        settingsService.settings.backendUrl = backendUrl
    }

    override fun reset() {
        val savedState = settingsService.settings
        backendUrlField.text = savedState.backendUrl
    }

    private fun validateBackendUrl(url: String) {
        if (url.isBlank()) {
            throw ConfigurationException("Backend URL must not be empty")
        }

        val parsedUrl = try {
            URL(url)
        } catch (ex: MalformedURLException) {
            throw ConfigurationException("Invalid backend URL: ${ex.message}")
        }

        val protocol = parsedUrl.protocol?.lowercase()
        if (protocol != "http" && protocol != "https") {
            throw ConfigurationException("Backend URL must start with http:// or https://")
        }
    }
}
