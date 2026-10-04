# 仓库发布与维护规范 (Repository & Release Guidelines)

## 官方发布目标仓库
本项目（Clock/Alarm 大时钟桌面应用）的代码更新、优化及版本发布，**唯一指定的最终发布仓库**为：
👉 **https://github.com/100142armin-lgtm/dashizhong**

### 核心规范
1. **Git Remote 绑定**：
   - 本地仓库 `origin` 必须始终保持指向 `https://github.com/100142armin-lgtm/dashizhong.git`。
2. **版本推送与发布**：
   - 后续任何功能更新与优化，在全量测试通过后，均推送到此仓库的 `main` 分支。
   - 最终正式版本发布时，打上与 `VERSION` 匹配的标签（如 `v1.0.20`），并推送到 `https://github.com/100142armin-lgtm/dashizhong` 触发 GitHub Actions 自动化构建。
3. **软件内更新源维护**：
   - `update_checker.py` 中的 `DEFAULT_REPO` 必须为 `"100142armin-lgtm/dashizhong"`，确保用户软件自动检查并更新来自该仓库的最新版本。
