"""Solar *generation* hosting-capacity screen for NJ carport prospects.

Queries public ArcGIS feeder/transformer maps from four NJ electric utilities.
Closest mapped features are spatial indicators, NOT confirmed serving feeders,
available interconnection offers, queue reservations, or approvals.
"""
import csv,json,math,re,sys,time
from datetime import datetime,timezone
from pathlib import Path
from zoneinfo import ZoneInfo
import requests
from pyproj import Transformer
from shapely.geometry import Point,LineString
from shapely.ops import transform
from parking_estimates import estimate_solar_mw

UA="Promittens NJ solar siting research (public ArcGIS hosting map analysis)"
ACE="https://services3.arcgis.com/agWTKEK7X5K1Bx7o/ArcGIS/rest/services/PHI_Hosting_Capacity10_2_2026/FeatureServer/4"
ORU="https://services.arcgis.com/ciPnsNFi1JLWVjva/ArcGIS/rest/services/ORU_NodalHCV_Prod/FeatureServer/0"
PSEG1="https://services.arcgis.com/yHb9HdkiNl1PZaOr/arcgis/rest/services/NM_HCM_ServicePoints/FeatureServer/1"
PSEG0="https://services.arcgis.com/yHb9HdkiNl1PZaOr/arcgis/rest/services/NM_HCM_ServicePoints/FeatureServer/0"
JCPL="https://services9.arcgis.com/QhIvHlqYDjdoPWZG/arcgis/rest/services/Solar_Accommodation_Limit_2020/FeatureServer/0"
SOURCES={
 "ACE":{"name":"Atlantic City Electric","layers":[ACE],"bounds":(-75.8,38.4,-73.9,40.4),"radius":450},
 "ORU":{"name":"Orange & Rockland","layers":[ORU],"bounds":(-75.1,40.7,-73.7,41.9),"radius":450},
 "PSEG":{"name":"PSE&G","layers":[PSEG1,PSEG0],"bounds":(-75.5,39.3,-73.5,41.4),"radius":400},
 "JCPL":{"name":"JCP&L","layers":[JCPL],"bounds":(-75.7,39.0,-73.7,41.6),"radius":400}
}
METRIC=Transformer.from_crs(4326,5070,always_xy=True).transform
SESSION=requests.Session();SESSION.headers["User-Agent"]=UA

def value(v):
 try:
  n=float(v)
  return n if math.isfinite(n) else None
 except (ValueError,TypeError):return None

def date_ms(v):
 n=value(v)
 return datetime.fromtimestamp(n/1000,timezone.utc).date().isoformat() if n and n>1e12 else ""

def arcgeo(geometry):
 if "x" in geometry and "y" in geometry:return Point(geometry["x"],geometry["y"])
 if geometry.get("paths"):
  segs=[LineString(p) for p in geometry["paths"] if len(p)>=2]
  if segs:
   from shapely.geometry import MultiLineString
   return segs[0] if len(segs)==1 else MultiLineString(segs)
 return None

def jcp_capacity(attrs):
 """Original JCP 'Remaining' category text is *not* exact capacity."""
 label=str(attrs.get("Remaining") or "")
 compact=label.lower().replace(",","")
 nums=[float(v) for v in re.findall(r"\d+(?:\.\d+)?",compact)]
 factor=1.0 if "mw" in compact and "kw" not in compact else .001
 if not nums:return None,label
 if "less than" in compact or "<" in compact:
  return 0.0,label # screening lower bound, NOT zero verified
 if "greater than" in compact or "more than" in compact or ">" in compact:
  return nums[0]*factor,label
 if len(nums)>=2:
  return min(nums[:2])*factor,label
 return None,label # a lone unqualified figure is ambiguous

def parse_capacity(utility,attrs):
 if utility=="ACE":
  n=value(attrs.get("Allowable_PV_kW"))
  return (max(0,n/1000) if n is not None else None,
          str(attrs.get("FeederID") or ""),str(attrs.get("Substation") or ""),
          date_ms(attrs.get("Last_Updated") or attrs.get("UpdateDate")),
          "MWac proxy converted from utility kW field; verify published rating basis",
          value(attrs.get("Total_Pending_Gen_kW")))
 if utility=="ORU":
  n=value(attrs.get("PV_SECTION"))
  notes=str(attrs.get("NOTES") or "")
  if "no capacity available" in notes.lower() or "no capacity is available" in notes.lower():
   n=0.
  return (max(0,n) if n is not None else None,str(attrs.get("CIRCUIT") or ""),
          str(attrs.get("SUBSTATION") or ""),date_ms(attrs.get("HC_REFESH_DATE")),
          "Section-level PV hosting MW; queue and upstream constraints separate",
          value(attrs.get("QUEUED_DER")))
 if utility=="PSEG":
  c=value(attrs.get("circuitavailability"))
  st=value(attrs.get("stationavailability"))
  disp=value(attrs.get("TotalAvailabilitySymbol"))
  # This map displays the limiting (circuit AND station) availability.
  available=disp if disp is not None else min(c,st) if c is not None and st is not None else None
  return (max(0,available/1000) if available is not None else None,
          str(attrs.get("BASE_CIRCUITID") or ""),str(attrs.get("stationname") or ""),
          "","PSE&G service-point availability (kW) with feeder and station limits",
          value(attrs.get("PendingSolar")))
 if utility=="JCPL":
  cap,label=jcp_capacity(attrs)
  return (cap,"", "", "2026-06-30",
          "JCP&L transformer map category: "+label+"; numeric field is CONSERVATIVE category lower bound only",None)
 return None,"","","","",None

def fetch_nearby(layer,lat,lon,radius_m=450):
 # 0.012deg lat is approximately 1330m, adequate for a 450m radius.
 latdeg=radius_m/111320*1.15
 londeg=radius_m/(111320*max(0.25,math.cos(math.radians(lat))))*1.15
 geom={"xmin":lon-londeg,"ymin":lat-latdeg,"xmax":lon+londeg,"ymax":lat+latdeg,
       "spatialReference":{"wkid":4326}}
 params={"f":"json","where":"1=1","geometry":json.dumps(geom),
         "geometryType":"esriGeometryEnvelope","spatialRel":"esriSpatialRelIntersects",
         "inSR":4326,"outSR":4326,"outFields":"*","returnGeometry":"true",
         "resultRecordCount":500}
 r=SESSION.post(layer+"/query",data=params,timeout=(6,15))
 r.raise_for_status()
 data=r.json()
 if "error" in data:raise RuntimeError(str(data["error"])[:160])
 if data.get("exceededTransferLimit"):raise RuntimeError("Truncated GIS feature list")
 return data.get("features",[])

def get_candidates(row):
 lat=value(row.get("parcel_lat"));lon=value(row.get("parcel_lon"))
 if lat is None or lon is None:return [],["No valid parcel point coordinates"]
 target=transform(METRIC,Point(lon,lat))
 matches=[];failures=[]
 for utility,src in SOURCES.items():
  x1,y1,x2,y2=src["bounds"]
  if not (x1<=lon<=x2 and y1<=lat<=y2):continue
  for layer in src["layers"]:
   try:
    features=fetch_nearby(layer,lat,lon,src["radius"])
   except Exception as e:
    failures.append(f"{utility}: {str(e)[:160]}")
    continue
   for f in features:
    g=arcgeo(f.get("geometry") or {})
    if g is None:continue
    try:distance=transform(METRIC,g).distance(target)
    except Exception:continue
    if distance>src["radius"]:continue
    attrs=f.get("attributes") or {}
    mw,feeder,station,refresh,detail,queued=parse_capacity(utility,attrs)
    if mw is None:continue
    matches.append({"utility":utility,"utility_name":src["name"],
      "hosting_screen_mw":round(mw,4),"distance_m":round(distance),
      "feeder":feeder,"station":station,"map_refresh":refresh,
      "evidence":detail,"queued_raw":queued,"layer":layer,
      "feature_id":str(attrs.get("OBJECTID") or attrs.get("OBJECTID_1") or attrs.get("FID") or ""),
      "geometry_kind":g.geom_type})
 return matches,failures

def rank(row, matches, failures):
 solar=estimate_solar_mw(row)
 need=solar["solar_mwac_likely_inverter_only"]
 result={
  "hosting_utility":"UNKNOWN","hosting_map_mw":"", "hosting_map_distance_m":"",
  "hosting_feeder":"", "hosting_substation":"", "hosting_date":"",
  "hosting_score":"NOT ASSESSED","hosting_match_method":"NO CONFIRMED SERVING FEEDER",
  "hosting_map_source":"", "hosting_queue_raw":"",
  "hosting_capacity_to_project_ratio":"",
  "hosting_caveats":"Map screening only; connection point/feeder and upgrades must be confirmed",
  "hosting_check_failures":"; ".join(failures)[:450],"solar_mwac_likely_for_comparison":need
 }
 if not matches:
  result["hosting_score"]="UNKNOWN — NO MATCH" if not failures else "UNKNOWN — MAP ERROR/NO MATCH"
  return result
 # Choose nearest point/feeder first; a farther strong circuit is NOT a guaranteed alternative.
 match=min(matches,key=lambda m:(m["distance_m"],-m["hosting_screen_mw"]))
 equiv=[m for m in matches if m["utility"]!=match["utility"] and m["distance_m"]<=max(200,match["distance_m"]+100)]
 if equiv:
  result["hosting_caveats"]+="; nearby features from multiple utilities—serving provider AMBIGUOUS"
 result.update({
  "hosting_utility":match["utility"],
  "hosting_map_mw":match["hosting_screen_mw"],
  "hosting_map_distance_m":match["distance_m"],
  "hosting_feeder":match["feeder"],
  "hosting_substation":match["station"],
  "hosting_date":match["map_refresh"],
  "hosting_match_method":"NEAREST FEATURE ONLY — SERVICE NOT VERIFIED",
  "hosting_map_source":match["layer"],
  "hosting_queue_raw":match["queued_raw"] if match["queued_raw"] is not None else "",
  "hosting_caveats":result["hosting_caveats"]+"; "+match["evidence"],
 })
 if need>0:
  ratio=match["hosting_screen_mw"]/need
  result["hosting_capacity_to_project_ratio"]=round(ratio,2)
  if ratio>=1.5 and match["distance_m"]<=300 and not equiv:rating="A — HIGHER SCREENED HEADROOM"
  elif ratio>=1 and not equiv:rating="B — POSSIBLE HEADROOM"
  else:rating="C — LESS THAN TARGET / AMBIGUOUS"
  result["hosting_score"]=rating
 else:result["hosting_score"]="UNKNOWN — NO PROJECT SIZE"
 if match["utility"]=="JCPL":
  result["hosting_score"]="CATEGORY-BASED — "+result["hosting_score"]
  result["hosting_caveats"]+="; capacity is a category lower bound, NOT exact MW."
 return result

def run(folder="daily_reports"):
 root=Path(folder)
 day=datetime.now(ZoneInfo("America/New_York")).date().isoformat()
 file=root/f"{day}_provisional_parcels.csv"
 if not file.exists():raise RuntimeError("No current GIS parcel file; hosting matching not run")
 with file.open(encoding="utf-8-sig",newline="") as f:rows=list(csv.DictReader(f))
 out=[];details=[];start=time.monotonic()
 for row in rows:
  matches,errors=get_candidates(row)
  ranked=rank(row,matches,errors)
  out.append({**row,**ranked})
  for m in matches:details.append({"parcel_pin":row.get("parcel_pin"),"address":row.get("address"),**m})
 path=root/f"{day}_hosting_enriched.csv"
 if not out:
  # Write a header even for a zero-candidate day.
  out=[{**{k:"" for k in ["address","municipality","parcel_pin","parcel_lat","parcel_lon"]},**rank({},
    [],["No new GIS candidates"])}]
  # do not manufacture a property row
  out=[]
 keys=sorted({key for row in out for key in row})
 if keys:
  with path.open("w",encoding="utf-8-sig",newline="") as f:
   w=csv.DictWriter(f,fieldnames=keys);w.writeheader();w.writerows(out)
 report={"as_of":datetime.now(ZoneInfo("America/New_York")).isoformat(),
         "property_count":len(rows),"matched":sum(bool(x.get("hosting_utility") not in ("UNKNOWN","")) for x in out),
         "map_errors":sum(bool(x.get("hosting_check_failures")) for x in out),
         "method":"NEAREST PUBLIC MAP FEATURE WITHIN 400-450M; NOT VERIFIED FEEDER",
         "sources":{x:src["layers"] for x,src in SOURCES.items()},
         "capacity_reference":"PV GENERATION (not EV load). Compare approximate MWac, not MWdc.",
         "seconds":round(time.monotonic()-start,1)}
 (root/f"{day}_hosting_audit.json").write_text(json.dumps(report,indent=2))
 if details:
  with (root/f"{day}_hosting_map_matches.csv").open("w",encoding="utf-8-sig",newline="") as f:
   w=csv.DictWriter(f,fieldnames=sorted(set().union(*(x.keys() for x in details))))
   w.writeheader();w.writerows(details)
 print(json.dumps(report))

if __name__=="__main__":
 try:run()
 except Exception as e:
  print("Hosting screen unavailable:",e,file=sys.stderr);sys.exit(2)
