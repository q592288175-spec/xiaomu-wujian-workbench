# 多账户与余额同步验收

执行：Windows / OpenAI Codex，2026-10-12（北京时间）。

## 修改文件清单

| 文件 | 变化 |
| --- | --- |
| integrations/account-balances.mjs（新增） | 独立手动余额序列、基线、修正作废重算、审计、累计盈亏 |
| integrations/five-workbench.mjs | 增量迁移、独立初始资金、唯一名称、修订校验、账户停用与安全删除、卡绑定、统一接口及账户汇总 |
| integrations/trade-ledger.mjs | 手动对账不再重复写交易盈亏流水，避免重启生成重复基线；原平仓记账口径保留 |
| integrations/operation-archive.mjs | 账户摘要和独立余额CSV，JSON保留全部审计 |
| server.mjs | 账户余额、历史修正、作废、删除接口，账户归属及PATCH来源校验，服务指纹 |
| desktop/main.cjs | 服务指纹包含新增余额模块；已重建Windows APP |
| dist/account-ui.js、dist/account-ui.css（新增） | 两版共用账户弹窗、资金概况、历史筛选和安全确认 |
| dist/workbench.js、dist/workbench.css、dist/index.html | 稳定版顶部、金、木、账户管理联动，余额只读测算、保留未提交价位；切户清理CSV预览，防旧请求覆盖新账户 |
| dist/cockpit-workbench.js、dist/cockpit.html、dist/cockpit.css | 全息版账户功能和顶部资金条，响应式布局 |
| tests/account-balance.test.mjs（新增） | 8项余额/账户场景测试，覆盖多项分支断言 |
| tests/simple-account.test.mjs | 零余额可登记，负余额拒绝；风险测算的原许可不放宽 |
| tests/trade-records.test.mjs、tests/team-governance.test.mjs | 隔离测试使用唯一账户名，不绕过生产名称限制 |
| scripts/checkpoint-accounts.mjs（新增） | SQLite一致性备份及配套代码 |
| scripts/verify-account-balances.mjs（新增） | 真实服务与Windows APP隔离流程验收 |
| scripts/verify-account-preservation.mjs（新增） | 正式库原记录逐字段对照 |
| scripts/verify-account-formal-desktop.mjs（新增） | 正式APP只读切户验收，不改金额 |

另新增本说明和使用说明；更新十月决定记录及全局文件索引。已有其他未提交修改均保留，未提交Git或推送。

## 实际结果

- Node：76项聚焦测试全部通过。覆盖账户与余额、风险测算、冻结计划、团队边界、真实交易盈亏、火展示及原共振规则。
- Python：pytest执行tests/test_eod_market.py和tests/fire_scan_test.py，14项全部通过。未修改Python行情或筛选源码。
- npm run check通过；新增模块通过实际Node/浏览器加载。Node日志见output/account-balances/node-tests.txt，Python日志见python-tests.txt，语法日志见syntax-check.txt。
- Windows APP完成重建。真实服务接口+隔离SQLite+重建APP的实际点击通过：添加两个指定名称账户、顶部切换、金110万→111万、木111万→108万、金回看108万、错误余额金额修正/作废/备注编辑、关闭和重启、默认保护、有交易卡只停用。
- 同步不丢金表单中尚未提交的入场价。两浏览器窗口的稳定版/全息版同步账户选择与资金；稳定版1500、1100、390宽无整页横向溢出，历史表允许内部滚动。
- 页面错误收集为空。全息版弹窗受到旧footer样式影响的问题已修复，按钮可实际点击；顶部按钮不再竖排。账户资金条未覆盖现有五行流程。
- 正式APP只读验收：原4账户逐个切换、木页展示通过，切换前后账户数据完全一致；没有提交正式测试业务。
- 正式库与一致性备份逐字段核对：4账户、11卡、2计划版本、0执行、0复盘、3资金流水、26操作记录均保留；已有账户金额和业务字段未变。仅新增数据字段及默认保护标记，未绑定账户的旧卡为0。SQLite完整性检查ok。

## 证据位置

全部位于项目 output/account-balances：

- acceptance.json：隔离桌面流程和测试库路径。
- formal-desktop.json：正式桌面只读验收。
- preservation.json：原有业务保存核验及初始资金缺口。
- wood-1500.png、wood-1100.png、wood-mobile.png、cockpit.png：隔离页面截图。
- formal-wood.png：正式账户页面，仅本机保存，不可放入分享包。
- server.log：隔离服务运行日志。

测试中的账户金额属于测试夹具，不代表真实实盘账户余额。最早一次Python误用unittest发现零项测试，未计为通过；已改用pytest实际执行14项。早期失败截图/日志保留以便排查，以最终acceptance.json为最终结果。

## 数据与交易边界

余额修正和作废保留后续真实盈亏，不重复计入平仓金额。交易草稿、复盘文字和历史导入的原行为未改。余额变化按既有规则使相关旧批准失效，计划和历史版本不物理删除。未新增券商连接、自动下单或模型付费调用。

未修改资料包、正式规则数值、火筛选程序、主力切换或研究结论；没有解除运行锁。

## 待人工确认与验收边界

1. 三个旧实盘账户的独立初始资金缺失，须本人在账户与规则里填写；现有实际余额保留。
2. 正式库有仍在运行的旧轮次，检测到锁定源码版本差异。未自动结束或覆盖快照；新增风险继续依原机制拦截。请本人核对旧轮次后按原流程处理。
3. 本次是本地手动账本验收，不是期货公司实盘资金对账或真实交易授权。
4. 未重打包对外分享版。所有测试库、正式截图、操作导出均含本机资料，不能直接分享。

恢复点与操作步骤见 account-balance-management-2026-10-12.md；当前可用版本检查点为 .runtime/checkpoints/accounts-2026-10-11T23-30-03-676Z。
