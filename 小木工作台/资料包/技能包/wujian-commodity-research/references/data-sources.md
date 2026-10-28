# 数据源路线与权限状态

本表给的是检索与接入路线，不是已接通的数据API。最新值、授权、口径与发布日历须逐指标绑定。官方数据和行业样本各有覆盖局限；无法获得的指标必须留缺口。

|ID|发布者与入口|可查内容|频率|本轮状态|
|---|---|---|---|---|
|SHFE|[上海期货交易所](https://www.shfe.com.cn/)|行情、仓单、库存周报、品种规则|日/周/公告|本轮网页可读|
|INE|[上海国际能源交易中心](https://www.ine.cn/)|保税品种、SCFIS欧线合约、交割规则|日/周/公告|本轮访问受防火墙限制；部分品种可从SHFE进入|
|DCE|[大连商品交易所](https://www.dce.com.cn/)|行情、仓单、品种合约与交割规则|日/公告|本轮网页抓取失败|
|CZCE|[郑州商品交易所](https://www.czce.com.cn/)|行情、仓单、品种合约与交割规则|日/公告|本轮网页抓取失败|
|GFEX|[广州期货交易所](https://www.gfex.com.cn/)|新能源金属及铂钯合约规则|日/公告|本轮首页抓取失败|
|CFFEX|[中国金融期货交易所](https://www.cffex.com.cn/cp/)|股指及国债合约、可交割券与转换因子|日/公告|本轮搜索定位产品页；打开超时|
|NBS|[国家统计局](https://data.stats.gov.cn/)|宏观、工业产量、农作物、投资与消费|月/季/年|本轮搜索定位；逐表待取|
|CUSTOMS|[海关总署](https://online.customs.gov.cn/)|分商品及国别进口出口数量金额|月|本轮搜索定位；查询权限待测|
|MOA|[农业农村部](https://www.moa.gov.cn/)|CASDE、畜牧监测、农产品价格、产能政策|周/月/公告|本轮搜索到CASDE及畜牧原始发布|
|CMA|[中国气象局](https://www.cma.gov.cn/)|实况降水、温度、墒情、农业气象灾害|日/旬/月/事件|本轮搜索到农业气象资料；当期站点待取|
|USDA|[美国农业部](https://www.usda.gov/oce/commodity/wasde/)|WASDE作物年度平衡表；NASS生长进度、面积、单产|周/月/季|本轮搜索定位WASDE和NASS进度|
|EIA|[美国能源信息署](https://www.eia.gov/petroleum/supply/weekly/)|原油成品油库存、产量、进出口、加工与需求代理|周/月|本轮搜索定位原始表；未取当期数值|
|PBOC|[中国人民银行](https://www.pbc.gov.cn/)|政策利率、公开市场操作、社融信贷货币、政策报告|日/月/季/事件|本轮搜索定位政策报告；当期数据待取|
|MOF|[财政部](https://www.mof.gov.cn/)|国债发行拍卖、财政收支与计划|公告/月|官方候选入口，未本轮打开|
|CHINABOND|[中国债券信息网](https://www.chinabond.com.cn/)|收益率曲线、债券估值与托管|日/月|官方候选入口，接口及授权待测|
|CHINAMONEY|[中国货币网](https://www.chinamoney.com.cn/)|银行间资金、回购、Shibor及人民币汇率|日|官方候选入口，接口及授权待测|
|INDEX|[中证指数](https://www.csindex.com.cn/)|指数编制、成分权重、估值与行业结构|日/定期调整|官方候选入口，当期数据待取|
|DISCLOSURE|[交易所公告及巨潮](https://www.cninfo.com.cn/)|成分股财报、生产经营、停产扩产、资本开支|公告/季|官方披露渠道候选，原始文件逐份核验|
|FED|[美联储](https://www.federalreserve.gov/monetarypolicy.htm)|政策决定、声明、预测及沟通|会议/事件|附件提供，运行时重查；不沿用附件利率值|
|TREASURY|[美国财政部](https://home.treasury.gov/resource-center/data-chart-center/interest-rates)|名义及实际收益率曲线|日|附件提供，运行时核验期限列|
|WGC|[世界黄金协会](https://www.gold.org/goldhub)|黄金需求、央行购金估计、ETF数量|月/季|附件提供；估计可修订，全球与单基金分开|
|SAFE|[国家外汇管理局](https://www.safe.gov.cn/)|官方储备资产数量及金额|月|附件提供；不能由金额推断购金数量|
|CFTC|[美国商品期货交易委员会](https://www.cftc.gov/MarketReports/CommitmentsofTraders/index.htm)|分类持仓及统计说明|周|附件提供；持仓日与公布日分开|
|MPOB|[马来西亚棕榈油局](https://bepi.mpob.gov.my/)|棕榈油产量库存出口等|月|行业官方候选，运行时核验|
|SSE_SHIP|[上海航运交易所](https://www.sse.net.cn/)|SCFIS欧线、SCFI及指数编制|按各指数发布日历|行业官方候选；SCFI不替代SCFIS|
|OPEC|[OPEC](https://www.opec.org/)|月报、产量目标与供应政策|月/公告|机构候选，目标不等于实际产量|
|INDUSTRY|授权产业数据与企业调研|SMM、Mysteel、钢联、隆众、卓创及对应行业协会的现货/开工/利润/库存/订单|按具体序列|未开通或验证任何新增付费权限；只使用已有合法授权|
|OVERSEAS|产地官方及海外行业机构|对应产地统计、气象、矿企、炼厂、协会、境外交易所数据|按来源|运行时查明确发布者与精确原文，不虚构API|

## 真实接入必须再建立series binding

每一个复合指标组拆成独立序列，填写series_id、metric_id、发布者、原始表名、合法接口或网页、查询参数、单位、样本、地域、频率、发布日历、时区、修订规则、许可证、最近成功获取时间、备用来源。当前没有填写真实API的地方，不能说“已自动接通”。

行情与规则用交易所或授权行情；产量/进出口用官方统计；高频开工、库存、利润需明确行业样本与授权；企业公告证实个体动作，不能直接外推全行业。气象用对应产地官方实况和预报，并标预报的不确定性。

## 品种源的进一步区分

AU加央行/黄金协会/基金发行人；AG加光伏银耗与工业订单；PT/PD加产地矿山及汽车催化。油脂中P加MPOB与印尼执行量，M/RM加饲料分项。股指加最新成分权重与财报；国债加财政发行、资金、收益率曲线和CTD。EC以SCFIS对应指数与实际舱位为主，不以一般库存代替。
