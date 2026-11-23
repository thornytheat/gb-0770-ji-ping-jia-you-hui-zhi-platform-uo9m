from collections import Counter, defaultdict

from app.diagnostics import RampError, detail
from .reader import rows_from
from .schemas import COLUMNS, OPTIONAL, convert_fields


def _values(data):
    """归属不参与原件比对：数值相同但航司不同的重复行是归属冲突，不是数值冲突。"""
    return {key:value for key,value in data.items() if key!='airline'}


def channel_report(channel, raw):
    optional = OPTIONAL[channel]
    groups = defaultdict(list)
    rejected, repeated = [], []
    airline_conflicts = {}
    count, segments, fields = 0,1,[]
    for line,header,row in rows_from(raw,COLUMNS[channel],optional):
        fields = header
        if row==header:
            segments += 1
            continue
        count += 1
        try:
            if not any(field.strip() for field in row):
                raise ValueError('BLANK_ROW')
            if len(row)!=len(header):
                raise ValueError('WIDTH')
            values = {key:value.strip() for key,value in zip(header,row)}
            has_airline = 'airline' in values
            airline = values.pop('airline','').strip() or None
            data = convert_fields(values,channel)
            if has_airline:
                data['airline'] = airline
            identity = (data['truck'],data['movement']) if channel=='stock' else data['ticket']
            groups[identity].append({'line':line,'data':data,'raw':row})
        except ValueError as exc:
            origin = dict(zip(header,row)) if len(row)==len(header) else {}
            rejected.append(dict(detail(str(exc)),line=line,raw=row,
                                 truck=origin.get('truck','').strip() or None))
    if not count:
        raise RampError('HEADER_ONLY')
    kept = []
    for group in groups.values():
        first,*rest = group
        if any(_values(item['data'])!=_values(first['data']) for item in rest):
            related = [item['line'] for item in group]
            rejected.extend(dict(detail('CONFLICT'),line=r['line'],raw=r['raw'],data=r['data'],related=related)
                            for r in group)
            continue
        named = {item['data']['airline'] for item in group if item['data'].get('airline')}
        if channel!='stock' and len({name.casefold() for name in named})>1:
            airline_conflicts[first['data']['ticket']] = {'lines':[item['line'] for item in group],
                                                          'airlines':sorted(named)}
        elif 'airline' in optional and not first['data'].get('airline') and named:
            first['data']['airline'] = min(named)
        kept.append(first)
        repeated.extend({'line':item['line'],'kept':first['line']} for item in rest)
    return {'input':count,'accepted':len(kept),'isolated':len(rejected),'duplicate':len(repeated),'segments':segments,
            'fields':list(fields),'rows':kept,'quarantine':sorted(rejected,key=lambda e:e['line']),
            'repeat_sources':repeated,'airline_conflicts':airline_conflicts,
            'reasons':dict(Counter(row['code'] for row in rejected))}


def admit(files):
    sheets = {name:channel_report(name,files[name]) for name in COLUMNS}
    totals = {key:sum(sheet[key] for sheet in sheets.values()) for key in ('input','accepted','isolated','duplicate')}
    return dict(totals,sheets=sheets)
