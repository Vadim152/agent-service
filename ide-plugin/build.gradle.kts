plugins {
    id("org.jetbrains.intellij.platform") version "2.11.0"
    kotlin("jvm") version "2.1.0"
}

kotlin {
    jvmToolchain(17)
}

group = "ru.sber"
version = "0.2.0-SNAPSHOT"

repositories {
    mavenCentral()
    intellijPlatform {
        defaultRepositories()
    }
}

dependencies {
    implementation("com.fasterxml.jackson.module:jackson-module-kotlin:2.17.1")
    implementation("com.fasterxml.jackson.datatype:jackson-datatype-jsr310:2.17.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    testImplementation(kotlin("test"))
    testImplementation("junit:junit:4.13.2")
    testRuntimeOnly("org.junit.vintage:junit-vintage-engine:5.11.4")

    intellijPlatform {
        intellijIdea("2025.1") {
            useInstaller.set(false)
        }
        bundledPlugin("com.intellij.java")
        jetbrainsRuntime()
    }
}

intellijPlatform {
    pluginConfiguration {
        changeNotes = "Update plugin metadata for 2025.1 IDE builds."
        ideaVersion {
            sinceBuild = "251"
        }
    }
}

tasks {
    test {
        useJUnitPlatform()
    }
}
