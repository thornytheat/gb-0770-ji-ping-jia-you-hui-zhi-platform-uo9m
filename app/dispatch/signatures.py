from app.diagnostics import RampError
from app.ledger.manifest import lock
from app.ledger.replay import shift
from app.settlement.attribution import (airlines as airline_names, canonical, has_evidence, held_tickets,
                                        airline_of, same_airline)
from .document import compile_slip

WHOLE = ''


def target(snapshot, airline):
    """解析出证范围：整班返回 ``('',None)``；航司返回分册键与票面写法。"""
    if airline is None:
        return WHOLE,None
    if not isinstance(airline,str):
        raise RampError('BUNDLE')
    if not airline.strip():
        return WHOLE,None
    name = canonical(snapshot['stages']['intake'],airline)
    if name is None or not has_evidence(snapshot['stages']['intake'],name):
        raise RampError('AIRLINE',404)
    return name.strip().casefold(),name


def sign(book, batch, airline=None):
    snapshot = shift(book,batch)
    scope,name = target(snapshot,airline)
    attestation = compile_slip(snapshot,name)
    checksum = lock(attestation)
    with book.connection() as db:
        inserted = db.execute('INSERT INTO signatures (batch,scope,checksum) VALUES (?,?,?) '
                              'ON CONFLICT(batch,scope) DO NOTHING',(batch,scope,checksum)).rowcount
        saved = db.execute('SELECT checksum FROM signatures WHERE batch=? AND scope=?',(batch,scope)).fetchone()[0]
    held = held_tickets(snapshot['stages']['intake'])
    if name is not None:
        owner = airline_of(snapshot['stages']['intake'])
        held = {ticket:code for ticket,code in held.items()
                if same_airline(owner.get(ticket),name)}
    open_items = (attestation['summary']['open_items'] if name is not None else
                  sum(n for key,n in attestation['conservation']['states'].items() if key!='MATCH')
                  + len(attestation['conservation']['unmatched_receipts']))
    return {'batch':batch,'airline':name,'scope':'whole' if name is None else 'airline',
            'checksum':saved,'reused':not bool(inserted),'open_items':open_items,
            'held_for_review':len(held),
            'held_trucks':snapshot['stages']['balance']['held_trucks']}


def evidence_file(book, batch, airline=None):
    snapshot = shift(book,batch)
    if airline is not None and not isinstance(airline,str):
        raise RampError('BUNDLE')
    scope = WHOLE if not airline or not airline.strip() else airline.strip().casefold()
    with book.connection() as db:
        signature = db.execute('SELECT checksum FROM signatures WHERE batch=? AND scope=?',
                               (batch,scope)).fetchone()
    if signature is None:
        raise RampError('NOT_SIGNED',409)
    name = None if scope==WHOLE else (canonical(snapshot['stages']['intake'],airline) or airline.strip())
    try:
        document = compile_slip(snapshot,name)
        verified, slip = signature[0]==lock(document), document
    except (KeyError,TypeError,AttributeError):
        verified, slip = False, None
    return {'scope':'whole' if name is None else 'airline','airline':name,
            'checksum':signature[0],'verified':verified,'slip':slip,
            'snapshot':'MUTATED' if slip is None else 'OK'}


def available_airlines(book, batch):
    intake = shift(book,batch)['stages']['intake']
    held = held_tickets(intake)
    return {'airlines':airline_names(intake),
            'held':sorted(held),'held_reasons':{ticket:held[ticket] for ticket in sorted(held)}}
