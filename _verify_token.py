import os, tushare as ts
pro = ts.pro_api(os.environ['TUSHARE_TOKEN'])
df = pro.trade_cal(start_date='20260717', end_date='20260718')
print('TOKEN_OK rows=', len(df))
