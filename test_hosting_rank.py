import pytest
from shapely.geometry import Point
import hosting_rank as h

def test_ace_kilowatts_to_megawatts():
    mw,circ,sub,date,info,q = h.parse_capacity("ACE",{
        "Allowable_PV_kW":1850,"FeederID":"NJ0081","Substation":"South",
        "Total_Pending_Gen_kW":120})
    assert mw==1.85 and circ=="NJ0081" and q==120

def test_pseg_uses_bottleneck_not_feeder_only():
    mw,*_ = h.parse_capacity("PSEG",{
        "circuitavailability":4500,"stationavailability":300,
        "TotalAvailabilitySymbol":300})
    assert mw==pytest.approx(.3)
    mw2,*_ = h.parse_capacity("PSEG",{
        "circuitavailability":1000,"stationavailability":0})
    assert mw2==0

def test_oru_zero_note_overrides_map_placeholder():
    mw,*_ = h.parse_capacity("ORU",{"PV_SECTION":.1,"NOTES":"There is no Capacity available on this Circuit."})
    assert mw==0

def test_jcpl_category_is_lower_bound_not_exact():
    low,label=h.jcp_capacity({"RemainNum":0,"Remaining":"Less than 100 kW AC"})
    assert low==0
    bounded,_=h.jcp_capacity({"Remaining":"500 to 1,000 kW AC"})
    assert bounded==.5
    upper,_=h.jcp_capacity({"Remaining":"Greater than 1,000 kW AC"})
    assert upper==1.0

def test_actual_capacity_relative_to_project():
    r={"candidate_other_acres":4,"tax_class":"4A","property_use":"733"}
    m=[{"utility":"ACE","utility_name":"Atlantic City Electric",
      "hosting_screen_mw":2.0,"distance_m":100,"feeder":"NJ0001","station":"A",
      "map_refresh":"2026-10-01","evidence":"test","queued_raw":0,
      "layer":h.ACE,"feature_id":"1","geometry_kind":"LineString"}]
    x=h.rank(r,m,[])
    assert x["hosting_score"].startswith("A")
    assert x["hosting_capacity_to_project_ratio"]>1

def test_unknown_when_no_map_match():
    x=h.rank({"candidate_other_acres":2,"tax_class":"4A"},[],[])
    assert x["hosting_map_mw"]==""
    assert "UNKNOWN" in x["hosting_score"]

def test_nearest_feeder_is_used_not_highest_distant_feeder():
    r={"candidate_other_acres":4,"tax_class":"4A","property_use":"733"}
    base={"utility":"ACE","utility_name":"Atlantic City Electric",
      "feeder":"F1","station":"S","map_refresh":"","evidence":"","queued_raw":None,
      "layer":h.ACE,"feature_id":"1","geometry_kind":"LineString"}
    a={**base,"hosting_screen_mw":0.1,"distance_m":40}
    b={**base,"hosting_screen_mw":10.0,"distance_m":300,"feeder":"F2"}
    x=h.rank(r,[a,b],[])
    assert x["hosting_feeder"]=="F1"
    assert x["hosting_map_mw"]==0.1
