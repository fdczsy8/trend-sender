# 开发者资讯日报（GitHub Actions + QQ 邮箱推送）

每天自动抓取 7 个技术社区热榜，过滤去重后生成 HTML 邮件推送到你的 QQ 邮箱，
同时输出一份 Markdown 清单存档。专注找：**好玩的前端 Demo、安卓小工具、AI 语音模型、
网页打包素材、音乐播放器、黄历/日历源码**，优先展示**单 HTML 文件项目**（方便直接 FusionApp 打包）。

## 数据源

| key | 数据源 | 说明 |
|---|---|---|
| `github` | GitHub Trending | 每日热门开源项目，含今日新增 star |
| `gitee` | Gitee 热榜 | 国内开源热门项目 |
| `huggingface` | HuggingFace | 热门模型 + Space 在线 Demo（各占一半） |
| `modelscope` | 魔搭 ModelScope | 国内 AI 模型社区热门项目 |
| `codepen` | CodePen 热门 | 前端在线 Demo，自动标注【单HTML】 |
| `juejin` | 掘金热榜 | 中文技术文章 |
| `v2ex` | V2EX 热议 | 创意/技巧讨论帖 |

已按要求**排除 arxiv 等学术论文内容**（黑名单默认含 `论文`、`arxiv`）。

## 功能一览

- 每条内容带 标题 / 简介（自动裁剪去乱码）/ 热度 / 直达链接
- 自动分类标签：`前端` `AI模型` `安卓工具` `在线Demo` `教程`
- Star 热度阈值过滤（可在 config.json 按源分别设置，或 Actions 运行时临时指定）
- 白名单关键词命中 → `⭐` 置顶展示（默认含 FusionApp、TTS、前端、webview、播放器、黄历、日历等）
- 单 HTML 文件项目 → 标注 `【单HTML】` 同样置顶，方便网页打包
- 黑名单关键词命中 → 直接丢弃
- `cache/history.json` 本地缓存去重，默认 7 天内重复内容不再推送
- 请求间延时限速 + 超时自动重试；抓取失败单独发报错提醒邮件
- 邮件顶部当日统计：总条数 / 命中关注词 / 单HTML数量 / 各数据源成败
- 两种模式：`full` 完整版（带简介）/ `compact` 精简版（只标题+链接）
- 额外输出 `output/digest-*.md` Markdown 清单（Actions Artifact 可下载）

## 一、创建 QQ 邮箱授权码（不是 QQ 密码！）

1. 电脑登录 [mail.qq.com](https://mail.qq.com) → 设置 → **账号与安全**
2. 找到 **POP3/IMAP/SMTP...服务设置**，开启 **SMTP 服务**（需要手机验证）
3. 开启后系统会生成一串 **授权码**（16 位字母），记下来
4. GitHub 仓库 → Settings → Secrets and variables → Actions → New repository secret，添加：

| Secret 名 | 值 |
|---|---|
| `SMTP_USER` | 你的 QQ 邮箱，如 `123456789@qq.com` |
| `SMTP_PASS` | 上面申请的**授权码** |
| `MAIL_TO` | 收件邮箱，多个用逗号分隔（可就是同一个 QQ 邮箱） |
| `MAIL_FROM` | 可不填，默认等于 `SMTP_USER` |

> SMTP 服务器已在 workflow 写死为 `smtp.qq.com:465`（SSL），无需配置。

## 二、推送到 GitHub 并启用工作流

```bash
git init
git add .
git commit -m "feat: 资讯日报脚本"
git remote add origin https://github.com/<你的用户名>/<仓库名>.git
git push -u origin main
```

推送后 Actions 页签会出现 **资讯日报邮件推送** 工作流，需点一次 "I understand my workflows, go ahead and enable them"。

- **定时**：每天北京时间 08:00、20:00 自动运行
- **手动**：Actions → 该工作流 → Run workflow，可直接在弹窗里选模式、Star 下限、开关任意数据源，不用改代码

## 三、开关数据源 / 调整参数（不改抓取代码）

两种方式，优先级：手动运行时填的 Inputs > 仓库 Variables > `config.json`。

Settings → Secrets and variables → Actions → **Variables** 里可加：

| Variable | 示例值 | 作用 |
|---|---|---|
| `SRC_GITEE` | `false` | 关闭某个数据源（key 见上表） |
| `MODE` | `compact` | 默认邮件模式 |
| `MIN_STARS` | `100` | 全局 Star 下限（命中白名单的项目不受此限制） |
| `DEDUP_DAYS` | `10` | 去重天数 |

关键词、分类、各源默认阈值等都改 [config.json](config.json) 即可，无需动 Python 代码。

## 四、本地测试

```bash
pip install -r requirements.txt
python main.py --no-email        # 只抓取生成 output/digest.html，不发邮件
python main.py                   # 需要先在环境变量里配置 SMTP_USER 等（见下）
```

Windows PowerShell 临时设置环境变量：

```powershell
$env:SMTP_HOST="smtp.qq.com"; $env:SMTP_PORT="465"
$env:SMTP_USER="123456789@qq.com"; $env:SMTP_PASS="授权码"
$env:MAIL_TO="123456789@qq.com"
python main.py
```

## 注意事项

- **去重缓存依赖 git 回写**：workflow 每次运行成功后会把 `cache/history.json` 提交回仓库，请勿删除该文件；fork 使用或换了私有仓库需确认 Actions 有 `contents: write` 权限（本文件已声明）。
- **Gitee / CodePen 是网页解析**，官方无稳定 API，页面改版时抓取会失败并触发报错邮件，届时只需更新 `sources.py` 里对应解析选择器。
- V2EX / HuggingFace 在个别网络环境下可能超时，失败不影响其他源。
- `【单HTML】` 判定是启发式的：CodePen 项目直接认定；GitHub/Gitee 项目主语言为 HTML 或简介含"单文件/纯HTML"等关键词时标注。拿到后仍建议打开仓库确认是否只有一个 html 文件。
- QQ 邮箱授权码长期有效，但如果换绑手机或关闭 SMTP 服务会失效，重新生成并更新 `SMTP_PASS` 即可。

## 文件结构

```
main.py                      # 入口：编排全流程 + 报错邮件
sources.py                   # 7 个数据源抓取（重试/限速）
pipeline.py                  # 配置加载/关键词过滤/分类/去重/排序
report.py                    # HTML 邮件 + Markdown 生成
mailer.py                    # QQ 邮箱 SMTP 发送
config.json                  # 关键词/阈值/分类/开关配置
cache/history.json           # 去重历史（Actions 自动回写）
output/                      # 每次运行的 md / html 存档（Actions 上传 artifact）
.github/workflows/digest.yml # 定时 + 手动工作流
```
