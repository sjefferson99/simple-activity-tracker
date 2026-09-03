# Installing Simple Activity Tracker on your own phone

This guide walks you through building this app from source and installing it
on your own iPhone or Android phone. You don't need to know how to code —
just follow the steps in order and copy-paste the commands exactly as shown.

Two important things to know before you start:

- **You'll need a computer** — a Mac for iPhone, any computer for Android.
  Apple only allows an app to be installed by whoever compiles it, so there's
  no way around this for iPhone.
- **On iPhone, the app stops working after 7 days** unless you're paying for
  an Apple Developer account ($99/year). This is an Apple restriction on free
  developer accounts, nothing to do with this app. When it stops opening,
  just repeat the "install to your phone" step below (5 minutes) and it'll
  work for another 7 days. Android has no such limit — install it once and
  it keeps working.

Pick the section for your phone below. Each one is self-contained.

---

## Installing on iPhone (needs a Mac)

### What you'll need

- A Mac
- Your iPhone and a USB cable (or the same WiFi network, for a wireless install)
- Your own Apple ID (the same one you use for the App Store — no paid
  developer account needed)
- About 45–60 minutes, mostly spent waiting for downloads

### Step 1: Install Xcode

Xcode is Apple's software for building iPhone apps. It's a free download,
but it's large (several GB) so this can take a while.

1. Open the **App Store** app on your Mac.
2. Search for **Xcode** and install it.
3. Once installed, open Xcode once from your Applications folder. It may ask
   to install some additional components — let it finish.
4. Open the **Terminal** app (search for it with Spotlight — press
   <kbd>Cmd</kbd>+<kbd>Space</kbd> and type "Terminal"). Paste this in and
   press Return, then enter your Mac password when asked (you won't see it
   as you type — that's normal):

   ```
   sudo xcode-select --switch /Applications/Xcode.app/Contents/Developer
   sudo xcodebuild -runFirstLaunch
   ```

### Step 2: Install Homebrew

Homebrew is a tool that installs other developer tools for you. Paste this
into Terminal and press Return:

```
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

Follow any on-screen instructions it gives you at the end (it sometimes asks
you to run one or two more commands — copy and run exactly what it shows you).

### Step 3: Install Flutter and CocoaPods

Flutter is the toolkit this app is built with. Paste each line below into
Terminal one at a time, pressing Return after each:

```
brew install --cask flutter
brew install cocoapods
```

This will take several minutes.

### Step 4: Get the app's source code

If you were given a link to this project on GitHub, download it — click the
green **Code** button, then **Download ZIP**, then unzip it somewhere easy to
find, like your Desktop.

(If you were sent a `.zip` file directly instead, just unzip that.)

### Step 5: Open Terminal in the project folder

In Terminal, type `cd ` (with a space after it), then drag the unzipped
project folder into the Terminal window — it'll fill in the path for you.
Press Return.

Check you're in the right place by typing:

```
ls
```

You should see folders like `mobile`, `docs`, and a file called `CLAUDE.md` listed.

The app itself lives in the `mobile` folder, so move into it:

```
cd mobile
```

Check again with `ls` — this time you should see `pubspec.yaml` and `lib`.

### Step 6: Fetch the app's dependencies

```
flutter pub get
```

This downloads some building blocks the app needs. Takes a minute or two.

### Step 7: Connect your iPhone and trust your Mac

1. Plug your iPhone into your Mac with a USB cable.
2. On your iPhone, you'll get a popup asking "Trust This Computer?" — tap
   **Trust** and enter your passcode.
3. Back in Terminal, check your phone is detected:

   ```
   flutter devices
   ```

   You should see your iPhone listed by name. If it's not there, unlock your
   phone and try again.

### Step 8: Set up code signing (one-time, per Mac)

Every app installed on an iPhone has to be signed by an Apple ID — this is
what lets Apple (and you) confirm the app came from a known source. You only
need to do this once.

1. In Terminal, type:

   ```
   open ios/Runner.xcworkspace
   ```

   This opens the project in Xcode.
2. In the left sidebar, click **Runner** (the top item, with the blue icon).
3. Click the **Signing & Capabilities** tab along the top.
4. Under **Team**, click the dropdown and choose **Add an Account…**, then
   sign in with your Apple ID if it's not already listed. Once signed in,
   select your name from the Team dropdown.
5. Xcode may show a red warning about the "Bundle Identifier" being taken —
   if so, change the text `dev.sjefferson.simpleRunner` (in the **Bundle
   Identifier** field just above Team) to something unique, like
   `com.yourname.simplerunner`. Any unique text works.
6. Close Xcode (you don't need to press any build button in there — Terminal
   will do the actual building next).

### Step 9: Build and install to your phone

Back in Terminal:

```
flutter run --release
```

The first build can take 5–10 minutes. You'll see a lot of text scroll by —
that's normal. When it finishes, the app installs itself on your phone
automatically.

### Step 10: Trust the developer certificate on your iPhone

The first time you open the app, iOS will refuse to run it and show
"Untrusted Developer." This is expected — one more step fixes it:

1. On your iPhone, go to **Settings → General → VPN & Device Management**
   (on older iOS versions this is called **Settings → General → Profiles &
   Device Management**).
2. Under "Developer App," tap your Apple ID email address.
3. Tap **Trust "[your Apple ID]"**, then confirm.
4. Open Simple Activity Tracker from your home screen — it should now launch normally.

**You're done.** The app is installed and ready to use. Remember: it'll stop
opening after 7 days (an Apple limit on free developer accounts, explained
above) — when that happens, just repeat **Step 9** to reinstall it for
another 7 days. Everything else on this list only needs doing once.

---

## Installing on Android (any computer — Mac, Windows, or Linux)

### What you'll need

- A Windows, Mac, or Linux computer
- Your Android phone and a USB cable
- About 45–60 minutes, mostly spent waiting for downloads

### Step 1: Install Android Studio

1. Download Android Studio from
   [developer.android.com/studio](https://developer.android.com/studio) and
   run the installer.
2. Open Android Studio once it's installed. On first launch it offers a
   **Setup Wizard** — choose the **Standard** install option and let it
   finish (this downloads the Android SDK, which takes a while).
3. Once the wizard finishes, go to **More Actions → SDK Manager** from the
   Android Studio welcome screen.
4. Click the **SDK Tools** tab and check the box for **Android SDK
   Command-line Tools (latest)**, then click **Apply** to install it.

### Step 2: Install Flutter

- **On a Mac:** open **Terminal** (press <kbd>Cmd</kbd>+<kbd>Space</kbd>,
  type "Terminal") and run:
  ```
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  brew install --cask flutter
  ```
- **On Windows:** download Flutter from
  [docs.flutter.dev/get-started/install/windows](https://docs.flutter.dev/get-started/install/windows)
  and follow the instructions there to unzip it and add it to your PATH.
- **On Linux:** download Flutter from
  [docs.flutter.dev/get-started/install/linux](https://docs.flutter.dev/get-started/install/linux)
  and follow the instructions there.

### Step 3: Get the app's source code

If you were given a link to this project on GitHub, download it — click the
green **Code** button, then **Download ZIP**, then unzip it somewhere easy to
find, like your Desktop.

(If you were sent a `.zip` file directly instead, just unzip that.)

### Step 4: Open a terminal in the project folder

- **On a Mac:** in Terminal, type `cd ` (with a space), then drag the
  unzipped folder into the window and press Return.
- **On Windows:** open the unzipped folder in File Explorer, click the
  address bar, type `powershell`, and press Return.

The app itself lives in a `mobile` subfolder, so move into it:

```
cd mobile
```

Check you're in the right place:

```
flutter --version
```

If that prints a version number, Flutter is working.

### Step 5: Accept Android SDK licenses and fetch dependencies

```
flutter doctor --android-licenses
```

Type `y` and press Return for each license it shows you. Then:

```
flutter pub get
```

### Step 6: Connect your Android phone

1. On your phone, go to **Settings → About phone**, find **Build number**,
   and tap it 7 times — this unlocks **Developer options**.
2. Go to **Settings → Developer options** and turn on **USB debugging**.
3. Plug your phone into your computer with a USB cable.
4. Your phone will show a popup asking to allow USB debugging from this
   computer — tap **Allow**.
5. Check it's detected:
   ```
   flutter devices
   ```
   Your phone should be listed by name.

### Step 7: Build and install to your phone

```
flutter run --release
```

The first build can take several minutes. When it finishes, the app installs
itself on your phone and opens automatically. Android has no expiry limit —
once it's installed, it stays installed.

**You're done.**

---

## If something goes wrong

- **`flutter devices` doesn't show your phone:** unplug and replug the USB
  cable, make sure you tapped Trust/Allow on the phone's popup, and try
  again.
- **A command fails partway through:** it's usually safe to just run the
  same command again — most of these steps pick up where they left off
  rather than starting over.
- **Anything else:** copy the exact error message and ask whoever gave you
  this project to help — it's much easier to solve with the exact wording of
  the error in hand.
