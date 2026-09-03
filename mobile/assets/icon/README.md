# App icon placeholder

Drop a **1024x1024 `icon.png`** in this directory (fitness-themed artwork, to
be generated separately — not part of this commit), then regenerate the
platform-specific icon files from `mobile/`:

```
dart run flutter_launcher_icons
```

Configuration lives in `mobile/flutter_launcher_icons.yaml` (adaptive icon
background is set to the app's light teal seed color from
`lib/app/app.dart`). Nothing has been generated yet — this directory holds
only this placeholder note until the real `icon.png` is added.
