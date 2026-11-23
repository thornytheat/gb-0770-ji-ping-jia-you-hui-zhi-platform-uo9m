"""航司归属：判定票据能否按承运航司单独出证。

整班证据单含有多家航司的票面，直接外发会泄露别家数据；裁过的单子若沿用
整班摘要又无法复验。这里只解析归属并标出留待核的票，分册的组装见
``app/dispatch/document.py``。
"""
from collections import defaultdict

AIRLINE_MISSING = 'AIRLINE_MISSING'
AIRLINE_CONFLICT = 'AIRLINE_CONFLICT'
HELD = frozenset({AIRLINE_MISSING,AIRLINE_CONFLICT})


def same_airline(left, right):
    return (isinstance(left,str) and isinstance(right,str) and left.strip()!=''
            and left.strip().casefold()==right.strip().casefold())


def tracked(sheets):
    """只要任一票据来源带航司列，归属就参与核验；都没有时整班照旧。"""
    return any('airline' in sheets.get(name,{}).get('fields',()) for name in ('tickets','receipts'))


def _declared(sheets, channel):
    grouped = defaultdict(list)
    for row in sheets[channel]['rows']:
        grouped[row['data']['ticket']].append(row['data'].get('airline'))
    for row in sheets[channel]['quarantine']:
        data = row.get('data')
        if data and row.get('code')=='CONFLICT':
            grouped[data['ticket']].append(data.get('airline'))
    return grouped


def resolution(sheets):
    """返回 ``({票号: 航司}, {票号: 留待核原因})``。

    票面声明优先；票面未声明时取回执的唯一航司。两处不一致、同票原件
    归属不一致或两处都缺，都留待核。航司名按首次出现的写法归一。
    """
    if not tracked(sheets):
        return {},{}
    canonical_names = {}
    def display(name):
        canonical_names.setdefault(name.strip().casefold(),name.strip())
        return canonical_names[name.strip().casefold()]
    declared_tickets = {}
    for row in sheets['tickets']['rows']:
        declared_tickets.setdefault(row['data']['ticket'],row['data'].get('airline'))
    conflict_airlines = defaultdict(set)
    for channel in ('tickets','receipts'):
        for ticket,info in sheets[channel].get('airline_conflicts',{}).items():
            conflict_airlines[ticket] |= {name.casefold() for name in info['airlines']}
    declared_receipts = _declared(sheets,'receipts')
    names,held,known = {},{},set()
    for ticket,declared in declared_tickets.items():
        known.add(ticket)
        receipt_names = [name for name in declared_receipts.get(ticket,()) if name]
        if conflict_airlines.get(ticket):
            held[ticket] = AIRLINE_CONFLICT
            label = declared or (receipt_names[0] if receipt_names else None)
            if label:
                names[ticket] = display(label)
        elif declared:
            if any(not same_airline(name,declared) for name in receipt_names):
                held[ticket] = AIRLINE_CONFLICT
            names[ticket] = display(declared)
        elif len({name.casefold() for name in receipt_names})>1:
            held[ticket] = AIRLINE_CONFLICT
        elif receipt_names:
            names[ticket] = display(receipt_names[0])
        else:
            held[ticket] = AIRLINE_MISSING
    for ticket,values in declared_receipts.items():
        if ticket in known:
            continue
        named = [name for name in values if name]
        if len({name.casefold() for name in named})>1:
            held[ticket] = AIRLINE_CONFLICT
        elif named:
            names[ticket] = display(named[0])
        else:
            held[ticket] = AIRLINE_MISSING
    return names,held


def airline_of(intake):
    return resolution(intake['sheets'])[0]


def held_tickets(intake):
    return resolution(intake['sheets'])[1]


def airlines(intake):
    """可出证的航司：至少有一张归属明确、未被留待核的计量票。"""
    names,held = resolution(intake['sheets'])
    eligible = {name.strip().casefold():name.strip() for ticket,name in names.items()
                if ticket not in held}
    return sorted(eligible.values())


def has_evidence(intake, airline):
    names,held = resolution(intake['sheets'])
    return any(same_airline(name,airline) and ticket not in held for ticket,name in names.items())


def canonical(intake, airline):
    """按票面首次出现的写法取得该航司的展示名。"""
    if not isinstance(airline,str) or not airline.strip():
        return None
    for name in airline_of(intake).values():
        if same_airline(name,airline):
            return name
    return None


def owned(record, airline):
    return same_airline(record.get('airline'),airline)


def airline_balance(balance, airline):
    """只保留该航司自身的签收回执与差异；整车库存是实物账，不随航司拆分。"""
    rows = [row for row in balance['receipts']
            if owned(row,airline) and row['state'] not in HELD]
    withheld = sorted(row['ticket'] for row in balance['receipts']
                      if owned(row,airline) and row['state'] in HELD)
    unmatched = [row for row in balance['unmatched_receipts'] if owned(row,airline)]
    states = {}
    for row in rows:
        states[row['state']] = states.get(row['state'],0)+1
    return {'airline':airline,'scope':'airline','receipts':rows,'unmatched_receipts':unmatched,
            'states':states,'held':withheld,
            'receipt_delta_g':sum(row['variance_g'] for row in rows if row['variance_g'] is not None),
            'open_items':sum(count for key,count in states.items() if key!='MATCH')+len(unmatched)}


def airline_sources(intake, airline, held):
    """该航司自己的原件行；别家票面、无法归属的隔离件都不外发。"""
    sheets = intake['sheets']
    owner = airline_of(intake)

    def ticket_owned(row):
        return same_airline(owner.get(row['data']['ticket']),airline)

    def receipt_owned(row):
        own = row['data'].get('airline')
        return same_airline(own,airline) or same_airline(owner.get(row['data']['ticket']),airline)

    def quarantine_owned(row):
        data = row.get('data')
        if not data or data.get('ticket') in held:
            return False
        return owned(data,airline) or same_airline(owner.get(data.get('ticket')),airline)

    def sheet(rows,quarantine):
        return {'rows':rows,'accepted':len(rows),'isolated':len(quarantine),'quarantine':quarantine}

    return {'tickets':sheet([row for row in sheets['tickets']['rows']
                             if ticket_owned(row) and row['data']['ticket'] not in held],
                            [row for row in sheets['tickets']['quarantine'] if quarantine_owned(row)]),
            'receipts':sheet([row for row in sheets['receipts']['rows']
                              if receipt_owned(row) and row['data']['ticket'] not in held],
                             [row for row in sheets['receipts']['quarantine'] if quarantine_owned(row)])}
