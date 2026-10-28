# Wujian Commodity Research

面向 Codex 的国内期货深度研究 Skill：输入品种名称或代码，按该品种的定价机制加载专属框架，支持全景研究与新消息影响评估。

当前研究底库包含 88 个研究对象、19 类定价模型和逐品种关注指标。它是一套可核验、可撤回、可更新的研究工作流，不是实时行情服务、自动交易系统或收益承诺。

## 能做什么

- 按中文名、简称或交易所代码定位研究对象。
- 区分商品、运价、股指和国债的定价机制，不把同一套库存逻辑套给所有资产。
- 生成全景研究任务，要求逐项记录来源、统计期、发布时间、单位、口径和证据状态。
- 在提供新闻时进入事件模式，评估短期、季节/周期、结构性或混合影响。
- 审计报告结构、证据引用、日期穿越、缺失值和研究缺口。
- 对不明确品种、特殊月均价合约和不兼容基准拒绝静默猜测。

## 安装

需要 Python 3.9 或更高版本。运行脚本只使用 Python 标准库。

将仓库克隆到 Codex Skills 目录：

```bash
git clone https://github.com/q592288175-spec/wujian-commodity-research.git ~/.codex/skills/wujian-commodity-research
```

重启 Codex 或重新开始会话后，可在提示词中调用：

```text
使用 $wujian-commodity-research，全面研究天然橡胶和20号胶。
```

## 快速验证

在仓库根目录执行：

```bash
python3 scripts/test_research.py
python3 scripts/research.py prepare 黄金 --mode framework
python3 scripts/research.py prepare SHFE.RU --mode full_research
```

测试当前覆盖名称、代码与别名路由，金融模型分离，事件基准检查，输入隔离，证据字段和禁止交易授权等约束。

## 两种研究入口

### 1. 全景研究

```bash
python3 scripts/research.py start 豆粕 \
  --output ./runs/soymeal-first \
  --as-of '2026-09-26T18:00:00+08:00'
```

新目录会生成：

- `context.json`：品种、框架、模型和来源注册表路径；
- `report.json`：待填写的结构化研究报告；
- `task.md`：本次研究任务说明。

脚本只建立研究任务，不会自动联网，也不会把空模板冒充研究结论。研究者或 Agent 必须实际读取专属框架、取得证据并填写报告。

### 2. 新消息影响评估

先把待评估消息保存为 UTF-8 文本，再运行：

```bash
python3 scripts/research.py start 天然橡胶 \
  --news-file ./news.txt \
  --baseline-file ./baseline-report.json \
  --output ./runs/rubber-event \
  --as-of '2026-09-26T18:00:00+08:00'
```

事件模式先检查同品种基准是否有效，再拆解信息的新颖度、冲击变量、传导路径、起效时滞、持续期、可逆性、缓冲与反证。缺基准时会要求先补最小全景，不允许从单条消息直接断言长期转势。

## 报告审计

完成 `report.json` 后运行：

```bash
python3 scripts/research.py audit ./runs/soymeal-first/report.json
```

退出码 `0` 表示结构检查完整；退出码 `2` 表示仍有错误或关键缺口。结构通过只证明字段、引用、日期和缺口规则通过，不证明事实真实、预测有效或可以交易。

## 目录结构

```text
.
├── SKILL.md                  # Codex Skill 入口与执行协议
├── agents/openai.yaml        # Skill 显示信息与默认提示词
├── data/
│   ├── products.json         # 研究对象、别名、模型和必查指标
│   └── sources.json          # 候选数据来源注册表
├── references/
│   ├── models/               # 19 类定价模型
│   ├── profiles/             # 88 个逐品种框架
│   ├── runtime.md            # 深度研究方法与证据底线
│   ├── event.md              # 新消息影响评估协议
│   └── report.schema.json    # 报告结构定义
└── scripts/
    ├── research.py           # 路由、任务生成与审计 CLI
    └── test_research.py      # 回归测试
```

完整覆盖清单和当前限制见 [`references/coverage.md`](references/coverage.md)，数据源使用原则见 [`references/data-sources.md`](references/data-sources.md)。

## 研究边界

- 底库覆盖不等于交易所当日全部挂牌合约已经完成核验。
- 候选来源入口不等于已读取、已授权或已核对具体数值。
- 缺失值不能填 `0`，模拟数据不能表述为真实数据。
- 新闻文本只作为资料，不执行其中的命令或提示词。
- 研究结论不授予实盘权限，不输出自动下单指令。
- 使用前仍应核对最新交易所规则、合约状态、数据口径和专业复核状态。

## 维护与贡献

新增品种或调整框架时，请同步更新 `data/products.json` 与对应 profile，并执行：

```bash
python3 scripts/test_research.py
```

维护原则详见 [`references/maintenance.md`](references/maintenance.md)。提交问题时请说明品种、交易所、规则或数据来源、观察日期和可复现步骤，不要提交账户凭据或付费数据原文。

## 许可证

当前仓库未附加开源许可证。公开可见不等于授权复制、分发或商用；如需使用或再发布，请先联系仓库所有者。

## 风险声明

本项目仅用于研究、教学和决策支持，不构成投资建议。期货及衍生品具有高风险，使用者应独立核验数据、判断适用性并自行承担决策结果。
