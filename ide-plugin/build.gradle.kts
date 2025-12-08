plugins {
    id("org.jetbrains.intellij") version "1.17.1"
    kotlin("jvm") version "1.9.24"
}

kotlin {
    jvmToolchain(17)
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
    implementation("com.fasterxml.jackson.module:jackson-module-kotlin:2.17.1")
    implementation("com.fasterxml.jackson.datatype:jackson-datatype-jsr310:2.17.1")

    testImplementation(kotlin("test"))
}

tasks {
    patchPluginXml {
        sinceBuild.set("242")
        changeNotes.set("Initial skeleton for AI Cucumber Assistant plugin.")
    }

    test {
        useJUnitPlatform()
    }
}
