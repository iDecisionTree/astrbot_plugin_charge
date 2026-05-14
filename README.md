# astrbot_plugin_charge

电费查询插件，支持手动查询、账号保存、每日 22:00 自动采集，以及近七天分析图表。

## 依赖

```bash
pip install -r requirements.txt
```

## 命令

```text
/c login <账号> <密码>
/c account list
/c account remove <账号|序号>
/c account clear
/c <房间号>
/c analyze add <房间号>
/c analyze <房间号>
```

## 分析功能说明

- `/c analyze add <房间号>`：添加房间到分析列表。
- 每天晚上 22:00 自动查询一次该房间的剩余电量，并将日期与数据持久化保存。
- `/c analyze <房间号>`：返回一张图表，上半部分是近七天剩余电量折线图，下半部分是近七天每天消耗电量折线图，并附带文字分析。
- 如果房间未添加，会直接提示先执行 `analyze add`。

## 数据存储

- 账号信息：`data/plugin_data/astrbot_plugin_charge/charge_accounts.json`
- 分析数据：`data/plugin_data/astrbot_plugin_charge/charge_analysis.json`
- 分析图表：`data/plugin_data/astrbot_plugin_charge/analysis_<房间号>.png`
