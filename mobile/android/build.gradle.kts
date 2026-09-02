allprojects {
    repositories {
        google()
        mavenCentral()
    }
}

val newBuildDir: Directory =
    rootProject.layout.buildDirectory
        .dir("../../build")
        .get()
rootProject.layout.buildDirectory.value(newBuildDir)

subprojects {
    val newSubprojectBuildDir: Directory = newBuildDir.dir(project.name)
    project.layout.buildDirectory.value(newSubprojectBuildDir)
}
subprojects {
    project.evaluationDependsOn(":app")
}

// media_store_plus 0.1.3 hardcodes compileSdkVersion 33 in its own
// android/build.gradle, unrelated to anything in this app. Gradle's unified
// dependency resolution pulls in AndroidX libraries elsewhere (via other
// plugins) that need compileSdk 34+, and the plugin's stale pin then fails
// its own :checkDebugAarMetadata task before our app is even built. The
// plugin hasn't been updated in ~2 years, so bump it here rather than
// forking the package — this survives `flutter pub get` since it patches
// the build at configuration time, not the pub cache.
subprojects {
    if (project.name == "media_store_plus") {
        // afterEvaluate, not plugins.withId — the plugin's own build.gradle
        // (Groovy, `compileSdkVersion 33`) runs during this subproject's own
        // evaluation, which happens *inside* the outer subprojects{} closure
        // below it; setting compileSdk from plugins.withId ran before that
        // script did and got clobbered by it. afterEvaluate guarantees this
        // runs strictly after the subproject has finished evaluating itself.
        afterEvaluate {
            // Match :app's own compileSdk (set from flutter.compileSdkVersion
            // in app/build.gradle.kts) rather than a second hardcoded number
            // — otherwise a future Flutter upgrade that raises the app's
            // compileSdk further can silently leave this patch stale and
            // reintroduce the exact failure it exists to fix. evaluationDependsOn(":app")
            // above guarantees :app has already set this by the time this runs.
            val appCompileSdk =
                (project(":app").extensions.getByName("android")
                        as com.android.build.gradle.BaseExtension)
                    .compileSdkVersion
            extensions.configure<com.android.build.gradle.LibraryExtension> {
                compileSdk = appCompileSdk
                    ?.removePrefix("android-")
                    ?.toIntOrNull()
                    ?: 36
            }
        }
    }
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
