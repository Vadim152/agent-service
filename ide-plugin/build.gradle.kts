plugins {
    id("org.jetbrains.intellij") version "1.17.1"
    kotlin("jvm") version "1.9.24"
}

kotlin {
    jvmToolchain(17)
}

intellij {
    version.set("2025.1")
    plugins.set(listOf("com.intellij.java"))
}

group = "ru.sber"
version = "0.2.0-SNAPSHOT"

repositories {
    mavenCentral()
}

dependencies {
    implementation("com.fasterxml.jackson.module:jackson-module-kotlin:2.17.1")
    implementation("com.fasterxml.jackson.datatype:jackson-datatype-jsr310:2.17.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    testImplementation(kotlin("test"))
}

tasks {
    patchPluginXml {
        sinceBuild.set("251")
        changeNotes.set("Update plugin metadata for 2025.1 IDE builds.")
    }

    test {
        useJUnitPlatform()
    }
}
