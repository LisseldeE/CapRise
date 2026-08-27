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

## 项目简介

CapRise 是一个基于 PySide6 的 Windows 桌面快捷工具栏。全局热键 <kbd>Ctrl</kbd> + <kbd>·</kbd> 唤起悬浮胶囊，截图、翻译、标注、局域网剪切板、全局搜索等日常办公所需，一触即达。

## 功能一览

- **截图**：任意方向框选截屏，实时预览，支持保存与复制
- **标注**：矩形/自由/文字标注，框内保留原内容，支持拖动与删除
- **翻译**：框选屏幕任意区域，OCR 识别并在线翻译为目标语言
- **局域网剪切板**：同房间号设备间实时同步剪贴板文本
- **全局搜索**：输入即搜，涵盖计算、已安装软件与全局文件
- **计时器**：番茄钟或倒计时，剩余时间在悬浮胶囊同步显示
- **取色器**：屏幕任意位置点击取色，一键复制颜色值

## 项目截图

![主界面](https://lisseldee.github.io/assets/images/webp/7-1.webp)

## 项目信息

- **项目名称**: CapRise
- **项目作者**: Lisselde_E
- **项目主页**: https://lisseldee.github.io/#7
- **项目仓库**: https://github.com/LisseldeE/CapRise

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
- **全局快捷键**：<kbd>Ctrl</kbd> + <kbd>·</kbd> 一键唤出/隐藏悬浮胶囊面板
- **截屏工具**：快速截取屏幕区域，支持预览、保存、复制
- **翻译工具**：框选屏幕任意区域，OCR 识别 + 在线翻译
- **标注工具**：对截屏内容进行矩形、自由形状、文字标注
- **局域网剪切板**：同房间号设备间实时同步剪贴板文本
- **设置面板**：语言切换、翻译目标语言、快捷键查看、开机自启、关于与检查更新

### 胶囊面板
- **悬浮胶囊**：简洁的胶囊形悬浮面板，跟随系统主题（深色/浅色模式自适应）
- **SVG 图标**：清晰的矢量图标，动态悬停颜色变化
- **平滑动画**：弹出/收起带有位置和透明度过渡动画
- **智能隐藏**：点击空白区域或按 ESC 键自动收起，对自家扩展窗口（家族窗口）友好不误关闭
- **系统托盘**：托盘图标常驻，支持双击唤出、右键菜单显示/退出
- **置顶显示**：面板始终置顶于所有窗口之上

### 截屏功能
- **区域选择**：支持从任意方向框选截屏区域
- **实时预览**：截屏后即时预览，确认后再保存
- **多种操作**：支持保存为文件、复制到剪贴板

### 翻译功能
- **区域框选翻译**：框选屏幕任意区域，自动识别文字并翻译为目标语言
- **系统 OCR**：调用 Windows 内置 OCR 引擎（WinRT）识别文字，无需联网
- **在线翻译**：基于 Google 免费翻译接口，免 API Key，多节点容错
- **翻译目标语言**：支持简体中文、繁體中文、English、日本語、한국어
- **翻译源语言**：源语言固定为英文（English，OCR 引擎仅识别英文），在翻译子胶囊中同样可下拉选择
- **结果卡片**：圆角结果卡片淡入显示，加载动画、结果 + 一键复制、失败重试，长文自动滚动；右上角一键删除，可立即重新框选
- **多显示器适配**：结果卡片自动在选区附近与当前屏幕内定位，避免越界

### 标注功能
- **矩形标注**：在截屏上绘制矩形框，框内保留原始内容（无遮罩），框外暗化突出重点
- **自由形状**：自由绘制标注区域
- **文字标注**：在截屏上添加文字说明
- **可编辑标注**：标注可拖动调整位置、删除；控制按钮为框顶右侧的一对圆形豆——白色豆拖动、红色豆删除，悬浮到豆区两者一同亮起，未悬浮时近乎透明不遮挡画面
- **固定底图**：框选内容与遮罩均取自同一帧桌面快照，避免底图实时刷新与框选内容割裂
- **二级工具栏**：标注工具胶囊样式二级栏，支持关闭

### 局域网剪切板
- **房间号配对**：右键剪切板按钮配置 6 位房间号，同房间号设备自动组网
- **双通道发现**：UDP 广播 + TCP 子网探测并行发现主机，规避 Windows UDP 不可靠问题
- **星型中继**：主机作为中继节点，任意设备复制的内容实时送达所有其他设备
- **自动角色仲裁**：同房间多设备自动选出一台为主机；若两端同时启动成主机，2 秒后冲突扫描按 IP 仲裁降级
- **断线自愈**：客户端断线后指数退避自动重连；重试耗尽后自动重新发现并按需自荐为主机，永不卡死在未连接
- **历史记录**：剪切板历史持久化至本地 SQLite，支持回看、点击粘贴、删除、清空
- **状态持久化**：启用状态、展开状态、房间号跨重启保留
- **回声防护**：通过 `origin_peer_id` 排除发送者，避免内容回环

### 设置功能
- **语言切换**：中文/英文界面切换，实时生效无需重启
- **翻译目标/源语言**：可配置翻译的目标语言（实时生效）与源语言（当前仅英文）
- **快捷键设置**：为各功能自定义全局快捷键，修改立即生效；支持逐项清除，并可一键重置恢复默认——重置无需核验占用、两阶段执行，即时生效
- **图标顺序**：拖拽调整工具在胶囊中的排列顺序，点击眼睛图标显示/隐藏；列表项点击不显示选中/焦点高亮，视觉更清爽
- **开机自启**：设置开机自动启动，状态持久化保存
- **关于页**：查看版本、作者、仓库信息，并支持检查更新

### 全局搜索
- **快捷唤起**：输入即搜，支持计算、已安装软件与全局文件三类结果
- **计算表达式**：直接输入算式（如 `1+2*3`、`sqrt(16)`），即时返回结果并支持一键复制
- **已安装软件**：从注册表读取已安装程序，实时模糊匹配，回车即可启动
- **全局文件**：基于 [Everything](https://www.voidtools.com/) 的文件索引能力，通过其命令行工具 `es.exe` 实现全盘毫秒级检索（含中文路径），点击直接打开
- **结果悬浮高亮**：鼠标悬浮或方向键上下移动，蓝色指示条实时跟随当前项
- **开关状态持久化**：全局文件、安装软件两个开关状态写入配置文件，重启后保持

## 更新日志

详见 [更新日志](https://github.com/LisseldeE/CapRise/blob/main/CHANGELOG.md)

## 技术栈

- **Python 3.x**：核心开发语言
- **PySide6**：Qt6 Python 绑定，GUI 框架
- **Win32 API**：全局快捷键注册、系统事件监听、系统托盘
- **WinRT**：Windows 内置 OCR 引擎（翻译功能文字识别）
- **SVG**：矢量图标渲染
- **JSON**：配置文件持久化
- **Socket（UDP + TCP）**：局域网剪切板发现与中继
- **SQLite**：剪切板历史持久化
- **Everything（es.exe）**：全局文件搜索的后端索引与检索引擎

## 项目结构

```
CapRise/
├── CapRise.py              # 主入口
├── icon.ico                 # 程序图标
├── README.md                # 中文说明
├── README_EN.md             # 英文说明
├── requirements.txt         # 依赖清单
├── modules/
│   ├── capsule.py           # 悬浮胶囊面板
│   ├── screenshot.py        # 截屏功能
│   ├── annotation.py        # 标注功能
│   ├── translate.py         # 区域翻译功能（OCR + 在线翻译）
│   ├── settings.py          # 设置对话框
│   ├── about.py             # 关于页与检查更新
│   ├── config.py            # 配置文件管理
│   ├── i18n.py              # 国际化支持
│   ├── hotkey.py            # 全局快捷键
│   ├── icons.py             # SVG 图标
│   ├── widgets.py           # 工具栏共享控件（胶囊样式图标按钮）
│   ├── overlay.py           # 全屏遮罩基类
│   ├── family.py            # 家族窗口注册（焦点感知隐藏）
│   ├── global_mouse_hook.py # 全局鼠标钩子
│   ├── keystroke.py         # 键盘事件工具
│   ├── clipboard_manager.py # 局域网剪切板协调器
│   ├── clipboard_network.py # UDP 发现 + TCP 中继网络层
│   ├── clipboard_monitor.py # 系统剪切板监听（含回声防护）
│   ├── clipboard_history.py # 剪切板历史 SQLite 持久化
│   ├── clipboard_panel.py   # 剪切板历史浮层
│   └── room_config.py       # 房间号配置对话框
```

## 配置

配置文件存储在用户目录下的 `CapRise/config.json`，包含以下设置：

- `language`：界面语言（zh_CN / en）
- `autostart`：开机自启（true / false）
- `clipboard_enabled`：局域网剪切板是否启用（true / false）
- `clipboard_expanded`：剪切板浮层是否展开（true / false）
- `clipboard_room`：剪切板房间号（6 位数字）
- `translate_target_lang`：翻译目标语言（zh-CN / zh-TW / en / ja / ko，在翻译子胶囊中切换）
- `translate_source`：翻译源（google / edge，默认 edge，手动选择，不自动切换）
- `translate_source_lang`：翻译源语言（当前仅 en 英文，OCR 引擎仅识别英文）
- `search_files_enabled`：全局文件搜索开关（true / false）
- `search_apps_enabled`：已安装软件搜索开关（true / false）

剪切板历史存储在同目录下的 `clipboard_history.db`（SQLite）。

## 开源声明

本项目采用 MIT 开源协议，详见 [LICENSE](https://github.com/LisseldeE/CapRise/blob/main/LICENSE) 文件。

## 致谢

本项目全局文件搜索功能引用并依赖 [Everything](https://www.voidtools.com/) 的索引与检索引擎（通过其命令行工具 `es.exe` 调用），感谢 Everything 开发者 David Carpenter 及 Everything 开发团队为用户提供如此优秀的本地文件搜索工具。Everything 采用 MIT 许可证，其官网为 [https://www.voidtools.com/](https://www.voidtools.com/)。

## 反馈

如有问题或新的创意欢迎和我联系！

欢迎提交 Issue 和 Pull Request！
