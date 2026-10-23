"""Opt-in read-only MCP integration check against the running DBHub/Cube stack."""
import argparse
import asyncio
import json
from decimal import Decimal

from langchain_mcp_adapters.client import MultiServerMCPClient


async def check(url):
    client = MultiServerMCPClient({'dbhub': {'transport': 'http', 'url': url}})
    tools = {t.name: t for t in await client.get_tools()}

    async def call(name, **args):
        result = await tools[name].ainvoke(args)
        payload = json.loads(next(item['text'] for item in result if item.get('type') == 'text'))
        if payload.get('success') is not True:
            raise AssertionError(f"{name}: {payload}")
        statements = payload['data']['statements']
        assert not any(s.get('truncated') for s in statements), f'{name} truncated'
        rows = [row for statement in statements for row in statement['rows']]
        print(f'{name}: OK ({len(rows)} rows)')
        return rows

    coverage = await call('get_reporting_coverage')
    sales = next(r for r in coverage if r['dataset'] == 'sales')
    assert sales['first_business_date'] and sales['last_business_date'], 'Seed/build sales data first'
    dates = {'start_date': sales['first_business_date'][:10], 'end_date': sales['last_business_date'][:10]}
    reference = next(r for r in coverage if r['dataset'] == 'inventory_snapshot')['last_business_date']
    assert reference, 'Build inventory mart first'
    reference = reference[:10]
    summary = await call('get_sales_summary', **dates)
    branches = await call('get_branch_performance', **dates)
    channels = await call('get_channel_performance', **dates)
    segments = await call('get_customer_purchase_segments', **dates)
    trend = await call('get_sales_trend', **dates)
    await call('get_product_performance', **dates)
    await call('get_sales_comparison', **dates,
               previous_start_date=dates['start_date'], previous_end_date=dates['end_date'])
    await call('get_inventory_position')
    await call('get_inventory_expiry', reference_date=reference)
    await call('get_production_waste_summary', **dates)
    await call('get_procurement_backlog', reference_date=reference)
    await call('get_procurement_backlog', reference_date=reference, overdue_only=False)
    await call('get_cash_variances', **dates)
    await call('get_cash_variances', **dates, tolerance=1000.0)

    for metric in ('order_count', 'receipt_revenue', 'net_revenue_after_refund'):
        for row in summary:
            for report in (branches, channels, segments):
                actual = sum(Decimal(str(r[metric])) for r in report if r['currency_code'] == row['currency_code'])
                assert abs(actual - Decimal(str(row[metric]))) < Decimal('0.01'), (metric, actual, row)
        if len(summary) == 1:
            actual = sum(Decimal(str(r[metric])) for r in trend)
            assert abs(actual - Decimal(str(summary[0][metric]))) < Decimal('0.01'), (metric, actual)

    branch = branches[0]['branch_code']
    scoped = await call('get_sales_summary', **dates, branch_code=branch)
    assert scoped, 'Known branch filter unexpectedly empty'
    for name in ('get_sales_summary', 'get_sales_trend', 'get_channel_performance',
                 'get_product_performance', 'get_customer_purchase_segments',
                 'get_production_waste_summary', 'get_cash_variances'):
        assert await call(name, **dates, branch_code="__missing__' OR 1=1 --") == [], name
    assert await call('get_inventory_position', branch_code='__missing__') == []
    assert await call('get_sales_summary', start_date='1900-01-01', end_date='1900-01-01') == []
    # A one-day inclusive range must not accidentally include the following day.
    day = dates['start_date']
    one_day = await call('get_sales_summary', start_date=day, end_date=day)
    if len(summary) == 1:
        expected = next(r['receipt_revenue'] for r in trend if r['business_date'][:10] == day)
        assert abs(Decimal(str(one_day[0]['receipt_revenue'])) - Decimal(str(expected))) < Decimal('0.01')
    print('PASS: 13 reporting tools, defaults, filters, date boundary and cross-report totals')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://localhost:8086/mcp')
    asyncio.run(check(parser.parse_args().url))
