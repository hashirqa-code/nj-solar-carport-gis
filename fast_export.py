"""Guaranteed first-stage XLSX fallback, without waiting on OSM or imagery services."""
import csv
import json
import sys
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
from enrich_reports import FIELDS, to_workbook_row, write_xlsx

def run(folder="daily_reports"):
    p=Path(folder)
    day=datetime.now(ZoneInfo("America/New_York")).date().isoformat()
    src=p/f"{day}_hosting_enriched.csv"
    if not src.exists():src=p/f"{day}_provisional_parcels.csv"
    if src.exists():
        with src.open("r",encoding="utf-8-sig",newline="") as f:
            rows=list(csv.DictReader(f))
    elif (p/f"{day}_audit.json").exists():
        rows=[]
    else:
        raise RuntimeError(f"No live GIS audit for {day}; won't recycle a stale report")
    for r in rows:
        r["parking_evidence_level"]="PARKING UNKNOWN — NJDEP OTHER PAVEMENT ONLY"
        r["osm_solar_warning"]="NOT CHECKED"
        r["aerial_image_status"]="NOT YET CHECKED"
        r["osm_surface_parking_acres"]=0
        r["osm_largest_parking_polygon_acres"]=0
        r["osm_parking_capacity_published"]=""
        r["aerial_image_filename"]=""
        r["osm_parking_feature_ids"]=""
        r["osm_solar_feature_ids"]=""
    from parking_estimates import estimate_solar_mw
    rows.sort(key=lambda r:(
        3 if str(r.get("hosting_score","")).startswith("A") else
        2 if str(r.get("hosting_score","")).startswith("B") else
        1 if str(r.get("hosting_score","")).startswith("C") else 0,
        estimate_solar_mw(r)["solar_mwdc_likely"]),reverse=True)
    widths=[8,26,19,16,16,18,16,17,18,17,18,20,38,45,18,20,14,12,12,18,19,17,17,14,15,24,22,22,27,14,20,22,30,30,23,22,18,14,14,54,20,34,22,20,18,20,21,68,42,80]
    notes=[
      ["Field","Explanation"],
      ["Source",str(src)],
      ["Status","PRELIMINARY GIS ONLY — parking and solar checks NOT COMPLETED; zero rows means no new observations today"],
      ["Parking estimates","Low, likely and high spaces are ALLOCATED AREA APPROXIMATIONS, NOT observed painted stalls."],
      ["Estimate formula","2015 Other pavement acres x use-based parking share x 43,560 sq ft / 350, 325, 300 sq ft per stall."],
      ["Solar carport MWdc formula","Low 65% coverage x 2.0 kW/stall; likely 80% x 2.75; high 90% x 3.4. MWdc = stalls x coverage x kW/stall / 1000."],
      ["NREL canopy density cross-check","263 kWdc/acre * preliminary modeled parking acres; https://www.nlr.gov/docs/fy24osti/90070.pdf"],
      ["Interconnection","MWac converter is purely nameplate/DC:AC assumption. Utility hosting unknown."],
      ["Parking share assumptions","Retail 48/68/85%; office 40/60/78%; apartments 32/52/73%; industrial 12/30/52%; others documented in parking_estimates.py."],
      ["Uncertainty","NJDEP 2015 Other pavement includes drives, sidewalks, loading, and sometimes buildings; estimates have LOW confidence."],
      ["Verified parking count","UNKNOWN until imagery/site-plan confirmation."],
      ["Map source","NJGIN MOD-IV 2026 parcels and NJDEP 2015 other impervious"],
      ["Ownership","User verifies independently; blank ownership field by design"],
      ["Utility hosting","Queries ACE, O&R, PSE&G and JCP&L PV generation hosting layers by real parcel coordinates."],
      ["Screening only","Nearest map feature within 400–450m; NOT verified serving feeder or interconnection approval."],
      ["A/B/C Grade","Physical MWac vs nearby public utility map value; A/B/C reflect preliminary proximity not feeder confirmation."],
      ["Unit conversion","ACE and PSE&G utility map fields are kW; O&R maps MW; JCP&L supplies capacity categories."],
      ["Map evidence","Source layer URL, measured distance, map date and feature feeder IDs are recorded per property."],
      ["Fallback reason","This file is created immediately so a third-party OSM outage cannot block spreadsheet delivery."]
    ]
    dst=p/f"{day}_NJ_solar_carport_prospects.xlsx"
    write_xlsx(dst,[("Solar Carport Leads",[FIELDS]+[to_workbook_row(r,i) for i,r in enumerate(rows,1)],widths),
                    ("Method and Audit",notes,[29,110])])
    print(json.dumps({"workbook":str(dst),"provisional_gis_rows":len(rows),"status":"FALLBACK_UNVERIFIED"}))

if __name__=="__main__":
    try:run()
    except Exception as e:
        print("Cannot create fallback workbook:",e,file=sys.stderr)
        sys.exit(2)
