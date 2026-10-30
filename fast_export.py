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
    src=p/f"{day}_provisional_parcels.csv"
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
    rows.sort(key=lambda r:float(r.get("largest_other_piece_acres") or 0),reverse=True)
    widths=[8,26,19,16,16,18,16,38,45,18,20,14,12,12,18,19,17,17,14,15,24,22,22,27,14,20,22,30,30,23,22,18,14,14,54]
    notes=[
      ["Field","Explanation"],
      ["Source",str(src)],
      ["Status","PRELIMINARY GIS ONLY — parking and solar checks NOT COMPLETED; zero rows means no new observations today"],
      ["Parking estimates","Low, likely and high spaces are ALLOCATED AREA APPROXIMATIONS, NOT observed painted stalls."],
      ["Estimate formula","2015 Other pavement acres x use-based parking share x 43,560 sq ft / 350, 325, 300 sq ft per stall."],
      ["Parking share assumptions","Retail 48/68/85%; office 40/60/78%; apartments 32/52/73%; industrial 12/30/52%; others documented in parking_estimates.py."],
      ["Uncertainty","NJDEP 2015 Other pavement includes drives, sidewalks, loading, and sometimes buildings; estimates have LOW confidence."],
      ["Verified parking count","UNKNOWN until imagery/site-plan confirmation."],
      ["Map source","NJGIN MOD-IV 2026 parcels and NJDEP 2015 other impervious"],
      ["Ownership","User verifies independently; blank ownership field by design"],
      ["Utility hosting","UNKNOWN until feeder-specific map validation"],
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
