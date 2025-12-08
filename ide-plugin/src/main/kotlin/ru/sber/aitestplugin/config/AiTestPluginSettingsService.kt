package ru.sber.aitestplugin.config

import com.intellij.openapi.components.PersistentStateComponent
import com.intellij.openapi.components.Service
import com.intellij.openapi.components.State
import com.intellij.openapi.components.Storage
import com.intellij.openapi.components.service
import com.intellij.util.xmlb.XmlSerializerUtil

@Service(Service.Level.APP)
@State(name = "AiTestPluginSettings", storages = [Storage("aiTestPluginSettings.xml")])
class AiTestPluginSettingsService : PersistentStateComponent<AiTestPluginSettings> {

    private var stateData: AiTestPluginSettings = AiTestPluginSettings()

    val state: AiTestPluginSettings
        get() = stateData

    override fun getState(): AiTestPluginSettings = stateData

    override fun loadState(state: AiTestPluginSettings) {
        XmlSerializerUtil.copyBean(state, this.stateData)
    }

    companion object {
        fun getInstance(): AiTestPluginSettingsService = service()
    }
}
