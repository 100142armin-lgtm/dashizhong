# 时钟闹钟

下载正式版本：[GitHub Releases](https://github.com/100142armin-lgtm/dashizhong/releases/latest)。
版本变化与升级说明见 [更新日志](CHANGELOG.md)。

功能：

- 闹钟、世界时钟和倒计时（含闹铃声音）
- 待办事项和便签
- 区域截图与标注编辑
- 屏幕录像
- 视频播放器（本地文件、在线视频链接和 YouTube；保留 `yt-dlp`）
- 电脑清理
- 开机自启动

## 运行

```bat
pip install -r requirements.txt
python main.py
```

快捷键：`Ctrl+Alt+T` 打开时钟界面，`Ctrl+Alt+A` 区域截图。

## 打包

```bat
pip install pyinstaller
python -m PyInstaller --noconfirm Clock-Alarm.spec
```

便携目录为 `dist\Clock-Alarm\`，入口为 `Clock-Alarm.exe`。安装包可用
`ISCC installer\Clock-Alarm.iss` 构建，产物位于 `dist\release\`。

## License

MIT

## 如何发布新版本

本项目使用 GitHub Actions 自动构建和发布。发布正式版本时，只推送源码和
Git Tag，不要在 GitHub 网页中手工创建 Release，也不要手工上传、替换或删除
Release 文件。所有正式产物和 Attestation 都必须由 GitHub Actions 生成。

### 发布步骤

#### 1. 确保代码已提交并推送

```bash
# 查看当前状态
git status

# 添加并提交本次修改
git add .
git commit -m "你的改动说明"

# 推送到 GitHub
git push origin main
```

#### 2. 创建版本 Tag

版本号格式必须为 `v主版本.次版本.修订版本`，并与根目录 `VERSION` 文件一致。
例如，`VERSION` 为 `1.0.10` 时：

```bash
git tag -a v1.0.10 -m "Release version 1.0.10"
```

#### 3. 推送 Tag 触发自动构建

```bash
git push origin v1.0.10
```

推送后，GitHub Actions 会自动测试和构建项目、生成便携包与 Windows 安装包、
为最终文件生成 Build Provenance Attestation，并由 `github-actions[bot]` 创建
Release 和上传文件。

#### 4. 查看构建结果

- 构建进度：打开仓库的 **Actions** 页面。
- 发布结果：打开仓库的 **Releases** 页面。
- 只有发布工作流全部成功，且 Release 资产具有有效 Attestation，才可作为正式版。

### 版本号说明

| 版本号格式 | 使用场景 | 示例 |
|---|---|---|
| `vX.0.0` | 重大更新或不兼容改动 | `v2.0.0` |
| `vX.Y.0` | 新增功能 | `v1.1.0` |
| `vX.Y.Z` | 修复问题 | `v1.0.1` |

### 如果构建失败怎么办

不要在 GitHub 网页中手工补传文件。应先打开 Actions 页面查看日志并修复代码，
然后删除失败的 tag，提交修复后重新创建并推送相同版本 tag：

```bash
git tag -d v1.0.10
git push origin :refs/tags/v1.0.10
git tag -a v1.0.10 -m "Release version 1.0.10"
git push origin v1.0.10
```
