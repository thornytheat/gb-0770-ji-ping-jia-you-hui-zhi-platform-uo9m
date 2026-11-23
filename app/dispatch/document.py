from app.settlement.attribution import airline_balance, airline_sources, airline_of, held_tickets, same_airline


def compile_slip(archive, airline=None):
    stages = archive['stages']
    if airline is None:
        return {'document':'机坪加注证据单','manifest':archive['manifest'],
                'conservation':stages['balance'],'counter_checks':stages['mass']['rows'],
                'sources':stages['intake']['sheets']}
    return compile_airline(archive, airline)


def compile_airline(archive, airline):
    """只装该航司自己的对账依据；别家票面与整车库存账不随分册外发。

    分册带自己的摘要（批次、规则、参数、量程样本），可在不持有整班原件
    的情况下单独复验；整班原单仍按整班摘要各自可验。
    """
    stages = archive['stages']
    intake = stages['intake']
    owner = airline_of(intake)
    held = held_tickets(intake)
    report = airline_balance(stages['balance'],airline)
    checks = [row for row in stages['mass']['rows']
              if same_airline(owner.get(row['ticket']),airline) and row['ticket'] not in held]
    signed = [row for row in report['receipts'] if row['signed_g'] is not None]
    manifest = archive['manifest']
    return {'document':'机坪加注证据单 · 航司分册',
            'scope':{'kind':'airline','airline':airline,'batch':manifest['batch']},
            'manifest':{'batch':manifest['batch'],'rules':manifest['rules'],
                        'parameters':manifest['parameters'],'fleet_sha256':manifest['fleet_sha256']},
            'counter_checks':checks,
            'receipts':{'rows':report['receipts'],'unmatched_receipts':report['unmatched_receipts'],
                        'states':report['states']},
            'sources':airline_sources(intake,airline,held),
            'summary':{'tickets':len(checks),
                       'meter_g':sum(row['standard']['mass_g'] for row in checks if row['standard']),
                       'signed_g':sum(row['signed_g'] for row in signed),
                       'variance_g':report['receipt_delta_g'],'open_items':report['open_items']}}
