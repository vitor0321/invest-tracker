from invest.scoring import classify, compute_score
from invest.valuation import QualityResult

W = {"folga": 0.5, "qualidade": 0.3, "regularidade": 0.2}
OK = QualityResult(True, [])
BAD = QualityResult(False, ["payout"])


def test_score():
    assert compute_score(40, 50, True, 1.0, W) == 60
    assert compute_score(60, 50, True, 1.0, W) == 50
    assert compute_score(40, None, True, 1.0, W) is None


def kw(**o):
    base = dict(price=40.0, reference=50.0, quality=OK, dividend_cut=False,
                payout=0.5, data_age_days=1, held=False)
    base.update(o)
    return base


def test_each_signal():
    assert classify(**kw()) == "oportunidade"
    assert classify(**kw(price=60.0, held=True)) == "caro"
    assert classify(**kw(price=60.0, held=False)) == "neutro"
    assert classify(**kw(quality=BAD)) == "neutro"
    assert classify(**kw(dividend_cut=True)) == "risco"
    assert classify(**kw(payout=1.2)) == "risco"
    assert classify(**kw(data_age_days=11)) == "dado_velho"
    assert classify(**kw(reference=None)) == "sem_dados"


def test_precedence():
    assert classify(**kw(data_age_days=11, dividend_cut=True)) == "dado_velho"
    assert classify(**kw(reference=None, data_age_days=11)) == "dado_velho"
    assert classify(**kw(dividend_cut=True)) == "risco"
