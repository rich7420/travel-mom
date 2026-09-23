from app.providers.mock import demo_provider
from app.services.scoring import rank_flights, rank_hotels


def test_rankings():
    f=rank_flights(demo_provider.flights('TPE','NRT',2))
    h=rank_hotels(demo_provider.hotels('Tokyo',3))
    assert len(f)==3 and len(h)==3
    assert f[0]['score'] >= f[-1]['score']
    assert h[0]['score'] >= h[-1]['score']
    assert all(not x['option']['customer_safe'] for x in f)
