# Reddit Lead Finder 中文说明

Reddit Lead Finder 是一个开源、自部署、人工审核的 Reddit lead generation 系统。
它根据每个产品的 Campaign 配置发现帖子、过滤市场、评估购买意图、选择回复策略、
生成草稿并发送 Slack 或邮件提醒，但不会自动发布评论。

V0.2.2 增加了托管服务需要的多 Campaign 工作区、审核与批准、负责人分配、结果与
转化金额记录、客户报告、CSV 下载，以及可选的 Dashboard 登录保护。

## 快速开始

```bash
cp .env.example .env
```

在 `.env` 中填写 OpenAI API key，并将 User-Agent 中的邮箱改为自己的：

```text
OPENAI_API_KEY=你的_API_Key
REDDIT_USER_AGENT="reddit-lead-finder/0.2 (contact: 你的邮箱)"
```

然后运行：

```bash
docker compose up --build
```

打开 `http://localhost:8000`。

打开 `http://localhost:8000/campaign` 即可进入前端配置页面，不需要编辑 YAML。首次可直接
配置默认 Campaign；之后可点右上角 `+ New` 新建不同产品或客户的独立工作区。

页面包含六个步骤：

1. Product：产品介绍、价值、客户和限制
2. Market：国家、语言、客户信号和排除市场
3. Discovery：关键词、竞品、核心/相邻/仅观察 subreddit、社区规则和AI建议
4. Qualification：Lead门槛、正向和负向购买信号
5. Engagement：品牌提及、链接、披露语、语气和字数
6. Review & Test：粘贴样本帖子测试评分、策略和草稿

最后可以选择保存 Campaign，或者保存后马上运行第一次扫描。页面保存的内容会写入该
Campaign 自己的 YAML 文件，方便后续复制、版本管理和分享。

## 同时管理多个客户

点击顶部的 `+ New`，输入客户或产品名称，即可建立独立 Campaign。每个 Campaign 都有
自己的配置、Leads、状态、通知和 Report。Dashboard 顶部可以切换 Campaign。同一个 Reddit 帖子可以针对不同产品分别评分，
客户之间的帖子、草稿、状态、负责人和结果不会混在一起。审核流程为：

```text
New -> Approved -> Replied -> Outcome
                  -> Skipped
```

在 `/report` 查看客户报告，在 `/report.csv` 下载当前 Campaign 的完整数据。

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
- 是否允许品牌提及、链接和披露语

项目自带 SaaS、本地服务和开发者工具三个示例。详细配置、评分逻辑、部署方式、
安全要求与贡献方式请阅读英文版 `README.md`。

## 重要原则

Reddit Lead Finder 不自动发布、不自动私信、不伪装成真实客户。任何品牌提及都应披露关系，
用户必须先阅读原帖和社区规则，再决定是否回复。
