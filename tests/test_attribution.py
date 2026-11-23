from app.bundles import sample_set
from app.ledger.manifest import lock
from app.shift import compute


def carrier(overrides=None):
    bundle = {name:raw.decode() for name,raw in sample_set('carrier').items()}
    bundle.update(overrides or {})
    return {key:value.encode() for key,value in bundle.items()}


def archived(client, bundle=None):
    reply = client.post('/api/shifts',json=bundle or {'sample':'carrier'})
    assert reply.status_code==201
    return '/api/shifts/'+reply.json['batch']


def tickets_in(slip):
    return [row['data']['ticket'] for row in slip['sources']['tickets']['rows']]


def test_airline_column_is_optional():
    plain = compute(sample_set('dirty'))
    assert 'airline' not in plain['intake']['sheets']['tickets']['fields']
    assert all(row['state'] not in ('AIRLINE_MISSING','AIRLINE_CONFLICT') for row in plain['balance']['receipts'])


def test_attributed_bundle_lists_airlines_and_held_tickets(client):
    addr = archived(client)
    result = client.get(addr+'/airlines').json
    assert result['airlines']==['CA','MU']
    assert result['held_reasons']=={'T07':'AIRLINE_CONFLICT','T09':'AIRLINE_MISSING'}


def test_missing_or_conflicting_ownership_is_held_for_review():
    data = compute(carrier())['balance']
    states = {row['ticket']:row['state'] for row in data['receipts']}
    assert (states['T09'],states['T07'])==('AIRLINE_MISSING','AIRLINE_CONFLICT')


def test_ownership_conflict_is_not_a_value_conflict():
    bundle = carrier()
    bundle['receipts'] = bundle['receipts'].replace(
        b'T01,FT-12,80.4,R01,MU',b'T01,FT-12,80.4,R01,MU\nT01,FT-12,80.4,R01,CA')
    report = compute(bundle)
    sheet = report['intake']['sheets']['receipts']
    assert [row for row in sheet['quarantine'] if row['data']['ticket']=='T01']==[]
    assert sheet['airline_conflicts']['T01']=={'lines':[2,3],'airlines':['CA','MU']}
    assert next(row['state'] for row in report['balance']['receipts'] if row['ticket']=='T01')=='AIRLINE_CONFLICT'


def test_airline_slip_contains_only_that_airline(client):
    addr = archived(client)
    client.post(addr+'/sign',json={'airline':'MU'})
    slip = client.get(addr+'/export',query_string={'airline':'MU'}).json['slip']
    assert set(tickets_in(slip))=={'T01','T02','T03','T04','T05','T06','T08','T10','Q01','UNIT','EDGE'}
    assert all(row['airline'].casefold()=='mu' for row in slip['receipts']['rows'])
    assert slip['scope']['airline']=='MU'
    blob = str(slip)
    assert 'T07' not in blob and 'T09' not in blob and 'S01' not in blob and 'ORPHAN' not in blob


def test_each_airline_slip_reverifies_on_its_own(client):
    addr = archived(client)
    for airline in ('MU','CA'):
        mark = client.post(addr+'/sign',json={'airline':airline}).json
        exported = client.get(addr+'/export',query_string={'airline':airline}).json
        assert exported['verified'] and exported['checksum']==mark['checksum']
        assert exported['checksum']==lock(exported['slip'])


def test_whole_batch_still_verifies_alongside_airline_slips(client):
    addr = archived(client)
    client.post(addr+'/sign',json={'airline':'MU'})
    client.post(addr+'/sign',json={})
    whole = client.get(addr+'/export').json
    assert whole['verified'] and whole['slip']['document']=='机坪加注证据单'
    states = {row['ticket']:row['state'] for row in whole['slip']['conservation']['receipts']}
    assert states['T09']=='AIRLINE_MISSING' and states['T07']=='AIRLINE_CONFLICT'
    assert 'S01' in [row['data']['ticket'] for row in whole['slip']['sources']['tickets']['rows']]


def test_repeat_signing_never_adds_a_record(client,ramp):
    addr = archived(client)
    first = client.post(addr+'/sign',json={'airline':'MU'}).json
    again = client.post(addr+'/sign',json={'airline':'mu'}).json
    assert again==dict(first,reused=True)
    client.post(addr+'/sign',json={'airline':'CA'})
    client.post(addr+'/sign',json={})
    with ramp.book.connection() as db:
        rows = db.execute('SELECT scope FROM signatures ORDER BY scope').fetchall()
    assert rows==[('',),('ca',),('mu',)]


def test_airline_slip_carries_its_own_manifest_summary(client):
    addr = archived(client)
    client.post(addr+'/sign',json={'airline':'CA'})
    exported = client.get(addr+'/export',query_string={'airline':'CA'}).json
    slip = exported['slip']
    assert slip['manifest']['batch']==exported['checksum'] or slip['manifest']['batch']
    assert slip['manifest']['fleet_sha256'] and slip['manifest']['rules']
    assert slip['summary']['tickets']==len(slip['sources']['tickets']['rows'])==4


def test_unknown_airline_is_rejected(client):
    addr = archived(client)
    assert client.post(addr+'/sign',json={'airline':'ZZ'}).status_code==404
    assert client.get(addr+'/export',query_string={'airline':'ZZ'}).status_code==409


def test_unsigned_airline_scope_cannot_export(client):
    addr = archived(client)
    response = client.get(addr+'/export',query_string={'airline':'MU'})
    assert (response.status_code,response.json['error'])==(409,'NOT_SIGNED')


def test_airline_signing_does_not_change_metering(client):
    addr = archived(client)
    before = client.get(addr).json['stages']['mass']
    client.post(addr+'/sign',json={'airline':'MU'})
    assert client.get(addr).json['stages']['mass']==before


def test_mutated_snapshot_still_reports_unverified_for_airline(client,ramp):
    addr = archived(client)
    client.post(addr+'/sign',json={'airline':'CA'})
    with ramp.book.connection() as db:
        db.execute("UPDATE stage_rows SET body='{}' WHERE phase='balance'")
    exported = client.get(addr+'/export',query_string={'airline':'CA'}).json
    assert exported['verified'] is False


def test_case_variants_share_one_airline_scope(client):
    addr = archived(client)
    first = client.post(addr+'/sign',json={'airline':'mu'}).json
    second = client.post(addr+'/sign',json={'airline':' Mu '}).json
    assert (first['airline'],second['airline'])==('MU','MU')
    assert second==dict(first,reused=True)


def test_airline_without_eligible_ticket_cannot_be_signed(client):
    bundle = {
        'tickets':('ticket,truck,opened,closed,start_l,stop_l,event,fuel,rho,rho_unit,temp_c,airline\n'
                   'S01,FT-18,2026-11-22T01:10:00Z,2026-11-22T01:20:00Z,10,60,normal,JET-A1,800,kg/m3,15,CA\n'
                   'S02,FT-18,2026-11-22T02:00:00Z,2026-11-22T02:10:00Z,60,90,normal,JET-A1,800,kg/m3,15,\n'),
        'receipts':('ticket,truck,signed_kg,document,airline\n'
                    'S01,FT-18,40.0,R11,CA\n'),
        'stock':'truck,movement,kind,kg\nFT-18,O18,opening,140\nFT-18,C18,closing,104\n'}
    addr = '/api/shifts/'+client.post('/api/shifts',json=bundle).json['batch']
    assert client.post(addr+'/sign',json={'airline':'MU'}).status_code==404
    assert client.post(addr+'/sign',json={'airline':'CA'}).status_code==200


def test_unknown_header_column_is_still_rejected(client):
    bundle = carrier()
    bundle['tickets'] = bundle['tickets'].replace(b',airline',b',airline,cabin')
    data = {name:value.decode() for name,value in bundle.items()}
    response = client.post('/api/intake',json=data)
    assert (response.status_code,response.json['error'])==(422,'HEADER')


def test_intake_exposes_field_list_and_airline_conflicts(client):
    bundle = carrier()
    bundle['receipts'] = bundle['receipts'].replace(
        b'T01,FT-12,80.4,R01,MU',b'T01,FT-12,80.4,R01,MU\nT01,FT-12,80.4,R01,CA')
    report = client.post('/api/intake',json={name:value.decode() for name,value in bundle.items()}).json
    sheet = report['sheets']['receipts']
    assert 'airline' in sheet['fields'] and sheet['airline_conflicts']['T01']['airlines']==['CA','MU']
    assert [row['data']['ticket'] for row in sheet['quarantine'] if row['code']=='CONFLICT']==['S03','S03']


def test_airline_slips_carry_distinct_digests(client):
    addr = archived(client)
    mu = client.post(addr+'/sign',json={'airline':'MU'}).json['checksum']
    ca = client.post(addr+'/sign',json={'airline':'CA'}).json['checksum']
    whole = client.post(addr+'/sign',json={}).json['checksum']
    assert len({mu,ca,whole})==3
