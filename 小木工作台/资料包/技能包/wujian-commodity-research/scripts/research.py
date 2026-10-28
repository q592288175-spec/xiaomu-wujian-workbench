#!/usr/bin/env python3
"""Portable stdlib-only research preparation and evidence contract checks."""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))

def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2)

def records():
    return read(ROOT/'data/products.json')

def timestamp(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('时间必须含时区')
    return dt

def resolve(query):
    q = query.strip().upper()
    exchange = None
    if '.' in q:
        exchange, q = q.split('.', 1)
    if re.fullmatch(r'(L|V|PP)\d{4}F', q) or '月均价' in q:
        raise ValueError('月均价特殊合约：先核官方结算标的、观察窗口与规则，不能套普通合约')
    q = re.sub(r'(?<=[A-Z])\d{3,4}$', '', q)
    matches = [p for p in records() if q in [p['symbol'], p['name'].upper(),
        *[s.upper() for s in p['aliases'].split(',') if s]] and
        (exchange is None or exchange == p['exchange'])]
    if len(matches) != 1:
        raise ValueError('品种不明确或不在已建底库；请确认名称、交易所和代码，不猜测匹配')
    return matches[0]

def prepare(query, news=None, baseline=None, as_of=None, mode=None):
    p = resolve(query)
    iid = p['exchange']+'.'+p['symbol']
    as_of = as_of or datetime.now(timezone.utc).isoformat()
    timestamp(as_of)
    has_news = bool(isinstance(news, str) and news.strip())
    if mode == 'framework' and has_news:
        raise ValueError('框架查看模式不能同时要求新闻评估')
    if mode == 'event_impact' and not has_news:
        raise ValueError('事件模式缺少消息原文')
    if mode == 'full_research' and has_news:
        raise ValueError('新闻输入与全景模式冲突；请省略mode或用event_impact')
    if baseline:
        if baseline.get('instrument') != iid:
            raise ValueError('基准报告品种不匹配')
        if timestamp(baseline['as_of']) > timestamp(as_of):
            raise ValueError('基准报告晚于研究截止')
    mode = mode or ('event_impact' if has_news else 'full_research')
    return dict(schema_version='3.0', mode=mode, instrument=iid,
        requested_instrument=query, as_of=as_of, framework=p,
        profile=str(ROOT/'references/profiles'/f"{p['symbol']}.md"),
        model=str(ROOT/'references/models'/f"{p['model']}.md"),
        runtime=str(ROOT/'references/runtime.md'),
        event_protocol=str(ROOT/'references/event.md') if has_news else None,
        source_registry=str(ROOT/'data/sources.json'), news=news if has_news else None,
        baseline=baseline, baseline_status='requires_review' if baseline else 'missing',
        must_establish_baseline=has_news and not baseline,
        analysis_status='not_run', trade_permission=False)

def scaffold(ctx):
    p=ctx['framework']
    report=dict(schema_version='3.0', framework_version='3.0',
        report_id=ctx['instrument']+'-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'),
        mode=ctx['mode'], instrument=ctx['instrument'], as_of=ctx['as_of'],
        status='insufficient_evidence', sources=[], facts=[], hypotheses=[], scenarios=[],
        coverage=[dict(metric_id=m['id'],status='missing',evidence_ids=[],gap=m['question']) for m in p['metrics']],
        brief=dict(where='未取行情',pressures=[],supports=[],watch=[],main_conflict='待研究',largest_unknown='尚未取证'),
        watch_rules=[], changes=dict(previous_report_id=None,action='new',before=None,after=None,reason='尚未研究'),
        trade_permission=False)
    if ctx['mode']=='event_impact':
        report['event']=dict(raw_input=ctx['news'],first_published_at=None,novelty='unknown',
            baseline_report_id=(ctx['baseline'] or {}).get('report_id'),baseline_adequacy='missing',
            impact_class='insufficient_evidence',channels=[],priced_in='未知',price_effect={},response={})
    return report

def audit(report):
    errors=[]; gaps=[]
    def check(ok,msg):
        if not ok: errors.append(msg)
    def fields(obj,keys,label):
        if not isinstance(obj,dict):
            errors.append(label+'必须为对象'); return False
        for k in keys:
            check(k in obj,label+'缺'+k)
        return all(k in obj for k in keys)
    def when(v,label):
        try: return timestamp(v)
        except (ValueError,TypeError,AttributeError): errors.append(label+'不是带时区时间'); return None
    fields(report,['schema_version','framework_version','report_id','instrument','as_of','mode','status','sources','facts','coverage','hypotheses','scenarios','brief','watch_rules','changes','trade_permission'],'报告')
    check(report.get('schema_version')=='3.0','schema版本不是3.0')
    check(report.get('framework_version')=='3.0','框架版本不兼容')
    check(report.get('trade_permission') is False,'研究不授予交易许可')
    check(report.get('mode') in ('full_research','event_impact'),'报告模式错误')
    check(report.get('status') in ('conditional','insufficient_evidence','reviewed','simulation'),'报告状态错误')
    cutoff=when(report.get('as_of'),'as_of')
    try:
        p=resolve(report.get('instrument',''))
        check(report['instrument']==p['exchange']+'.'+p['symbol'],'报告需标准品种ID')
        metric_ids={m['id'] for m in p['metrics']}
    except (ValueError,AttributeError):
        metric_ids=set();errors.append('报告品种未知')
    for key in ('sources','facts','coverage','hypotheses','scenarios','watch_rules'):
        if not isinstance(report.get(key),list): errors.append(key+'必须为数组')
    if errors: return dict(structure_ok=False,errors=errors,gaps=gaps,complete=False)
    source_ids=set();fact_ids=set()
    sources={}
    for s in report['sources']:
        if not fields(s,['id','publisher','url','origin_group','access_status'],'来源'): continue
        check(bool(s['id']) and s['id'] not in source_ids,'来源ID重复或空')
        source_ids.add(s['id']);sources[s['id']]=s
        check(bool(s['publisher']) and bool(s['origin_group']),'来源机构和同源组不可空')
    for f in report['facts']:
        if not fields(f,['id','metric_id','statement','value','unit','observation_start','observation_end','published_at','retrieved_at','status','source_ids','locator','definition','revision'],'事实'): continue
        check(f['id'] not in fact_ids and bool(f['id']),'事实ID重复或空');fact_ids.add(f['id'])
        check(f['metric_id'] in metric_ids,'事实指标不属于本品种')
        check(f['status'] in ('verified','estimated','calculated','quoted','disputed','unavailable','simulation'),'事实状态错误')
        check(isinstance(f['source_ids'],list),'source_ids必须是数组')
        check(all(s in source_ids for s in f['source_ids']),'事实引用不存在的来源')
        pub=when(f['published_at'],'published_at') if f['published_at'] else None
        ret=when(f['retrieved_at'],'retrieved_at') if f['retrieved_at'] else None
        check(not(pub and cutoff and pub>cutoff),'未来公开/修订数据泄漏')
        check(not(pub and ret and pub>ret),'获取时间早于公开时间')
        check(not(ret and ret>datetime.now(timezone.utc)),'获取时间在未来')
        if f['status']=='unavailable': check(f['value'] is None,'缺失值必须null，不可填0')
        if f['status']=='verified':
            check(bool(f['source_ids']) and bool(pub) and bool(ret) and bool(f['locator']) and bool(f['definition']) and bool(f['unit']),'verified缺少可追溯字段')
            check(all(sources[s].get('access_status')=='read_original' and bool(sources[s].get('url')) for s in f['source_ids'] if s in sources),'verified不能仅引用入口或未读来源')
        if f['status']=='simulation': check(report['status']=='simulation','模拟证据不得进入真实研究')
        if f['status']=='calculated':
            check(bool(f.get('formula')) and bool(f.get('input_fact_ids')),'计算值缺公式/输入证据')
        if f['observation_start'] and f['observation_end']:
            try:
                begin=datetime.fromisoformat(f['observation_start']).date();end=datetime.fromisoformat(f['observation_end']).date()
                check(begin<=end,'观察起止顺序错误')
                # Forecast horizons may exceed cutoff only if explicitly labelled as forecasts.
                check(not(cutoff and end>cutoff.date() and f.get('value_kind')!='forecast'),'未来观察期须明确为forecast')
            except ValueError: errors.append('观察期日期无效')
    facts={f['id']:f for f in report['facts'] if isinstance(f,dict) and 'id' in f}
    seen=set()
    for c in report['coverage']:
        if not fields(c,['metric_id','status','evidence_ids','gap'],'覆盖'): continue
        check(c['metric_id'] in metric_ids and c['metric_id'] not in seen,'覆盖指标未知或重复');seen.add(c['metric_id'])
        check(c['status'] in ('covered','partial','missing'),'覆盖状态错误')
        check(all(f in fact_ids for f in c['evidence_ids']),'覆盖引用不存在的事实')
        check(all(facts[f].get('metric_id')==c['metric_id'] for f in c['evidence_ids'] if f in facts),'跨指标冒充覆盖')
        if c['status']=='covered':
            check(bool(c['evidence_ids']) and all(facts[f].get('status') in ('verified','estimated','calculated') for f in c['evidence_ids'] if f in facts),'covered没有有效证据')
            check(bool(c.get('freshness_review')),'covered缺发布日历/口径新鲜度复核')
        else: gaps.append(c['metric_id']+': '+str(c['gap']))
    check(seen==metric_ids,'没有逐项覆盖全部必查指标')
    check(len(report['hypotheses'])>=3,'不足三种竞争解释')
    for h in report['hypotheses']:
        if not fields(h,['id','claim','mechanism','horizon','supporting_facts','contradicting_facts','confidence','falsifier'],'假说'): continue
        check(h['confidence'] in ('low','medium','high'),'置信度错误')
        check(all(f in fact_ids for f in h['supporting_facts']+h['contradicting_facts']),'假说引用不存在的事实')
        fields(h['falsifier'],['metric','condition','window','basis','action'],'反证')
        check(all(h['falsifier'].get(k) for k in ('metric','condition','window','basis','action')),'反证字段不可空')
    for f in facts.values():
        if f.get('status')=='calculated': check(all(k in fact_ids and k!=f['id'] for k in f.get('input_fact_ids',[])),'计算输入引用错误')
    fields(report['brief'],['where','pressures','supports','watch','main_conflict','largest_unknown'],'四问卡')
    fields(report['changes'],['previous_report_id','action','before','after','reason'],'版本变化')
    check(bool(report['watch_rules']),'缺下一检查点')
    check({s.get('type') for s in report['scenarios'] if isinstance(s,dict)}=={'base','supportive','adverse'},'需基准/支撑/压制三情景')
    for s in report['scenarios']:
        fields(s,['type','conditions','price_effect','invalidation'],'情景')
    if report['mode']=='event_impact':
        e=report.get('event',{})
        if fields(e,['raw_input','first_published_at','novelty','baseline_report_id','baseline_adequacy','impact_class','channels','priced_in','price_effect','response'],'事件'):
            check(e['novelty'] in ('new','realization','revision','duplicate','opinion','unknown'),'新颖度错误')
            check(e['impact_class'] in ('short_term','seasonal_cyclical','structural','mixed','insufficient_evidence'),'影响分类错误')
            check(e['baseline_adequacy'] in ('adequate','partial','missing'),'基准状态错误')
            if e['first_published_at']:
                ep=when(e['first_published_at'],'事件公开时间')
                check(not(ep and cutoff and ep>cutoff),'事件晚于截止')
            check(bool(e['channels']),'事件缺传导路径')
            for c in e['channels']:
                if fields(c,['variable','mechanism','scale','onset_lag','duration','reversibility','buffers','evidence_ids','falsifier'],'传导'):
                    check(all(f in fact_ids for f in c['evidence_ids']),'事件证据引用错误')
            fields(e['price_effect'],['immediate','persistent','spot_near_far','confidence','conditions'],'价格影响')
            fields(e['response'],['research_action','flat_account','existing_position','next_check','invalidation_action'],'应对')
            if e['baseline_adequacy']!='adequate': gaps.append('事件基准不完整')
            if e['baseline_adequacy']=='adequate': check(bool(e['baseline_report_id']),'完整基准缺报告ID')
            if e['novelty']=='unknown': check(e['price_effect'].get('confidence')=='low','未经核验消息必须低置信')
    if gaps: check(report['status']!='reviewed','关键缺口存在，不得标reviewed')
    if report['status']=='reviewed': check(bool(report.get('review_notes')),'reviewed需真实人工/模型复核记录')
    return dict(structure_ok=not errors, errors=errors, gaps=gaps,
        complete=not errors and not gaps, audit_scope='字段、引用、日期与缺口检查；不证明事实真实性或投资有效性')

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    sub=ap.add_subparsers(dest='command',required=True)
    sub.add_parser('list')
    a=sub.add_parser('audit');a.add_argument('report')
    for command in ('prepare','start'):
        a=sub.add_parser(command);a.add_argument('instrument')
        a.add_argument('--mode',choices=['framework','full_research','event_impact'])
        a.add_argument('--news-file');a.add_argument('--baseline-file');a.add_argument('--as-of')
        if command=='start':a.add_argument('--output',required=True)
    a=ap.parse_args()
    try:
        if a.command=='list': result=[{k:p[k] for k in ('symbol','exchange','name','sector','model')} for p in records()]
        elif a.command=='audit':
            result=audit(read(a.report));print(dump(result))
            return 0 if result['complete'] else 2
        else:
            news=Path(a.news_file).read_text(encoding='utf-8') if a.news_file else None
            baseline=read(a.baseline_file) if a.baseline_file else None
            result=prepare(a.instrument,news,baseline,a.as_of,a.mode)
            if a.command=='start':
                if result['mode']=='framework':raise ValueError('framework只查看，不建立报告')
                out=Path(a.output).resolve()
                out.mkdir(parents=True,exist_ok=False)
                (out/'context.json').write_text(dump(result)+'\n',encoding='utf-8')
                (out/'report.json').write_text(dump(scaffold(result))+'\n',encoding='utf-8')
                (out/'task.md').write_text('# 研究任务\n\n状态：尚未研究。\n\n读取context.json中的profile、model、runtime，事件模式再读event_protocol。逐指标取证后填写report.json并执行audit；缺口保留未知。最终另写report.md。\n',encoding='utf-8')
                result={'directory':str(out),'instrument':result['instrument'],'mode':result['mode'],'analysis_status':'not_run'}
        print(dump(result));return 0
    except (OSError,ValueError,KeyError,TypeError,AttributeError) as exc:
        print(str(exc),file=sys.stderr);return 2

if __name__=='__main__':sys.exit(main())
