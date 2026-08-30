param(
    [switch]$Install,
    [ValidateRange(1024, 65535)]
    [int]$Port = 8787
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$AndroidRoot = Join-Path $ProjectRoot "android"
$SdkRoot = if ($env:ANDROID_SDK_ROOT) { $env:ANDROID_SDK_ROOT } elseif ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { Join-Path $env:LOCALAPPDATA "Android\Sdk" }

if (-not (Test-Path $SdkRoot)) {
    throw "Android SDK not found. Set ANDROID_SDK_ROOT or install the Android SDK."
}

$escapedSdk = $SdkRoot.Replace("\", "\\").Replace(":", "\:")
Set-Content -Path (Join-Path $AndroidRoot "local.properties") -Value "sdk.dir=$escapedSdk" -Encoding ASCII

Push-Location $AndroidRoot
try {
    & ".\gradlew.bat" assembleRelease
    if ($LASTEXITCODE -ne 0) { throw "Gradle build failed with exit code $LASTEXITCODE." }
}
finally {
    Pop-Location
}

$sourceApk = Join-Path $AndroidRoot "app\build\outputs\apk\release\app-release.apk"
$dist = Join-Path $ProjectRoot "dist"
New-Item -ItemType Directory -Force -Path $dist | Out-Null
$publishedApk = Join-Path $dist "Swingdesk.apk"
Copy-Item $sourceApk $publishedApk -Force
Write-Host "Built: $publishedApk"

if ($Install) {
    & adb devices
    if ($LASTEXITCODE -ne 0) { throw "ADB is unavailable." }
    & adb install -r $publishedApk
    if ($LASTEXITCODE -ne 0) { throw "APK installation failed with exit code $LASTEXITCODE." }
    & adb reverse "tcp:$Port" "tcp:$Port"
    if ($LASTEXITCODE -ne 0) { throw "ADB reverse tunnel failed with exit code $LASTEXITCODE." }
    & adb shell monkey -p com.swingdesk.app -c android.intent.category.LAUNCHER 1
    if ($LASTEXITCODE -ne 0) { throw "App launch failed with exit code $LASTEXITCODE." }
}