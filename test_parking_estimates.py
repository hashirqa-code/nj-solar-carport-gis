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


def test_carport_mw_scenarios_derive_from_stall_estimates():
    from parking_estimates import estimate_solar_mw
    from enrich_reports import FIELDS,to_workbook_row
    r={"address":"621 HAMILTON ST","municipality":"FRANKLIN TWP",
       "tax_class":"4A","property_use":"733",
       "candidate_other_acres":"3.05","largest_other_piece_acres":"3.05"}
    e=estimate(r); m=estimate_solar_mw(r)
    assert m["solar_mwdc_low"] == round(e["parking_estimate_low"] * .65 * 2.0 / 1000,3)
    assert m["solar_mwdc_likely"] == round(e["parking_estimate_likely"] * .8 * 2.75 / 1000,3)
    assert m["solar_mwdc_high"] == round(e["parking_estimate_high"] * .9 * 3.4 / 1000,3)
    assert m["solar_mwdc_low"] < m["solar_mwdc_likely"] < m["solar_mwdc_high"]
    values=to_workbook_row(r,1)
    assert len(values)==len(FIELDS)
    assert values[FIELDS.index("Carport MWdc Likely")] == m["solar_mwdc_likely"]
    assert values[FIELDS.index("Carport MWdc High")] == m["solar_mwdc_high"]
