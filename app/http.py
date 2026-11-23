from flask import Blueprint, current_app, jsonify, request
from app.bundles import submitted
from app.diagnostics import RampError
from app.dispatch.signatures import available_airlines,evidence_file,sign
from app.ledger.replay import list_shifts,replay,shift
from app.shift import compute

routes = Blueprint('ramp_api',__name__)


def evaluate(stage):
    return compute(submitted(),stage)[stage]


@routes.route('/api/intake',methods=['GET','POST'])
def intake():
    return evaluate('intake')


@routes.route('/api/versions',methods=['GET','POST'])
def versions():
    return evaluate('versions')


@routes.route('/api/readings',methods=['GET','POST'])
def readings():
    return evaluate('readings')


@routes.route('/api/mass',methods=['GET','POST'])
def mass():
    return evaluate('mass')


@routes.route('/api/balance',methods=['GET','POST'])
def balance():
    return evaluate('balance')


@routes.get('/api/shifts')
def shifts():
    return {'shifts':list_shifts(current_app.book)}


@routes.post('/api/shifts')
def archive():
    result = replay(current_app.book,submitted())
    return result,200 if result['reused'] else 201


@routes.get('/api/shifts/<batch>')
def load(batch):
    return shift(current_app.book,batch)


@routes.get('/api/shifts/<batch>/airlines')
def airlines(batch):
    return available_airlines(current_app.book,batch)


@routes.post('/api/shifts/<batch>/sign')
def issue(batch):
    body = request.get_json(silent=True) if request.data else None
    airline = body.get('airline') if isinstance(body,dict) else None
    if airline is not None and not isinstance(airline,str):
        raise RampError('BUNDLE')
    return sign(current_app.book,batch,airline)


@routes.get('/api/shifts/<batch>/export')
def export(batch):
    airline = request.args.get('airline')
    if airline is not None and not airline.strip():
        airline = None
    result = jsonify(evidence_file(current_app.book,batch,airline))
    suffix = '' if result.json['airline'] is None else '-'+result.json['airline'].replace(' ','_')
    result.headers['Content-Disposition'] = f'attachment; filename="fuel-{batch}{suffix}.json"'
    return result
