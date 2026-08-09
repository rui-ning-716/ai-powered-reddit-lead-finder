# Reddit Lead Finder 中文说明

Reddit Lead Finder 是一个开源、自部署、人工审核的 Reddit 获客系统。
它根据每个产品的 Product Setup 发现帖子、过滤市场、评估购买意图、选择回复策略、
生成草稿并发送 Slack 或邮件提醒，但不会自动发布评论。

V0.5.0 增加了网址生成完整配置的流程。第一次打开时不再预载 AI Meeting Notes、
English 或任何示例。输入产品公开网址后，AI 会生成 Product、Market、Discovery、
Qualification、Engagement、Review & Test 六个部分，用户只需逐项审核和修改。

网址读取会阻止本地和私有网络地址，检查重定向，并限制超时、页面大小和读取页数。
AI 生成的 subreddit 只是候选社区，不代表已经确认允许品牌推广，发布前仍需人工核对规则。

## 快速开始

```bash
cp .env.example .env
```

在 `.env` 中填写 OpenAI API key，并将 User-Agent 中的邮箱改为自己的：

```text
OPENAI_API_KEY=你的_API_Key
REDDIT_USER_AGENT="reddit-lead-finder/0.5 (contact: 你的邮箱)"
```

然后运行：

```bash
docker compose up --build
```

打开 `http://localhost:8000`。

打开 `http://localhost:8000`。第一次使用时输入产品公开网址，点击生成 Product Setup。
检查 AI 填写的六个部分后再保存。之后可点右上角 `+ Add product` 新建不同产品或客户的独立工作区。

页面包含六个步骤：

1. Product：产品介绍、价值、客户和限制
2. Market：国家、语言、客户信号和排除市场
3. Discovery：关键词、竞品、核心/相邻/仅观察 subreddit、社区规则和AI建议
4. Qualification：Opportunity 门槛、正向和负向购买信号，以及 AI 自适应评分
5. Engagement：品牌提及、链接、披露语、语气和字数
6. Review & Test：粘贴样本帖子测试评分、策略和草稿

最后可以选择保存 Product Setup，或者保存后马上搜索 Reply Opportunities。页面保存的内容会写入该
产品自己的 YAML 文件，方便后续复制、版本管理和分享。

Reddit RSS 搜索是关键词匹配，不是语义搜索。搜索词不需要与整条标题完全一致，但 Reddit
会先根据词语和短语召回候选帖子，双引号会让多词短语更精确。AI 只会在帖子被召回后再判断
语义和购买意图，因此同一个需求最好准备多种用户可能使用的表达方式。

## 同时管理多个客户

点击顶部的 `+ Add product` 即可建立独立产品工作区。每个产品都有
自己的配置、Reply Opportunities、状态、通知和 Performance。页面顶部可以切换产品。同一个 Reddit 帖子可以针对不同产品分别评分，
客户之间的帖子、草稿、状态、负责人和结果不会混在一起。审核流程为：

```text
New -> Approved -> Replied -> Outcome
                  -> Skipped
```

在 `/report` 查看 Performance，在 `/report.csv` 下载当前产品的完整数据。

如果你从早期版本升级且历史 Leads 混在一起，先新建目标 Campaign，再在 Lead 卡片底部用
`Move to campaign` 将每条历史 Lead 移过去。移动后对应的统计和报告也会一起归属到新 Campaign。

如果 Dashboard 会被其他人通过网络访问，请同时配置：

```text
DASHBOARD_USERNAME=operator
DASHBOARD_PASSWORD=一个足够长且唯一的密码
```

并使用 HTTPS。更完整的托管服务操作说明见 `docs/MANAGED_SERVICE.md`。

## 可配置内容

- 产品名称、介绍、价值、限制和目标客户
- 国家、语言、市场信号和排除词
- Reddit关键词、subreddit和搜索时间范围
- 正向与负向购买信号
- Lead score门槛
- Relevance、购买意图、产品匹配度、紧迫度和可回复性的相对权重
- 推广风险和市场不匹配的扣分，以及每个评分维度下的细分判断信号
- 是否允许品牌提及、链接和披露语

项目自带 SaaS、本地服务和开发者工具三个示例。详细配置、评分逻辑、部署方式、
安全要求与贡献方式请阅读英文版 `README.md`。

## 重要原则

Reddit Lead Finder 不自动发布、不自动私信、不伪装成真实客户。任何品牌提及都应披露关系，
用户必须先阅读原帖和社区规则，再决定是否回复。
