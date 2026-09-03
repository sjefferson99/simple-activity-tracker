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

// Pins a subproject's compileSdk to match :app's own (see the shared
// rationale below) — used for both media_store_plus (pinned too low) and
// flutter_secure_storage (pinned to an API level that no longer resolves).
fun Project.pinCompileSdkToApp() {
    // afterEvaluate, not plugins.withId — the plugin's own build.gradle
    // (Groovy or Kotlin, setting its own compileSdk/compileSdkVersion) runs
    // during this subproject's own evaluation, which happens *inside* the
    // outer subprojects{} closure below it; setting compileSdk from
    // plugins.withId ran before that script did and got clobbered by it.
    // afterEvaluate guarantees this runs strictly after the subproject has
    // finished evaluating itself.
    afterEvaluate {
        // Match :app's own compileSdk (set from flutter.compileSdkVersion in
        // app/build.gradle.kts) rather than a second hardcoded number —
        // otherwise a future Flutter upgrade that raises the app's compileSdk
        // further can silently leave this patch stale and reintroduce the
        // exact failure it exists to fix. evaluationDependsOn(":app") above
        // guarantees :app has already set this by the time this runs.
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

subprojects {
    // media_store_plus 0.1.3 hardcodes compileSdkVersion 33 in its own
    // android/build.gradle, unrelated to anything in this app. Gradle's
    // unified dependency resolution pulls in AndroidX libraries elsewhere
    // (via other plugins) that need compileSdk 34+, and the plugin's stale
    // pin then fails its own :checkDebugAarMetadata task before our app is
    // even built. The plugin hasn't been updated in ~2 years, so bump it
    // here rather than forking the package — this survives `flutter pub
    // get` since it patches the build at configuration time, not the pub
    // cache.
    if (project.name == "media_store_plus") pinCompileSdkToApp()

    // flutter_secure_storage 11.0.0 sets compileSdk = 37, but the installed
    // SDK tooling only offers "android-37.0"/"android-37.1"/"android-37.2"
    // (Google split API level 37 into sub-versions with no bare "android-37"
    // target at all) — AGP can't resolve the plugin's plain-integer request
    // against any of them, and :flutter_secure_storage:compileDebugJavaWithJavac
    // fails before our app builds. Nothing this plugin does needs API 37
    // specifically (it wraps the Android Keystore, stable for many API
    // levels), so pin it down to :app's compileSdk instead of chasing the
    // new sub-versioned platform names.
    if (project.name == "flutter_secure_storage") pinCompileSdkToApp()
}

tasks.register<Delete>("clean") {
    delete(rootProject.layout.buildDirectory)
}
