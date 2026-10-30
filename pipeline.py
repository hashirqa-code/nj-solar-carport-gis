#!/usr/bin/env python3
"""NJ solar-carport parcel + 2015 other-impervious GIS screening.
GIS proxy areas are NOT verified parking footprints or parking-space counts.
"""
import argparse
import csv
import json
import math
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from pyproj import Transformer
from shapely.geometry import shape, box, Polygon
from shapely.ops import transform, unary_union

PARCEL = "https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/arcgis/rest/services/Parcels_Composite_NJ_WM/FeatureServer/0"
PAVEMENT = "https://mapsdep.nj.gov/arcgis/rest/services/Cached_Layers/Rast_impervious_surface_3857/MapServer/0"
ORTHO = "https://maps.nj.gov/arcgis/rest/services/Basemap/Orthos_Natural_2020_NJ_WM/MapServer"
METRIC = Transformer.from_crs(4326, 5070, always_xy=True).transform
ACRE_M2 = 4046.8564224
FT2_M2 = 10.76391041671
S = requests.Session()
S.headers["User-Agent"] = "NJ-Carport-GIS-Public-Research/1.0"

def fetch(url, params=None, binary=False):
    last = None
    for attempt in range(3):
        try:
            r = S.post(url, data=params or {"f":"json"}, timeout=65)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(2*(attempt+1)); continue
            r.raise_for_status()
            if binary: return r.content
            d = r.json()
            if "error" in d: raise RuntimeError(f"ArcGIS error: {d['error']}")
            return d
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last = str(exc)
            if attempt < 2: time.sleep(2*(attempt+1))
    raise RuntimeError(f"{url}: {last}")

def check_services():
    checks = {}
    for name, url, required in [
        ("NJGIN parcels", PARCEL, ["fields", "objectIdField"]),
        ("NJDEP other pavement", PAVEMENT, ["fields", "objectIdField"])
    ]:
        m = fetch(url, {"f":"json"})
        fields = {f["name"] for f in m.get("fields", [])}
        must = {"PROP_CLASS","PROP_LOC"} if name.startswith("NJGIN") else {"ClassName"}
        if not must <= fields: raise RuntimeError(f"{name} missing fields: {must-fields}")
        if not m.get("objectIdField") and not any(x.get("type")=="esriFieldTypeOID" for x in m.get("fields",[])):
            raise RuntimeError(f"{name}: cannot identify ObjectID field")
        checks[name]={"url":url, "maxRecordCount":m.get("maxRecordCount"),"found_fields":sorted(must)}
    return checks

def query_features(url, bbox, where="1=1", fields="*", offset=0, limit=40, cap=None):
    geom = json.dumps({"xmin":bbox[0],"ymin":bbox[1],"xmax":bbox[2],"ymax":bbox[3],
                       "spatialReference":{"wkid":4326}})
    common={"f":"json","geometry":geom,"geometryType":"esriGeometryEnvelope",
            "inSR":"4326","spatialRel":"esriSpatialRelIntersects","where":where}
    ids = fetch(url+"/query", dict(common,returnIdsOnly="true"))
    if not isinstance(ids.get("objectIds"),(list,type(None))):
        raise RuntimeError("Missing objectIds; incomplete GIS query")
    all_ids = sorted(ids["objectIds"] or [])
    if cap is not None and len(all_ids)>cap:
        raise RuntimeError(f"Polygon count {len(all_ids)} exceeds cap {cap}; cannot claim complete pavement")
    chosen = all_ids[offset:offset+limit] if limit is not None else all_ids[offset:]
    features=[]
    for k in range(0,len(chosen),40):
        batch=chosen[k:k+40]
        p={"f":"geojson","objectIds":",".join(map(str,batch)),"outFields":fields,
           "returnGeometry":"true","outSR":"4326"}
        d=fetch(url+"/query",p)
        got=d.get("features")
        if d.get("type")!="FeatureCollection" or not isinstance(got,list) or len(got)!=len(batch):
            raise RuntimeError(f"Incomplete feature batch: requested {len(batch)}")
        features.extend(got)
    return features, len(all_ids)

def iter_polygons(g):
    if g.is_empty: return []
    if g.geom_type=="Polygon": return [g]
    if hasattr(g,"geoms"):
        return [p for part in g.geoms for p in iter_polygons(part)]
    return []

def pavement_proxy(parcel, features):
    """Clip actual NJDEP polygons, not parcel area. Other includes driveways, walks and some roofs."""
    bound=transform(METRIC,shape(parcel["geometry"]))
    if not bound.is_valid: bound=bound.buffer(0)
    pieces=[]
    for f in features:
        if str(f.get("properties",{}).get("ClassName","")).casefold()!="other":continue
        geom=transform(METRIC,shape(f["geometry"]))
        if not geom.is_valid: geom=geom.buffer(0)
        if geom.intersects(bound):pieces.append(geom.intersection(bound))
    raw=unary_union(pieces) if pieces else Polygon()
    opening=raw.buffer(-2).buffer(2) if not raw.is_empty else Polygon()
    large=[p for p in iter_polygons(opening) if p.area>=450]
    cleaned=unary_union(large) if large else Polygon()
    return {"raw_other_acres":round(raw.area/ACRE_M2,3),
            "candidate_other_acres":round(cleaned.area/ACRE_M2,3),
            "largest_other_piece_acres":round(max((p.area for p in iter_polygons(cleaned)),default=0)/ACRE_M2,3),
            "other_pavement_proxy_equivalent_low":math.floor(cleaned.area*FT2_M2/350),
            "other_pavement_proxy_equivalent_high":math.floor(cleaned.area*FT2_M2/300)}

def tiles():
    arr=[]
    x=-75.57
    while x < -73.88:
        y=38.91
        while y < 41.36:
            arr.append([round(x,5),round(y,5),round(x+0.18,5),round(y+0.16,5)])
            y+=0.16
        x+=0.18
    # Start near central New Jersey rather than spending the first runs in non-NJ bounding boxes.
    arr.sort(key=lambda b: abs((b[0]+b[2])/2 + 74.55) + 1.1*abs((b[1]+b[3])/2 - 40.40))
    return arr

def norm(value):
    return re.sub("[^a-z0-9]","",str(value or "").casefold())

def initial_exclusions(filename):
    p=Path(filename)
    if not p.exists(): return set()
    return {norm(line.split(",")[0]) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()}

def save_csv(filename,rows):
    if not rows:return
    with open(filename,"w",newline="",encoding="utf-8-sig") as f:
        w=csv.DictWriter(f,fieldnames=sorted({k for r in rows for k in r}))
        w.writeheader();w.writerows(rows)

def run(args):
    out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
    now=datetime.now(ZoneInfo("America/New_York"))
    day=now.date().isoformat()
    audit={"started_at":now.isoformat(),"source_health":{},"tiles":[],"limitations":[
        "NJDEP 2015 Other pavement is NOT classified parking; buildings can appear in Other where LiDAR missing.",
        "Proxy space-equivalents are NOT measured parking stalls.",
        "No present-day parking layout, utility hosting, existing solar, ownership, flood or wetlands validation.",
        "PROP_LOC is an assessor address, not a USPS-verified delivery address."]}
    try: audit["source_health"]=check_services()
    except Exception as exc:
        audit["service_failure"]=str(exc)
        (out/f"{day}_audit.json").write_text(json.dumps(audit,indent=2))
        raise
    state_path=out/"state.json"
    state=json.loads(state_path.read_text()) if state_path.exists() else {}
    cursor=int(state.get("cursor",0))
    offsets=state.get("tile_offsets",{})
    seen_pins=set(state.get("seen_pins",[]))
    seen_addresses=set(state.get("seen_addresses",[]))
    exclusions=initial_exclusions(args.exclusions)
    grid=tiles()
    candidates=list(state.get("candidate_pool",[]))
    good=0
    for tick in range(args.tiles):
        tileid=(cursor+tick)%len(grid)
        area=grid[tileid]
        offset=int(offsets.get(str(tileid),0))
        record={"tile":tileid,"offset":offset}
        try:
            subset,total=query_features(PARCEL,area,
                where="PROP_CLASS IN ('4A','4B','4C','15A','15B','15C','15D') AND CALC_ACRE >= 2",
                fields="PAMS_PIN,GIS_PIN,PROP_CLASS,PROP_USE,PROP_LOC,MUN_NAME,COUNTY,CALC_ACRE",
                offset=offset,limit=args.per_tile)
            record["returned_parcels"]=len(subset)
            record["total_intersecting_parcels"]=total
            record["failed_pavement"]=0
            record["candidates"]=0
            for parcel in subset:
                attrs=parcel.get("properties",{})
                address=str(attrs.get("PROP_LOC") or "").strip()
                city=str(attrs.get("MUN_NAME") or "").strip()
                pin=str(attrs.get("PAMS_PIN") or attrs.get("GIS_PIN") or "").strip()
                key=norm(address+", "+city)
                if not address or not city or not re.match(r"^\d",address):continue
                if (pin and pin in seen_pins) or key in seen_addresses or norm(address) in exclusions:continue
                try:
                    pavement,num=query_features(PAVEMENT,shape(parcel["geometry"]).bounds,
                        where="ClassName = 'Other'",fields="OBJECTID,ClassName",limit=None,cap=5000)
                    p=pavement_proxy(parcel,pavement)
                except Exception as exc:
                    record["failed_pavement"]+=1
                    record.setdefault("sample_failures",[])
                    if len(record["sample_failures"])<3:record["sample_failures"].append(str(exc)[:260])
                    continue
                if p["other_pavement_proxy_equivalent_low"]<args.minimum_proxy: continue
                row={"address":address,"municipality":city,"county":attrs.get("COUNTY"),
                     "parcel_pin":pin,"tax_class":attrs.get("PROP_CLASS"),
                     "property_use":attrs.get("PROP_USE"),
                     "assessor_acres":attrs.get("CALC_ACRE"),"parking_spaces_verified":"UNKNOWN",
                     "hosting_capacity_mw":"UNKNOWN","existing_solar_status":"NOT CHECKED",
                     "address_status":"ASSESSOR ADDRESS — NOT VERIFIED",
                     "proxy_status":"2015 OTHER PAVEMENT — NOT PARKING STALL COUNT",
                     "parcel_source":PARCEL,"pavement_source":PAVEMENT,"observed_at":now.isoformat(),**p}
                candidates.append(row)
                record["candidates"]+=1
            if record["returned_parcels"] and record["failed_pavement"]==record["returned_parcels"]:
                raise RuntimeError("All pavement geometry fetches failed")
            offsets[str(tileid)] = 0 if offset+len(subset)>=total else offset+len(subset)
            good+=1
            record["status"]="ok"
        except Exception as exc:
            record["status"]="error"
            record["error"]=str(exc)[:500]
        audit["tiles"].append(record)
    # Incomplete tiles continue from saved offset when next reached, rather than skipping permanent backlogs.
    state["cursor"]=(cursor+args.tiles)%len(grid) if good else cursor
    state["tile_offsets"]=offsets
    unique={}
    for row in sorted(candidates,key=lambda r:r["largest_other_piece_acres"],reverse=True):
        key=norm(row["address"]+", "+row["municipality"])
        if key in unique:continue
        unique[key]=row
    chosen=list(unique.values())[:args.max_results]
    state["candidate_pool"]=list(unique.values())[args.max_results:]
    for row in chosen:
        seen_addresses.add(norm(row["address"]+", "+row["municipality"]))
        if row["parcel_pin"]:seen_pins.add(row["parcel_pin"])
    audit.update({"succeeded_tiles":good,"new_provisional_parcels":len(chosen),
                  "all_current_candidates":len(unique),"remaining_candidates_not_delivered":len(state["candidate_pool"]),
                  "next_grid_cursor":state["cursor"],
                  "output_type":"PROVISIONAL GIS PARCELS, not qualified solar-carport property leads"})
    (out/f"{day}_audit.json").write_text(json.dumps(audit,indent=2))
    if not good:raise RuntimeError("No live GIS tile succeeded; see dated audit")
    if chosen:
        save_csv(out/f"{day}_provisional_parcels.csv",chosen)
        (out/f"{day}_addresses_UNVERIFIED.txt").write_text(
            "\n".join(f"{r['address']}, {r['municipality']}, NJ [ZIP UNKNOWN]" for r in chosen)+"\n")
    state["seen_pins"]=sorted(seen_pins)
    state["seen_addresses"]=sorted(seen_addresses)
    state_path.write_text(json.dumps(state,indent=2))
    print(json.dumps({"tiles_succeeded":good,"new_provisional_parcels":len(chosen),
                       "warning":"No confirmed parking stall counts or buildable carport areas."}))

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--out",default="daily_reports")
    p.add_argument("--tiles",type=int,default=2)
    p.add_argument("--per-tile",type=int,default=12)
    p.add_argument("--max-results",type=int,default=20)
    p.add_argument("--minimum-proxy",type=int,default=100)
    p.add_argument("--exclusions",default="seed_excluded_addresses.txt")
    args=p.parse_args()
    run(args)

if __name__=="__main__":
    try:main()
    except Exception as exc:
        print("Live GIS run failed; no verified property conclusions:",str(exc),file=sys.stderr)
        sys.exit(2)
