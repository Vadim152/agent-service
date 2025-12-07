plugins {
    id("org.jetbrains.intellij") version "1.17.1"
    kotlin("jvm") version "1.9.24"
}

intellij {
    version.set("2024.2")
    plugins.set(listOf("com.intellij.java"))
}

group = "ru.sber"
version = "0.1.0-SNAPSHOT"

repositories {
    mavenCentral()
}

dependencies {
    // Additional dependencies for HTTP client or JSON can be added here.
}

tasks {
    patchPluginXml {
        sinceBuild.set("242")
        changeNotes.set("Initial skeleton for AI Cucumber Assistant plugin.")
    }
}
