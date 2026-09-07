<p align="center">
  <img src="https://lisseldee.github.io/assets/images/webp/7-e.webp" width="100%" alt="CapRise">
</p>

<div align="center">

[![](https://img.shields.io/badge/-简体中文-3b82f6?style=flat)](https://github.com/LisseldeE/CapRise/blob/main/README.md) [![](https://img.shields.io/badge/-English-555555?style=flat)](https://github.com/LisseldeE/CapRise/blob/main/README_EN.md)

</div>

<p align="center">
  <a href="https://github.com/LisseldeE/CapRise/releases"><img src="https://img.shields.io/github/v/release/LisseldeE/CapRise" alt="最新版本"></a>
  <a href="https://github.com/LisseldeE/CapRise/releases"><img src="https://img.shields.io/github/release-date/LisseldeE/CapRise" alt="发布时间"></a>
  <a href="LICENSE"><img src="https://img.shields.io/github/license/LisseldeE/CapRise" alt="开源协议"></a>
  <img src="https://img.shields.io/badge/platform-Windows-blue" alt="支持平台">
</p>

<p align="center">
  <a href="#功能特性">功能特性</a> |
  <a href="#下载">下载</a> |
  <a href="#使用方法">使用方法</a> |
  <a href="#开源声明">补充声明</a>
</p>

## 项目简介

CapRise 是一个基于 PySide6 的 Windows 桌面快捷工具栏。全局热键 <kbd>Ctrl</kbd> + <kbd>·</kbd> 唤起悬浮胶囊，截图、翻译、标注、局域网剪切板、全局搜索等日常办公所需，一触即达。

## 项目截图

![主界面](https://lisseldee.github.io/assets/images/webp/7-1.webp)

## 项目信息

- **项目名称**: CapRise
- **项目作者**: Lisselde_E
- **开源协议**: MIT
- **项目主页**: https://lisseldee.github.io/#7
- **项目仓库**: https://github.com/LisseldeE/CapRise

## 功能特性

| 维度 | 能力说明 |
| :--- | :--- |
| **悬浮胶囊** | <kbd>Ctrl</kbd>+<kbd>·</kbd> 全局热键唤起；随系统主题自适应，SVG 图标动态悬停，平滑动画、置顶显示、点击空白或 ESC 智能隐藏 |
| **截图** | 任意方向框选截屏，实时预览，支持保存与复制 |
| **标注** | 矩形/自由/文字标注，框内保留原内容、框外暗化突出重点，支持拖动与删除 |
| **翻译** | 框选屏幕区域，WinRT 系统 OCR 识别 + 在线翻译，无需联网识别、免 API Key，多节点容错，支持多目标语言 |
| **局域网剪贴板** | 6 位房间号组网，UDP+TCP 双通道发现、主机星型中继，断线自愈，历史回看持久化到 SQLite |
| **全局搜索** | 输入即搜：计算、已安装软件、系统内容、全局文件（Everything），支持拼音模糊匹配 |
| **计时器** | 番茄钟/倒计时，剩余时间在悬浮胶囊同步显示 |
| **取色器** | 屏幕任意位置点击取色，一键复制颜色值 |
| **设置** | 中英切换、快捷键自定义、图标排序/显隐、开机自启、检查更新 |

## 下载

<p align="center">
  <a href="https://github.com/LisseldeE/CapRise/releases">
    <img src="https://img.shields.io/badge/GitHub-Releases-181717?style=flat-square&logo=github&logoColor=white" alt="GitHub Releases">
  </a>
  &nbsp;&nbsp;
  <a href="https://gitee.com/Lisselde_E/CapRise/releases">
    <img src="https://img.shields.io/badge/Gitee-镜像下载-C71D23?style=flat-square&logo=gitee&logoColor=white" alt="Gitee 镜像下载">
  </a>
</p>

> 💡 国内用户推荐使用 Gitee 镜像下载

## 使用方法

### 快捷操作
- **全局热键**：<kbd>Ctrl</kbd> + <kbd>·</kbd> 一键唤出/隐藏悬浮胶囊，其他功能快捷键可在设置中自定义
- **截图 / 标注 / 翻译**：从胶囊点击对应按钮，框选屏幕区域即可
- **局域网剪贴板**：右键剪贴板按钮设置 6 位房间号，同房间设备自动组网并实时同步
- **全局搜索**：点击搜索按钮，输入内容即得计算结果、应用与文件，回车启动或打开
- **计时器 / 取色器**：从胶囊一键启用即可

### 全局搜索
- **计算表达式**：直接输入算式（如 `1+2*3`、`sqrt(16)`），即时返回结果并支持一键复制
- **已安装软件 / 系统内容**：从注册表读取并实时模糊匹配（支持拼音），回车即可启动
- **全局文件**：基于 [Everything](https://www.voidtools.com/)（`es.exe`），实现全盘毫秒级检索（含中文路径），点击直接打开
- **结果悬浮高亮**：鼠标悬浮或方向键上下移动，蓝色指示条实时跟随当前项

## 更新日志

详见 [更新日志](https://github.com/LisseldeE/CapRise/blob/main/CHANGELOG.md)

## 技术栈

- Python 3.x
- PySide6（Qt6 Python 绑定）
- Win32 API / WinRT（全局快捷键、系统托盘、内置 OCR）
- Socket（UDP + TCP，局域网剪切板）
- SQLite（剪切板历史）
- Everything（es.exe，全局文件搜索）

## 项目结构

```
CapRise/
├── CapRise.py              # 主入口
├── modules/
│   ├── capsule.py          # 悬浮胶囊面板
│   ├── screenshot.py       # 截屏
│   ├── annotation.py       # 标注
│   ├── translate.py        # 区域翻译（OCR + 在线翻译）
│   ├── search.py           # 全局搜索
│   ├── clipboard_*.py      # 局域网剪切板（管理/网络/监听/历史/面板/房间配置）
│   ├── timer.py            # 计时器
│   ├── color_picker.py     # 取色器
│   ├── settings.py         # 设置对话框
│   ├── hotkey.py           # 全局快捷键
│   ├── config.py / i18n.py # 配置管理与国际化
│   └── ...
```

## 开源声明

本项目采用 MIT 开源协议，详见 [LICENSE](https://github.com/LisseldeE/CapRise/blob/main/LICENSE) 文件。

## 致谢

本项目全局文件搜索功能引用并依赖 [Everything](https://www.voidtools.com/) 的索引与检索引擎（通过其命令行工具 `es.exe` 调用），感谢 Everything 开发者 David Carpenter 及 Everything 团队。Everything 采用 MIT 许可证，官网为 [https://www.voidtools.com/](https://www.voidtools.com/)。

## 反馈

如有问题或新的创意欢迎和我联系！欢迎提交 Issue 和 Pull Request！