import json
import math
import pytest
from shapely.geometry import box, mapping
import pipeline as p

def feat(g,cls="Other"):
    return {"type":"Feature","properties":{"ClassName":cls},"geometry":mapping(g)}

def test_clipping_ignores_building_and_outside():
    parcel=feat(box(-74.6,40.3,-74.59,40.31))
    a=box(-74.605,40.305,-74.595,40.315)
    v=p.pavement_proxy(parcel,[feat(a),feat(box(-74.599,40.301,-74.598,40.302),"Building")])
    expected=p.transform(p.METRIC,box(-74.6,40.3,-74.59,40.31).intersection(a)).area/p.ACRE_M2
    assert math.isclose(v["raw_other_acres"],expected,abs_tol=.002)
    assert v["other_pavement_proxy_equivalent_low"]<=v["other_pavement_proxy_equivalent_high"]

def test_empty_pavement_is_zero():
    v=p.pavement_proxy(feat(box(-74.6,40.3,-74.59,40.31)),[])
    assert v["raw_other_acres"]==0
    assert v["other_pavement_proxy_equivalent_low"]==0

def test_grid_covers_state():
    g=p.tiles()
    assert len(g)>100
    assert any(z[0]<-75.4 and z[1]<39 for z in g)
    assert any(z[2]>-74 and z[3]>41 for z in g)

def test_query_paginates_by_sorted_ids(monkeypatch):
    def mock(url,params=None,binary=False):
        if params.get("returnIdsOnly")=="true":return {"objectIds":[5,1,4,2,3]}
        ids=list(map(int,params["objectIds"].split(",")))
        return {"type":"FeatureCollection","features":[{"type":"Feature","properties":{"OBJECTID":i},"geometry":mapping(box(-74.6,40.3,-74.599,40.301))} for i in ids]}
    monkeypatch.setattr(p,"fetch",mock)
    features,total=p.query_features("https://example.test/0",[-75,39,-74,41],offset=2,limit=2)
    assert total==5 and [x["properties"]["OBJECTID"] for x in features]==[3,4]

def test_query_rejects_missing_polygons(monkeypatch):
    def mock(url,params=None,binary=False):
        if params.get("returnIdsOnly")=="true":return {"objectIds":[1,2]}
        return {"type":"FeatureCollection","features":[]}
    monkeypatch.setattr(p,"fetch",mock)
    with pytest.raises(RuntimeError,match="Incomplete feature batch"):
        p.query_features("https://example.test/0",[-75,39,-74,41])

def test_pavement_cap_rejects_incomplete_survey(monkeypatch):
    monkeypatch.setattr(p,"fetch",lambda *a,**k:{"objectIds":[1,2,3]})
    with pytest.raises(RuntimeError,match="exceeds cap"):
        p.query_features("https://example.test/0",[-75,39,-74,41],cap=2)

def test_source_failure_writes_audit(monkeypatch,tmp_path):
    monkeypatch.setattr(p,"check_services",lambda:(_ for _ in ()).throw(RuntimeError("no network")))
    from argparse import Namespace
    a=Namespace(out=str(tmp_path),tiles=1,per_tile=1,max_results=20,minimum_proxy=100,exclusions="")
    with pytest.raises(RuntimeError,match="no network"):
        p.run(a)
    audits=list(tmp_path.glob("*_audit.json"))
    assert len(audits)==1
    assert "no network" in json.loads(audits[0].read_text())["service_failure"]
