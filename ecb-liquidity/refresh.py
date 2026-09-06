"""Official ECB liquidity collector; Python 3.10+, no external dependencies.
Preserves all published dates. Dashboard analytics default to weekdays.
"""
from __future__ import annotations
import argparse, csv, hashlib, io, json, math, os, tempfile, time, zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.request import Request, urlopen
ROOT=Path(__file__).resolve().parent
ARCHIVE='https://www.ecb.europa.eu/stats/pdf/monetary/lm/'
API='https://data-api.ecb.europa.eu/service/data/ILM/D.U2.C.EXLIQ+L020100+L020200+MRR+A050500.U2.EUR?startPeriod=2024-09-27&format=csvdata'
FIELDS={'Current accounts':'current_accounts','Deposit facility':'deposit_facility','Reserve requirements':'reserve_requirements','Marginal lending facility':'marginal_lending','Excess liquidity':'reported'}
KEYS={'EXLIQ':'reported','L020100':'current_accounts','L020200':'deposit_facility','MRR':'reserve_requirements','A050500':'marginal_lending'}
COMP=('current_accounts','deposit_facility','reserve_requirements','marginal_lending')
def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')
def numeric(v):
    if v is None or str(v).strip() in ('','-','.',':'): return None
    n=float(v)
    if not math.isfinite(n) or abs(n)>25000000: raise ValueError('Invalid value or unexpected units')
    return n
def read_archive(body,source):
    result={}
    with zipfile.ZipFile(io.BytesIO(body)) as z:
        if sum(i.file_size for i in z.infolist())>40000000: raise ValueError('Archive expansion limit')
        for i in z.infolist():
            if not i.filename.lower().endswith('.csv'): continue
            rows=list(csv.reader(io.StringIO(z.read(i).decode('utf-8-sig'))))
            header=next((n for n,r in enumerate(rows) if 'Reference date' in r and 'Excess liquidity' in r),None)
            if header is None: raise ValueError('ECB archive schema changed')
            labels=rows[header]
            for row in rows[header+1:]:
                if not row or not row[0].strip(): continue
                cells=dict(zip(labels,row)); day=None
                for fmt in ('%d/%m/%y','%d/%m/%Y','%Y-%m-%d'):
                    try: day=datetime.strptime(cells['Reference date'],fmt).date().isoformat(); break
                    except ValueError: pass
                if day is None: raise ValueError('Unrecognized archive date')
                rec={'date':day,'source':source}
                for label,k in FIELDS.items():
                    value=numeric(cells.get(label))
                    if value is not None:
                        if k!='reported' and value<0: raise ValueError('Negative liquidity component')
                        rec[k]=value
                result[day]=rec
    if not result: raise ValueError('Archive contains no recognized records')
    return result
def read_api(body,source):
    reader=csv.DictReader(io.StringIO(body.decode('utf-8-sig')))
    if not {'TIME_PERIOD','OBS_VALUE','BS_ITEM','UNIT_MULT'}.issubset(reader.fieldnames or []): raise ValueError('ECB API schema changed')
    result={}
    for row in reader:
        if row.get('UNIT_MULT')!='6' or row.get('CURRENCY_TRANS')!='EUR': raise ValueError('Expected EUR millions')
        key=KEYS.get(row['BS_ITEM'])
        if not key: continue
        day=date.fromisoformat(row['TIME_PERIOD']).isoformat(); value=numeric(row['OBS_VALUE'])
        if value is None: continue
        if key!='reported' and value<0: raise ValueError('Negative API component')
        rec=result.setdefault(day,{'date':day,'source':source}); rec[key]=value
        rec.setdefault('observation_status',{})[key]=row.get('OBS_STATUS')
    if not result: raise ValueError('API contains no observations')
    return result
def fetch(url):
    for attempt in range(3):
        try:
            with urlopen(Request(url,headers={'User-Agent':'LOIS-ECB-Liquidity/2.0','Accept':'*/*'}),timeout=25) as r:
                body=r.read(12000001)
                if len(body)>12000000: raise ValueError('Response exceeds limit')
                return body,{'url':url,'retrieved_at':stamp(),'last_modified':r.headers.get('Last-Modified'),'sha256':hashlib.sha256(body).hexdigest()}
        except Exception:
            if attempt==2: raise
            time.sleep(2**attempt)
def atomic(path,text):
    path.parent.mkdir(parents=True,exist_ok=True); fd,tmp=tempfile.mkstemp(dir=path.parent,prefix=path.name+'.')
    try:
        with os.fdopen(fd,'w',encoding='utf-8') as f: f.write(text)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)
def collect(source_dir=None):
    out=ROOT/'data'; out.mkdir(exist_ok=True); path=out/'liquidity.json'
    old=json.loads(path.read_text()) if path.exists() else {}
    raw={r['date']:dict(r) for r in old.get('records',[])}
    sources={r['url']:r for r in old.get('sources',[])}
    state=dict(old.get('archive_state',{})); warnings=[]; fresh=0; today=datetime.now(timezone.utc).date()
    jobs=[(str(y),ARCHIVE+f'liq_daily_{y}.zip') for y in range(2021,today.year+1)]+[('api',API)]
    manifest={r['name']:r for r in json.loads((source_dir/'manifest.json').read_text())} if source_dir else {}
    def retrieve(job):
        name,url=job
        if source_dir:
            filename='ilm_recent.csv' if name=='api' else f'liq_daily_{name}.zip'
            body=(source_dir/filename).read_bytes(); orig=manifest[filename]
            if hashlib.sha256(body).hexdigest()!=orig['sha256']: raise ValueError('Source hash mismatch')
            meta={k:orig.get(k) for k in ('url','retrieved_at','last_modified','sha256')}
        else: body,meta=fetch(url)
        values=read_api(body,url) if name=='api' else read_archive(body,url)
        if name!='api' and any(not d.startswith(name+'-') for d in values): raise ValueError('Wrong archive year')
        return name,values,meta
    successful={}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures={pool.submit(retrieve,j):j[0] for j in jobs}
        for future in as_completed(futures):
            try:
                name,values,meta=future.result(); successful[name]=(values,meta)
            except Exception as exc: warnings.append(f'{futures[future]}: {exc}')
    for name,url in jobs:
        if name not in successful: continue
        values,meta=successful[name]; sources[url]=meta; fresh+=1
        for day,rec in values.items():
            prev=raw.setdefault(day,{'date':day})
            if name!='api': prev.pop('observation_status',None)
            prev.update(rec)
        if name!='api': state[name]={'rows':len(values),'retrieved_at':meta['retrieved_at'],'sha256':meta['sha256']}
    records=[]
    for day,r in sorted(raw.items()):
        if not ('2021-01-01'<=day<=today.isoformat()): continue
        for k in ('computed','difference','check','value','method'): r.pop(k,None)
        if all(k in r for k in COMP): r['computed']=round(r['current_accounts']+r['deposit_facility']-r['reserve_requirements']-r['marginal_lending'],6)
        if 'reported' in r: r['value']=r['reported']; r['method']='ECB reported'
        elif 'computed' in r: r['value']=r['computed']; r['method']='ECB components'
        else: continue
        r['check']='not_cross_checked'
        if 'reported' in r and 'computed' in r:
            r['difference']=round(r['reported']-r['computed'],6)
            r['check']='ok' if abs(r['difference'])<=3 else 'review'
            if r['check']=='review': warnings.append(f'{day}: ECB reported total differs from components by EUR {r["difference"]:,.3f} million; reported total retained')
        records.append(r)
    present={r['date'] for r in records}; missing=[]; day=date(2021,1,1)
    last=date.fromisoformat(records[-1]['date']) if records else today
    while day<=last:
        if day.weekday()<5 and day.isoformat() not in present: missing.append(day.isoformat())
        day+=timedelta(days=1)
    weekdays=sum(date.fromisoformat(r['date']).weekday()<5 for r in records)
    oldvalues={r['date']:r['value'] for r in old.get('records',[])}
    revised=sum(r['date'] in oldvalues and r['value']!=oldvalues[r['date']] for r in records)
    missing_years=[y for y in range(2021,today.year+1) if str(y) not in state]
    complete=bool(records and not missing and not missing_years)
    if missing: warnings.insert(0,f'{len(missing)} missing weekday observations; never interpolated')
    result={'schema_version':1,'unit':'EUR millions','records':records,'sources':list(sources.values()),'archive_state':state,'last_check':stamp(),'last_success':max((m['retrieved_at'] for _,m in successful.values()),default=old.get('last_success')),'history_complete':complete,'status':('ok' if complete and not warnings else 'partial') if fresh else 'error','warnings':warnings,'missing_years':missing_years,'missing_weekdays':missing,'weekday_observations':weekdays,'crosscheck_review_rows':sum(r['check']=='review' for r in records),'revised_rows':revised,'analytics_basis':'Published Monday-Friday observations by default; all published dates retained in raw data','collector':'GitHub Actions / official ECB sources','schedule_utc':'40 9,12 * * 1-5','offline_import':bool(source_dir)}
    atomic(path,json.dumps(result,allow_nan=False,separators=(',',':')))
    fields=['date','value','reported','computed',*COMP,'difference','check','method','source']
    s=io.StringIO(); w=csv.DictWriter(s,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(records)
    atomic(out/'liquidity.csv',s.getvalue())
    summary={k:v for k,v in result.items() if k not in ('records','sources','archive_state')}
    summary.update(first_date=records[0]['date'] if records else None,last_date=records[-1]['date'] if records else None,all_observations=len(records),latest_millions=records[-1]['value'] if records else None)
    atomic(out/'status.json',json.dumps(summary,indent=2,allow_nan=False)); print(json.dumps(summary,indent=2))
    return 0 if fresh and complete else 2
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--source-dir',type=Path,help='Use hash-verified official source files for offline validation')
    args=p.parse_args(); raise SystemExit(collect(args.source_dir))
