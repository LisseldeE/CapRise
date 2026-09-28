<p align="center">
  <img src="https://lisseldee.github.io/assets/images/webp/7-e.webp" width="100%" alt="CapRise">
</p>

<div align="center">

[![](https://img.shields.io/badge/-简体中文-555555?style=flat)](https://github.com/LisseldeE/CapRise/blob/main/README.md) [![](https://img.shields.io/badge/-English-3b82f6?style=flat)](https://github.com/LisseldeE/CapRise/blob/main/README_EN.md)

</div>

<p align="center">
  <a href="https://github.com/LisseldeE/CapRise/releases"><img src="https://img.shields.io/github/v/release/LisseldeE/CapRise" alt="Latest Release"></a>
  <a href="https://github.com/LisseldeE/CapRise/releases"><img src="https://img.shields.io/github/release-date/LisseldeE/CapRise" alt="Release Date"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/LisseldeE/CapRise" alt="License"></a>
  <img src="https://img.shields.io/badge/platform-Windows-blue" alt="Supported Platform">
</p>

<p align="center">
  <a href="#features">Features</a> |
  <a href="#download">Download</a> |
  <a href="#usage">Usage</a> |
  <a href="#open-source-license">Additional Statement</a>
</p>

## Project Introduction

CapRise is a PySide6-based desktop quick toolbar for Windows. Use the global hotkey <kbd>Ctrl</kbd> + <kbd>·</kbd> to summon a floating capsule, giving one-touch access to everyday office tools such as screenshots, screen recording, translation, annotation, weather, music, LAN clipboard sync, and global search.

## Project Screenshots

![Main Interface](https://lisseldee.github.io/assets/images/webp/7-1.webp)

## Project Information

- **Project Name**: CapRise
- **Project Author**: Lisselde_E
- **License**: MIT
- **Project Homepage**: https://lisseldee.github.io/#7
- **Project Repository**: https://github.com/LisseldeE/CapRise

## Features

| Area | Capability |
| :--- | :--- |
| **Floating Capsule** | Summoned with the <kbd>Ctrl</kbd>+<kbd>·</kbd> global hotkey; adapts to the system theme, with SVG icons that react on hover, smooth show/hide animation, always-on-top display, and smart dismissal on outside click or ESC |
| **Screenshot** | Select any screen region from any direction, preview instantly, then save or copy |
| **Annotation** | Rectangle/freeform/text annotation that keeps the boxed content intact while dimming the rest; annotatations can be dragged or deleted |
| **Translate** | Select a screen region for WinRT system OCR + online translation; offline recognition, no API key, multi-node failover, multiple target languages |
| **LAN Clipboard** | Pairing via a 6-digit room code; UDP+TCP dual-channel discovery and star relay, with self-healing reconnection and SQLite history |
| **Global Search** | Type to search: calculations, installed apps, system content, and global files (Everything); supports pinyin fuzzy matching |
| **Timer** | Pomodoro or countdown, with the remaining time shown live in the floating capsule |
| **Screen Recording** | Full-screen capture of the primary monitor at a constant 60 fps, preferring hardware H.264 encoders (NVENC / QSV / AMF, falling back to x264); the capsule shows elapsed time and a stop button while recording, and the save folder is configurable |
| **Weather** | Powered by Open-Meteo (no API key): the idle capsule shows a weather icon and live temperature; click to expand a detail card with feels-like / humidity / wind plus a 6-hour forecast, and the city is searchable with °C/°F and refresh-interval settings |
| **Music Capsule** | Reads the Windows SMTC media session and shows cover art, title and artist, with previous / play-pause / next controls |
| **Color Picker** | Click anywhere on screen to sample a color, then copy the value with one click |
| **Single Instance** | Launching the app again does not spawn another process or tray icon; it surfaces the running capsule instead |
| **Settings** | Chinese/English switching, customizable hotkeys, tool ordering/visibility, recording folder, weather city and unit, auto-start, and update checks |

## Download

<p align="center">
  <a href="https://github.com/LisseldeE/CapRise/releases">
    <img src="https://img.shields.io/badge/GitHub%20Releases-Download-181717?style=for-the-badge&logo=github&logoColor=white" alt="GitHub Releases">
  </a>
</p>

## Usage

### Quick Actions
- **Global Hotkey**: <kbd>Ctrl</kbd> + <kbd>·</kbd> to show/hide the floating capsule; other function hotkeys are customizable in Settings
- **Screenshot / Annotation / Translate**: Click the corresponding button in the capsule and select a screen region
- **LAN Clipboard**: Right-click the clipboard button to set a 6-digit room code; devices sharing the code auto-network and sync in real time
- **Global Search**: Click the search button and start typing to get calculation results, apps, and files; press Enter to launch or open
- **Timer / Color Picker**: Enable them with one click from the capsule
- **Screen Recording**: Click the record button in the capsule to start full-screen capture of the primary monitor; the status strip shows elapsed time, and the stop button saves the clip to your recording folder
- **Weather / Music**: The idle capsule shows a weather pill — click it to expand the detail card; when media is playing, the status strip shows a music segment with previous / pause / next controls

### Global Search
- **Expression Calculator**: Type an expression directly (e.g. `1+2*3`, `sqrt(16)`) for an instant result with one-click copy
- **Installed Apps / System Content**: Matched in real time from the registry (pinyin supported), launch with Enter
- **Global Files**: Powered by [Everything](https://www.voidtools.com/) (`es.exe`) for near-instant whole-disk search (Chinese paths included); click to open
- **Hover Highlight**: The blue selection bar follows your cursor in real time when hovering or using arrow keys

## Change Log

See [Changelog](https://github.com/LisseldeE/CapRise/blob/main/CHANGELOG.md)

## Tech Stack

- Python 3.x
- PySide6 (Qt6 Python bindings)
- Win32 API / WinRT (global hotkeys, system tray, built-in OCR)
- Socket (UDP + TCP, LAN clipboard)
- SQLite (clipboard history)
- Everything (es.exe, global file search)
- Open-Meteo (weather data, no API key)
- Windows Graphics Capture + FFmpeg (PyAV) (screen recording and hardware encoding)
- Windows SMTC (system media session)

## Project Structure

```
CapRise/
├── CapRise.py              # Main entry point
├── modules/
│   ├── capsule.py          # Floating capsule panel
│   ├── status_strip.py     # Capsule status strip (recording / music / timer / weather)
│   ├── screenshot.py       # Screenshot
│   ├── annotation.py       # Annotation
│   ├── translate.py        # Region translate (OCR + online translation)
│   ├── search.py           # Global search
│   ├── clipboard_*.py      # LAN clipboard (manager/network/monitor/history/panel/room config)
│   ├── timer.py            # Timer
│   ├── recorder.py         # Screen recording (WGC capture + hardware-first H.264 encoding)
│   ├── music.py            # Music capsule (Windows SMTC session and playback control)
│   ├── weather.py          # Weather service and detail card
│   ├── color_picker.py     # Color picker
│   ├── settings.py         # Settings dialog
│   ├── hotkey.py           # Global hotkeys
│   ├── single_instance.py  # Single-instance protection
│   ├── config.py / i18n.py # Configuration & internationalization
│   └── ...
```

## Open Source License

This project is licensed under the MIT License. See [LICENSE](https://github.com/LisseldeE/CapRise/blob/main/LICENSE) file for details.

## Acknowledgments

The global file search feature of this project references and depends on [Everything](https://www.voidtools.com/)'s index and retrieval engine (invoked through its command-line tool `es.exe`). Thanks to Everything developer David Carpenter and the Everything team. Everything is licensed under the MIT License, and its official website is [https://www.voidtools.com/](https://www.voidtools.com/).

## Feedback

If you have any questions or new ideas, feel free to contact me! Issues and Pull Requests are welcome!