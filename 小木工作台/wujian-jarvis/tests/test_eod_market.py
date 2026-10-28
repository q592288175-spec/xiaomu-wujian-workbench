from integrations.eod_market import normalize_continuous, select_actual_main


def test_continuous_rows_are_sorted_deduplicated_and_complete() -> None:
    rows = [
        {'date':'2026-09-25','open':101,'high':104,'low':100,'close':103,'volume':20,'hold':30,'settle':102},
        {'date':'2026-09-24','open':100,'high':102,'low':99,'close':101,'volume':10,'hold':25,'settle':100},
    ]
    result = normalize_continuous(rows)
    assert [row['date'] for row in result] == ['2026-09-24','2026-09-25']
    assert result[-1]['openInterest'] == 30


def bar(day, symbol, volume, open_interest):
    return {'variety':'MA','symbol':symbol,'date':day,'close':3000,'volume':volume,'open_interest':open_interest}


def test_wenhua_rule_switches_only_when_volume_and_open_interest_both_lead() -> None:
    rows = [bar('2026-09-01','MA601',900,900), bar('2026-09-01','MA605',100,100),
            bar('2026-09-02','MA601',500,900), bar('2026-09-02','MA605',800,400)]
    assert select_actual_main(rows,'ma')['symbol'] == 'MA601'   # 第3条：只领先成交量，不切换
    rows += [bar('2026-09-03','MA601',300,500), bar('2026-09-03','MA605',900,950)]
    result = select_actual_main(rows,'ma')
    assert result['symbol'] == 'MA605' and result['stateDate'] == '2026-09-03'   # 第2条：量仓同时最大


def test_wenhua_rule_yields_to_volume_leader_when_main_leads_neither() -> None:
    rows = [bar('2026-09-01','MA601',900,900), bar('2026-09-01','MA605',100,100), bar('2026-09-01','MA609',50,50),
            bar('2026-09-02','MA601',10,100), bar('2026-09-02','MA605',800,400), bar('2026-09-02','MA609',300,600)]
    assert select_actual_main(rows,'ma')['symbol'] == 'MA605'   # 第4条：原主力量仓都不是最大，取成交量最大


def test_wenhua_rule_continues_from_saved_state_and_bootstraps_by_open_interest() -> None:
    rows = [bar('2026-09-01','MA611',900,400), bar('2026-09-01','MA701',500,700),
            bar('2026-09-02','MA611',950,380), bar('2026-09-02','MA701',600,710)]
    assert select_actual_main(rows,'ma')['symbol'] == 'MA701'   # 无历史且从未量仓同时最大：持仓量最大起步
    saved = {'symbol':'MA611','date':'2026-09-01','stateDate':'2026-09-01'}
    assert select_actual_main(rows,'ma',saved)['symbol'] == 'MA611'   # 已有状态：MA611仍领先成交量，维持
