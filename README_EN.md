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

## Project Introduction

CapRise is a PySide6-based Windows desktop quick toolbar. Use the global hotkey <kbd>Ctrl</kbd> + <kbd>·</kbd> to summon a floating capsule, giving one-touch access to everyday office tools like screenshots, translation, annotation, LAN clipboard sync, and global search.

## Features at a Glance

- **Screenshot**: Select any screen region from any direction, preview instantly, and save or copy
- **Annotation**: Rectangle/freeform/text annotation that keeps the boxed content intact, with drag and delete support
- **Translate**: Select a screen region to OCR-recognize and translate text into the target language
- **LAN Clipboard**: Real-time text clipboard sync across devices sharing the same room code
- **Global Search**: Type to search and cover calculations, installed apps, and global files at once
- **Timer**: Pomodoro or countdown, with the remaining time shown live in the floating capsule
- **Color Picker**: Sample a color anywhere on screen by clicking, then copy the value with one click

## 项目截图

![Main Interface](https://lisseldee.github.io/assets/images/webp/7-1.webp)

## Project Information

- **Project Name**: CapRise
- **Project Author**: Lisselde_E
- **Project Homepage**: https://lisseldee.github.io/#7
- **Project Repository**: https://github.com/LisseldeE/CapRise

## Download

<p align="center">
  <a href="https://github.com/LisseldeE/CapRise/releases">
    <img src="https://img.shields.io/badge/GitHub-Releases-181717?style=flat-square&logo=github&logoColor=white" alt="GitHub Releases">
  </a>
  &nbsp;&nbsp;
  <a href="https://gitee.com/Lisselde_E/CapRise/releases">
    <img src="https://img.shields.io/badge/Gitee-Mirror-C71D23?style=flat-square&logo=gitee&logoColor=white" alt="Gitee Mirror">
  </a>
</p>

> 💡 Users in China are recommended to use the Gitee mirror.

## Usage

### Quick Actions
- **Global Hotkey**: <kbd>Ctrl</kbd> + <kbd>·</kbd> to show/hide the floating capsule panel
- **Screenshot Tool**: Quickly capture screen regions with preview, save, and copy support
- **Translate Tool**: Select any screen region for OCR recognition + online translation
- **Annotation Tool**: Annotate screenshots with rectangles, freeform shapes, and text
- **LAN Clipboard**: Real-time text clipboard sync across devices with the same room code
- **Settings Panel**: Language switching, translate target language, hotkey display, auto-start, and about

### Capsule Panel
- **Floating Capsule**: Clean capsule-shaped floating panel, adapts to system theme (dark/light mode)
- **SVG Icons**: Crisp vector icons with dynamic hover color changes
- **Smooth Animation**: Position and opacity transition animations for show/hide
- **Smart Dismiss**: Click outside or press ESC to auto-hide, friendly to its own extension windows (family windows)
- **System Tray**: Persistent tray icon; double-click to summon, right-click for Show/Exit
- **Always on Top**: Panel stays above all windows

### Screenshot Features
- **Area Selection**: Drag to select any screen region from any direction
- **Live Preview**: Instant preview after capture before saving
- **Multiple Actions**: Save as file or copy to clipboard

### Translate Features
- **Region Translate**: Select any screen region, auto-recognize text and translate to the target language
- **System OCR**: Uses the Windows built-in OCR engine (WinRT); no network needed for recognition
- **Online Translation**: Based on Google's free endpoint, no API key, with multi-host failover
- **Target Languages**: Simplified Chinese, Traditional Chinese, English, Japanese, Korean
- **Source Language**: Fixed to English (the OCR engine only recognises English); also selectable as a dropdown in the translation sub-capsule
- **Result Card**: Rounded card fades in with a loading animation, result + one-click copy, retry on failure, and scrolling for long text; a one-click delete button in the top-right lets you immediately draw a fresh selection
- **Multi-Monitor Safe**: The card auto-anchors near the selection within the current screen, never overflowing

### Annotation Features
- **Rectangle Annotation**: Draw rectangles on screenshots; the boxed region keeps the original content (no overlay) while the outside is dimmed to highlight it
- **Freeform Annotation**: Freehand drawing for annotation areas
- **Text Annotation**: Add text labels to screenshots
- **Editable Annotations**: Drag to reposition or delete; the controls are a pair of circular beans at the top-right — the white bean drags, the red bean deletes. Hovering the bean area lights both together, and idle beans stay near-transparent so they never obscure the captured content
- **Fixed Snapshot Base**: The boxed content and the dimmed overlay come from one frozen desktop frame, so the background and selection never visually desync
- **Secondary Toolbar**: Capsule-style secondary toolbar with close support

### LAN Clipboard
- **Room Pairing**: Right-click the clipboard button to set a 6-digit room code; devices sharing the code auto-form a network
- **Dual-Channel Discovery**: UDP broadcast + TCP subnet probe run in parallel to locate the host, sidestepping Windows' unreliable UDP delivery
- **Star Relay**: The host acts as a relay node; any device's copy is delivered to all other devices in real time
- **Automatic Role Arbitration**: Multiple devices in the same room automatically elect one host; if two devices both become hosts on near-simultaneous startup, a conflict scan 2 seconds later demotes the higher-IP host via IP tiebreaker
- **Self-Healing on Disconnect**: Clients auto-reconnect with exponential backoff; after retries are exhausted, the manager re-discovers and self-promotes to host if needed — never strands the user in "disconnected"
- **History**: Clipboard history persists to local SQLite, supporting review, click-to-paste, delete, and clear
- **State Persistence**: Enabled state, expanded state, and room code survive restarts
- **Echo Guard**: Sender excluded via `origin_peer_id` to prevent content loops

### Settings Features
- **Language Switching**: Toggle between Chinese and English, takes effect immediately without restart
- **Translate Target/Source Language**: Configure the translation target language (takes effect immediately) and the source language (currently English only)
- **Hotkey Configuration**: Assign custom global hotkeys per feature, applied instantly; supports per-row clear and one-click reset to defaults — the reset skips occupancy checks and runs in two passes so it takes effect immediately
- **Tool Order**: Drag to reorder the tools in the capsule and click the eye icon to show/hide each one; items show no selection/focus highlight on click for a cleaner look
- **Auto-start**: Set to launch on system boot, persisted to configuration
- **About Page**: View version, author, and repository info, with check-for-update support

### Global Search
- **Type-to-search**: One input box covers calculations, installed apps, and global files
- **Expression Calculator**: Type an expression directly (e.g. `1+2*3`, `sqrt(16)`) for an instant result with one-click copy
- **Installed Apps**: Matches installed programs read from the registry, launch with Enter
- **Global Files**: Powered by [Everything](https://www.voidtools.com/)'s file index via its command-line tool `es.exe` — near-instant whole-disk search (Chinese paths included), click to open
- **Hover Highlight**: The blue selection bar follows the cursor in real time when hovering or using arrow keys
- **Persistent Toggles**: The 全局文件 / 安装软件 switch states are saved to the config file and restored on restart

## Changelog

See [Changelog](https://github.com/LisseldeE/CapRise/blob/main/CHANGELOG.md)

## Tech Stack

- **Python 3.x**: Core development language
- **PySide6**: Qt6 Python bindings, GUI framework
- **Win32 API**: Global hotkey registration, system event monitoring, system tray
- **WinRT**: Windows built-in OCR engine (text recognition for the translate feature)
- **SVG**: Vector icon rendering
- **JSON**: Configuration file persistence
- **Socket (UDP + TCP)**: LAN clipboard discovery and relay
- **SQLite**: Clipboard history persistence
- **Everything (es.exe)**: Backend index & retrieval engine for global file search

## Project Structure

```
CapRise/
├── CapRise.py              # Main entry point
├── icon.ico                 # Application icon
├── README.md                # Chinese documentation
├── README_EN.md             # English documentation
├── requirements.txt         # Dependency manifest
├── modules/
│   ├── capsule.py           # Floating capsule panel
│   ├── screenshot.py        # Screenshot functionality
│   ├── annotation.py        # Annotation functionality
│   ├── translate.py         # Region translate (OCR + online translation)
│   ├── settings.py          # Settings dialog
│   ├── about.py             # About page and check-for-update
│   ├── config.py            # Configuration management
│   ├── i18n.py              # Internationalization
│   ├── hotkey.py            # Global hotkey
│   ├── icons.py             # SVG icons
│   ├── widgets.py           # Shared toolbar widgets (capsule-style icon buttons)
│   ├── overlay.py           # Full-screen overlay base class
│   ├── family.py            # Family-window registry (focus-aware hide)
│   ├── global_mouse_hook.py # Global mouse hook
│   ├── keystroke.py         # Keystroke utilities
│   ├── clipboard_manager.py # LAN clipboard coordinator
│   ├── clipboard_network.py # UDP discovery + TCP relay network layer
│   ├── clipboard_monitor.py # System clipboard monitor (with echo guard)
│   ├── clipboard_history.py # Clipboard history SQLite persistence
│   ├── clipboard_panel.py   # Clipboard history floating panel
│   └── room_config.py       # Room code configuration dialog
```

## Configuration

Configuration file is stored at `CapRise/config.json` under the user home directory, with the following settings:

- `language`: Interface language (zh_CN / en)
- `autostart`: Auto-start on boot (true / false)
- `clipboard_enabled`: Whether LAN clipboard is enabled (true / false)
- `clipboard_expanded`: Whether the clipboard panel is expanded (true / false)
- `clipboard_room`: Clipboard room code (6-digit number)
- `translate_target_lang`: Translate target language (zh-CN / zh-TW / en / ja / ko, switched in the translation sub-capsule)
- `translate_source`: Translation provider (google / edge, default edge, chosen manually, never auto-switched)
- `translate_source_lang`: Translation source language (currently en / English only, as the OCR engine only recognises English)
- `search_files_enabled`: Whether global file search is enabled (true / false)
- `search_apps_enabled`: Whether installed-app search is enabled (true / false)

Clipboard history is stored in `clipboard_history.db` (SQLite) in the same directory.

## License

This project is licensed under the MIT License. See [LICENSE](https://github.com/LisseldeE/CapRise/blob/main/LICENSE) file for details.

## Acknowledgments

The global file search feature of this project references and depends on [Everything](https://www.voidtools.com/)'s index and retrieval engine (invoked through its command-line tool `es.exe`). Thanks to Everything's developer David Carpenter and the Everything team for providing such an excellent local file search tool. Everything is licensed under the MIT License, and its official website is [https://www.voidtools.com/](https://www.voidtools.com/).

## Feedback

If you have any questions or new ideas, feel free to contact me!

Issues and Pull Requests are welcome!