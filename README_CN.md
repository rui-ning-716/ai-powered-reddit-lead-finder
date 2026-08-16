# Reddit Lead Finder 中文说明

[English README](README.md)

**输入一个产品链接，自动建立完整的 Reddit Marketing Campaign。**

Reddit Lead Finder 会研究产品网站，生成产品 Campaign，寻找相关 Reddit 帖子，
判断购买意图和产品匹配度，并为值得回复的帖子生成个性化草稿。

它是一个开源、自部署、人工审核的 Reddit 营销与获客工具。系统不会自动发帖、
自动私信或自动投票，每一条回复都由用户最终决定。

## 从产品链接到回复草稿

1. **输入产品链接**

   填写产品的公开网站。系统会读取有限数量的公开产品页面。

2. **AI 自动建立 Campaign**

   AI 自动生成产品介绍、价值主张、目标客户、竞品、市场、购买信号、
   Reddit 搜索词和相关 subreddit。

3. **寻找相关 Reddit 帖子**

   Perplexity Search API 根据用户可能使用的自然语言搜索公开 Reddit 页面。
   帖子不需要出现完全相同的产品名称，只要问题、需求或购买场景相关即可进入分析。
   当主搜索结果不足时，可以选择使用 Apify 兜底。

4. **判断购买意图和产品匹配度**

   OpenAI 分析帖子相关性、购买意图、产品匹配度、紧迫度、可回复性、
   市场匹配度和推广风险。

5. **生成个性化回复草稿**

   符合条件的帖子会获得回复策略和草稿。分数较低的候选帖子仍会显示在
   **Skipped** 中，并保留 AI 判断原因，不会直接消失。

6. **人工审核并发布**

   用户阅读原帖、检查 subreddit 规则、修改草稿，然后决定是否亲自发布。

```text
产品链接
    -> AI 产品 Campaign
    -> 相关 Reddit 帖子
    -> 购买意图与产品匹配评分
    -> 个性化回复草稿
    -> 人工审核与发布
```

## AI 自动生成的 Campaign 包含什么

Product Setup 包含六个可以编辑的部分：

1. **Product**：产品介绍、价值主张、目标客户、竞品和产品限制
2. **Market**：国家、语言、客户信号和排除条件
3. **Discovery**：用户搜索语言、核心 subreddit、相邻社区和搜索时间范围
4. **Qualification**：购买信号、噪音信号、最低分数和帖子最大年龄
5. **Engagement**：回复语气、品牌提及、链接、身份披露和字数限制
6. **Review & Test**：使用一篇样本 Reddit 帖子测试评分、策略和草稿

所有内容都可以在 Campaign 保存前由用户审核和修改。

## 适合谁使用

- Growth 和 Product Marketing 团队
- Founder 和早期 Startup
- 同时管理多个产品或客户的 Agency
- 希望发现正在选型或寻找解决方案的 Sales 和 Community 团队
- 希望使用 AI 提高效率，但不希望自动发帖的运营人员

## 核心功能

- 根据产品网站自动生成完整 Campaign
- 语义搜索与关键词搜索结合的 Reddit 帖子发现
- 覆盖产品、竞品、用户痛点、推荐、价格、迁移和产品比较场景
- Perplexity 作为主搜索服务
- 可选的 Apify 兜底
- OpenAI 购买意图和产品匹配分析
- 可解释的多维度评分
- 先选择回复策略，再生成草稿
- 个性化且可以编辑的回复草稿
- 每一条回复都需要人工批准
- 多产品和多客户独立工作区
- `Needs review`、`Ready to reply`、`Published` 和 `Skipped` 工作流
- Slack 和邮件通知
- SQLite、CSV、Markdown 和 Performance 报告
- 跨帖去重
- 可选的 Dashboard 密码保护
- 支持 Docker 和本地 Python 安装

## V0.7.5 如何搜索帖子

Perplexity 是主要搜索服务。系统会把每条 Campaign query 作为独立的 Search API
请求发送，并将域名限制为 `reddit.com`，同时使用 Campaign 中选择的时间范围。
返回结果经过 Reddit 帖子识别、格式转换和去重后，才会交给 OpenAI 分析。

搜索以召回相关需求为优先。即使帖子没有写出产品名称，只要它表达了相关问题、
竞品不满、产品比较、迁移需求、实施问题或相同目标，也可以被判断为相关候选帖子。

Apify 是可选兜底。只有启用 Apify，并且 Perplexity 失败或有效结果少于设定数量时，
系统才会调用 Apify。Apify 不抓取评论，也不开启 Actor 自带的 AI 分析。

默认每小时自动扫描一次，每轮最多将 150 篇新帖子发送给 OpenAI 分析。
用户也可以随时手动扫描。

## 使用 Docker 快速开始

```bash
git clone https://github.com/rui-ning-716/reddit-lead-finder.git
cd reddit-lead-finder
cp .env.example .env
```

在 `.env` 中填写：

```text
OPENAI_API_KEY=你的_OpenAI_Key
PERPLEXITY_API_KEY=你的_Perplexity_Key

# 可选兜底
APIFY_API_TOKEN=
```

启动：

```bash
docker compose up --build
```

打开 [http://localhost:8000](http://localhost:8000)。

## 不使用 Docker，在 Mac 本地运行

```bash
git clone https://github.com/rui-ning-716/reddit-lead-finder.git
cd reddit-lead-finder
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

填写 `.env` 后运行：

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

打开 [http://127.0.0.1:8000](http://127.0.0.1:8000)。

## 第一次建立 Campaign

1. 在首页输入一个产品公开网站。
2. 点击 **Generate product setup**。
3. 检查 Product Setup 的六个部分。
4. 在 Discovery 中检查搜索词、subreddit、时间范围和每条 query 的结果数量。
5. 在 Qualification 中检查最低分数和帖子最大年龄。
6. 使用一篇样本 Reddit 帖子测试评分和回复草稿。
7. 点击 **Save and find opportunities**。
8. 在 **Reply Opportunities** 中审核真实帖子和 AI 草稿。

点击 **+ Add product** 可以为其他产品或客户建立完全独立的工作区。

## Opportunity 评分

AI 会返回多个独立评分，最终 Priority 由程序根据 Campaign 设置的权重和扣分重新计算。

| 维度 | 判断内容 |
| --- | --- |
| Relevance | 帖子是否涉及相同问题或使用场景 |
| Purchase intent | 用户是否正在寻找、比较、替换或准备购买解决方案 |
| Product fit | 产品能否真正解决用户需求 |
| Urgency | 用户是否需要尽快解决问题 |
| Reachability | 一条公开回复是否能够提供帮助 |
| Market fit | 是否存在明确的市场匹配或不匹配证据 |
| Promotion risk | 品牌参与回复是否会显得打扰或过度推广 |

没有提到预算、地区、公司规模或时间，不会自动被判定为不合格。只有明确不匹配的
证据才会降低 Priority。

## 回复策略

- `helpful_only`：只提供帮助，不提产品
- `expert_answer`：提供专业建议，不提产品
- `soft_mention`：先提供帮助，再披露身份并简短提及产品
- `direct_recommendation`：只用于明确寻找推荐且产品匹配度很高的帖子
- `skip`：不建议参与

品牌提及和链接必须遵守 Campaign 设置。系统不会自动发布草稿。

## 多产品管理和报告

每个 Product Workspace 都有独立的 Campaign、帖子、草稿、状态、通知、负责人、
结果和转化价值。同一个 Reddit 帖子可以针对不同产品分别评分，不会混合数据。

打开 `/report` 查看 Performance，或者通过 `/report.csv` 导出数据。
运营流程说明见 [`docs/MANAGED_SERVICE.md`](docs/MANAGED_SERVICE.md)。

## 可选通知

Slack：

```text
SLACK_NOTIFICATIONS_ENABLED=true
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
SLACK_MIN_INTENT_SCORE=0.72
```

Email：

```text
EMAIL_NOTIFICATIONS_ENABLED=true
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USERNAME=you@example.com
SMTP_PASSWORD=app-password
EMAIL_FROM=you@example.com
EMAIL_TO=owner@example.com
```

通知失败不会中断扫描。

## Dashboard 安全

如果 Dashboard 可以从外网访问，请设置用户名、密码并使用 HTTPS：

```text
DASHBOARD_USERNAME=operator
DASHBOARD_PASSWORD=一个足够长且唯一的密码
```

这适合由运营人员管理的 Pilot，不是完整的公开多租户 SaaS 登录系统。

## 安全与社区规则

Reddit Lead Finder 不会自动发帖、自动私信、自动投票、创建账号或隐藏品牌关系。
回复前必须：

1. 阅读完整帖子和评论背景。
2. 检查当前 subreddit 规则。
3. 根据真实情况修改草稿。
4. 提及产品时披露关系。
5. 如果品牌参与会显得打扰，就跳过该帖子。

请阅读 Reddit 的 [Spam Policy](https://support.reddithelp.com/hc/en-us/articles/360043504051-Spam)
和 [Responsible Builder Policy](https://support.reddithelp.com/hc/en-us/articles/42728983564564-Responsible-Builder-Policy)。

## 开发

```bash
make install
make test
make check
```

不要提交 `.env`、`data/`、导出文件或 SQLite 数据库。详见 [`SECURITY.md`](SECURITY.md)。

## License

MIT
