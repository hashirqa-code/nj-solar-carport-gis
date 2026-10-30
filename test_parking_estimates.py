from parking_estimates import estimate,land_use_group

def test_shopping_center_approximates_spaces_from_mixed_pavement():
    r={"candidate_other_acres":3.05,"largest_other_piece_acres":3.05,
       "tax_class":"4A","property_use":"733"}
    e=estimate(r)
    assert e["parking_land_use_group"]=="retail"
    assert 170 <= e["parking_estimate_low"] <= 200
    assert 260 <= e["parking_estimate_likely"] <= 300
    assert 360 <= e["parking_estimate_high"] <= 400
    assert "ASSUMED_SHARE" in e["parking_estimate_method"]

def test_industrial_uses_smaller_assumed_parking_fraction():
    r={"candidate_other_acres":7.326,"largest_other_piece_acres":7.326,
       "tax_class":"4B","property_use":"330"}
    e=estimate(r)
    assert e["parking_land_use_group"]=="industrial"
    assert 100 <= e["parking_estimate_low"] <= 120
    assert 270 <= e["parking_estimate_likely"] <= 320
    assert 530 <= e["parking_estimate_high"] <= 580

def test_osm_parking_area_is_anchor_not_verification():
    r={"candidate_other_acres":3.05,"largest_other_piece_acres":3.05,
       "tax_class":"4A","property_use":"733","osm_surface_parking_acres":1.7}
    e=estimate(r)
    assert "OSM_MAPPED" in e["parking_estimate_method"]
    assert "LOW" in e["parking_estimate_quality"]
    assert e["parking_estimate_low"]<=e["parking_estimate_likely"]<=e["parking_estimate_high"]

def test_fallback_does_not_fabricate_when_no_geometry():
    e=estimate({"candidate_other_acres":"","osm_surface_parking_acres":""})
    assert e["parking_estimate_likely"]==0
    assert e["parking_estimate_quality"]=="NO_ESTIMATE"

def test_workbook_column_lengths_and_nonblank_estimates():
    from enrich_reports import FIELDS,to_workbook_row
    row={"address":"621 HAMILTON ST","municipality":"FRANKLIN TWP",
         "county":"SOMERSET","tax_class":"4A","property_use":"733",
         "candidate_other_acres":"3.05","largest_other_piece_acres":"3.05"}
    out=to_workbook_row(row,1)
    assert len(out)==len(FIELDS)
    assert out[FIELDS.index("Est Parking Likely")]>=260
    assert out[FIELDS.index("Documented Parking Spaces (if sourced)")]==""
