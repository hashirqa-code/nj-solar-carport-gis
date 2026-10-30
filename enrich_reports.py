"""Second-stage parking-specific cross-check and reproducible Excel workbook.
Parking geometry is sourced from OSM; NJDEP 'Other' is a broad pavement proxy.
The orthophoto is for human inspection, NOT an AI stall count.
"""
import csv
import io
import json
import math
import re
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape
import requests
from shapely.geometry import Polygon, shape
from shapely.ops import transform, unary_union
from pyproj import Transformer

from pipeline import ORTHO, METRIC, ACRE_M2, initial_exclusions, norm

OVERPASS = ("https://overpass.kumi.systems/api/interpreter",
            "https://overpass-api.de/api/interpreter")
SESSION = requests.Session()
SESSION.headers["User-Agent"]="NJ-Carport-Research/1.0 (public data; small geographic queries)"

_OSM_CACHE = {}
def osm_query(bounds):
    # Group nearby parcels into approximately 2.1 km OSM request tiles. This
    # avoids hammering public Overpass servers with one query per property.
    west,south,east,north = bounds
    grid_x=math.floor(((west+east)/2)*40)
    grid_y=math.floor(((south+north)/2)*40)
    key=(grid_x,grid_y)
    if key in _OSM_CACHE:return _OSM_CACHE[key]
    pad=.004
    west=grid_x/40
    east=(grid_x+1)/40
    south=grid_y/40
    north=(grid_y+1)/40
    b=f"{south-pad:.7f},{west-pad:.7f},{north+pad:.7f},{east+pad:.7f}"
    q=f'[out:json][timeout:20];(way["amenity"="parking"]({b});way["power"="generator"]["generator:source"="solar"]({b});way["power"="plant"]["plant:source"="solar"]({b});way["generator:source"="solar"]({b}););out geom;'
    errors=[]
    for endpoint in OVERPASS:
        try:
            r=SESSION.post(endpoint,data={"data":q},timeout=28)
            r.raise_for_status()
            d=r.json()
            if "elements" not in d:raise ValueError("No elements field")
            result=(d["elements"],endpoint,"OK")
            _OSM_CACHE[key]=result
            return result
        except (requests.RequestException,ValueError) as exc:
            errors.append(f"{endpoint}: {str(exc)[:110]}")
    result=([],"","ERROR: "+"; ".join(errors))
    _OSM_CACHE[key]=result
    return result

def way_polygon(element):
    pts=element.get("geometry",[])
    coords=[(x["lon"],x["lat"]) for x in pts if "lon" in x and "lat" in x]
    if len(coords)<4 or coords[0]!=coords[-1]:return None
    g=Polygon(coords)
    if not g.is_valid:g=g.buffer(0)
    return g if not g.is_empty else None

def positive_int(v):
    try:
        x=int(str(v).strip())
        return x if 0<x<100000 else None
    except (ValueError,TypeError):return None

def parking_evidence(parcel_geom, elements):
    parcel=transform(METRIC,parcel_geom)
    park_parts=[];capacity_counts=[];osm_ids=[];solar_ids=[]
    for e in elements:
        tags=e.get("tags",{})
        geom=way_polygon(e)
        if geom is None:continue
        metric=transform(METRIC,geom)
        overlap=metric.intersection(parcel)
        if overlap.is_empty or overlap.area<40:continue
        identifier=f"{e.get('type','way')}/{e.get('id','unknown')}"
        if tags.get("amenity")=="parking":
            # parking=multi-storey or underground cannot support carports
            typ=tags.get("parking","surface")
            if typ in ("multi-storey","underground","rooftop","garage","street_side"):continue
            if overlap.area<300:continue
            park_parts.append(overlap)
            osm_ids.append(identifier)
            n=positive_int(tags.get("capacity"))
            if n:capacity_counts.append(n)
        if tags.get("generator:source")=="solar" or tags.get("plant:source")=="solar":
            solar_ids.append(identifier)
    g=unary_union(park_parts) if park_parts else Polygon()
    comps=([g] if g.geom_type=="Polygon" else list(g.geoms) if hasattr(g,"geoms") else [])
    return {"osm_surface_parking_acres":round(g.area/ACRE_M2,3),
            "osm_largest_parking_polygon_acres":round(max((p.area for p in comps),default=0)/ACRE_M2,3),
            "osm_parking_capacity_published":sum(capacity_counts) if capacity_counts else "",
            "osm_parking_feature_ids":",".join(osm_ids),
            "osm_solar_feature_ids":",".join(solar_ids),
            "osm_solar_warning":"OSM SOLAR FEATURE INTERSECTS PARCEL" if solar_ids else "NOT ESTABLISHED (OSM NOT EXHAUSTIVE)",
            "parking_evidence_level":("OSM_TAGGED_PARKING_POLYGON" if park_parts else "UNVERIFIED_NJDEP_OTHER_PAVEMENT"),
            "parking_stalls_verified":"NO",
            "parking_count_note":("OSM volunteered capacity, unverified" if capacity_counts else "UNKNOWN — no validated stall inventory")}

def aerial_export(row, outdir, number):
    lat=float(row["parcel_lat"]);lon=float(row["parcel_lon"])
    # One 2020 ortho reference per highest-ranked prospect; historical imagery.
    d=.0028
    bbox=f"{lon-d},{lat-d},{lon+d},{lat+d}"
    p={"bbox":bbox,"bboxSR":"4326","imageSR":"3857","size":"1100,1100","format":"jpg",
       "f":"image","transparent":"false"}
    try:
        r=SESSION.get(ORTHO+"/export",params=p,timeout=35)
        r.raise_for_status()
        if not r.headers.get("Content-Type","").lower().startswith("image/"):
            raise ValueError("Imagery service did not return an image")
        if len(r.content)<10000:raise ValueError("Image too small/empty")
        path=outdir/f"site_{number:02d}.jpg"
        path.write_bytes(r.content)
        return str(path),"2020 NJ ORTHO OBTAINED — HUMAN REVIEW REQUIRED"
    except (requests.RequestException,ValueError) as exc:
        return "",f"IMAGERY FETCH FAILED: {str(exc)[:85]}"

def cell(v,ref,style=0):
    fmt=f' s="{style}"' if style else ""
    if isinstance(v,bool):v=str(v)
    if v is None:v=""
    if isinstance(v,(float,int)) and math.isfinite(float(v)):
        return f'<c r="{ref}"{fmt}><v>{v}</v></c>'
    v=escape(str(v))
    return f'<c r="{ref}" t="inlineStr"{fmt}><is><t xml:space="preserve">{v}</t></is></c>'

def excel_col(i):
    s=""
    while i:
        i,r=divmod(i-1,26);s=chr(65+r)+s
    return s

def xlsx_sheet(rows,widths,head=True):
    columns="".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i,w in enumerate(widths,1))
    rr=[]
    for ri,values in enumerate(rows,1):
        cells=[]
        for ci,v in enumerate(values,1):
            cells.append(cell(v,f"{excel_col(ci)}{ri}",1 if head and ri==1 else 2 if ri%2==0 else 0))
        rr.append(f'<row r="{ri}">{"".join(cells)}</row>')
    auto=f'<autoFilter ref="A1:{excel_col(len(rows[0]))}{len(rows)}"/>' if head and len(rows)>1 else ""
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><sheetFormatPr defaultRowHeight="17"/><cols>{columns}</cols><sheetData>{"".join(rr)}</sheetData>{auto}<pageMargins left=".3" right=".3" top=".5" bottom=".5" header=".2" footer=".2"/></worksheet>'

def write_xlsx(path, tabs):
    styles='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><fonts count="3"><font><sz val="10"/><name val="Aptos"/></font><font><b/><sz val="10"/><color rgb="FFFFFFFF"/><name val="Aptos"/></font><font><sz val="10"/><name val="Aptos"/></font></fonts><fills count="4"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF163A4D"/></patternFill></fill><fill><patternFill patternType="solid"><fgColor rgb="FFF0F5F7"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1" applyFont="1"/><xf numFmtId="0" fontId="2" fillId="3" borderId="0" xfId="0" applyFill="1"/></cellXfs></styleSheet>'''
    wb='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'''+''.join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i,(name,_,_) in enumerate(tabs,1))+'</sheets></workbook>'
    rel='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'''+''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,len(tabs)+1))+f'<Relationship Id="rId{len(tabs)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>'
    types='''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'''+''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1,len(tabs)+1))+'</Types>'
    with zipfile.ZipFile(path,"w",compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml",types)
        z.writestr("_rels/.rels",'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>''')
        z.writestr("xl/workbook.xml",wb)
        z.writestr("xl/_rels/workbook.xml.rels",rel)
        z.writestr("xl/styles.xml",styles)
        for i,(_,rows,widths) in enumerate(tabs,1):
            z.writestr(f"xl/worksheets/sheet{i}.xml",xlsx_sheet(rows,widths))

FIELDS=[
"Rank","Assessor Street Address","Municipality","County","Property Tax Class","Use Code",
"Parcel Acres","2015 Other Impervious Acres","Largest Other Impervious Piece Acres",
"OSM-tagged Surface Parking Acres","Largest Mapped Parking Shape Acres",
"OSM Published Capacity (Unverified)","Verified Parking Stall Count",
"Parking Evidence","Solar Warning","2020 Aerial Image Status","Aerial Image Filename",
"Utility Hosting MW","Property Ownership — USER TO VERIFY","Candidate Priority",
"Source NJGIN Parcel","Source NJDEP Pavement","OSM Parking Features","OSM Solar Features",
"Parcel ID","Coordinates Lat","Coordinates Lon","Notes / Validation Needed"]

def to_workbook_row(r,i):
    acres=float(r.get("osm_surface_parking_acres") or 0)
    pavement=float(r.get("largest_other_piece_acres") or 0)
    solar=bool(r.get("osm_solar_feature_ids"))
    score=round(10*acres+min(pavement,10)*1.5+(5 if r.get("osm_parking_capacity_published") else 0)-(10 if solar else 0),1)
    r["priority_index"]=score
    out=[i,r.get("address",""),r.get("municipality",""),r.get("county",""),r.get("tax_class",""),r.get("property_use",""),
        r.get("assessor_acres",""),r.get("candidate_other_acres",""),r.get("largest_other_piece_acres",""),
        acres if acres else "",r.get("osm_largest_parking_polygon_acres","") or "",r.get("osm_parking_capacity_published",""),
        "UNKNOWN",r.get("parking_evidence_level",""),r.get("osm_solar_warning",""),r.get("aerial_image_status",""),r.get("aerial_image_filename",""),
        "UNKNOWN","","A — OSM parking mapped" if acres>=1 and not solar else "B — GIS lead, review",
        r.get("parcel_source",""),r.get("pavement_source",""),r.get("osm_parking_feature_ids",""),r.get("osm_solar_feature_ids",""),
        r.get("parcel_pin",""),r.get("parcel_lat",""),r.get("parcel_lon",""),
        "Do not rely on 2015 pavement as parking; verify current stripes, roof/road/truck use, site ownership, solar plans and utility"]
    return out

def run(report_dir=Path("daily_reports"),max_imagery=5):
    report_dir=Path(report_dir)
    audits=sorted(report_dir.glob("*_audit.json"))
    if not audits:raise RuntimeError("No live GIS audit available")
    day=audits[-1].name[:10]
    source=report_dir/f"{day}_provisional_parcels.csv"
    if not source.exists():raise RuntimeError(f"No GIS candidate CSV for {day}")
    with source.open(encoding="utf-8-sig",newline="") as f:
        rows=list(csv.DictReader(f))
    seen=set();enriched=[];failures=[]
    for r in rows:
        key=norm(r.get("address"))+norm(r.get("municipality"))
        if key in seen:continue
        seen.add(key)
        geo=r.get("parcel_polygon_geojson","")
        if not geo:
            r.update({"parking_evidence_level":"UNAVAILABLE_NO_PARCEL_GEOMETRY","osm_surface_parking_acres":0,
                       "osm_solar_warning":"UNKNOWN","osm_status":"NOT QUERIED"})
        else:
            parcel=shape(json.loads(geo))
            elements,endpoint,status=osm_query(parcel.bounds)
            if status=="OK":r.update(parking_evidence(parcel,elements))
            else:
                r.update({"parking_evidence_level":"OSM_UNAVAILABLE","osm_surface_parking_acres":0,
                          "osm_solar_warning":"UNKNOWN","osm_status":status})
                failures.append(status)
            r["osm_status"]=status
            r["osm_endpoint"]=endpoint
        r["aerial_image_status"]="NOT YET CHECKED"
        r["aerial_image_filename"]=""
        enriched.append(r)
    enriched.sort(key=lambda x:(float(x.get("osm_surface_parking_acres") or 0),
                                float(x.get("largest_other_piece_acres") or 0)),reverse=True)
    aerial_dir=report_dir/"aerial"/day
    aerial_dir.mkdir(parents=True,exist_ok=True)
    for i,r in enumerate(enriched[:max_imagery],1):
        if r.get("parcel_lat") and r.get("parcel_lon"):
            fn,status=aerial_export(r,aerial_dir,i)
            r["aerial_image_filename"]=fn
            r["aerial_image_status"]=status
    audit=json.loads(audits[-1].read_text(encoding="utf-8"))
    meta={"as_of":datetime.now().astimezone().isoformat(),"gis_date":day,"candidate_count":len(enriched),
          "osm_query_failures":len(failures),"osm_mapped_parking":sum(bool(float(x.get("osm_surface_parking_acres") or 0)) for x in enriched),
          "aerial_previews":sum(x.get("aerial_image_filename","")!="" for x in enriched),
          "parking_stall_counts_independently_verified":0,
          "notes":"Workbook is a screening list. Ownership and individual stall counts not verified."}
    (report_dir/f"{day}_enrichment_audit.json").write_text(json.dumps(meta,indent=2))
    with (report_dir/f"{day}_enriched_candidates.csv").open("w",encoding="utf-8-sig",newline="") as f:
        serial=[{k:v for k,v in x.items() if k!="parcel_polygon_geojson"} for x in enriched]
        writer=csv.DictWriter(f,fieldnames=sorted({k for x in serial for k in x}))
        writer.writeheader();writer.writerows(serial)
    widths=[8,26,19,16,14,12,12,18,19,17,17,14,15,24,22,22,27,14,20,22,30,30,23,22,18,14,14,54]
    sheet=[FIELDS]+[to_workbook_row(r,i) for i,r in enumerate(enriched,1)]
    methods=[
        ["Field","Explanation"],
        ["Report date",day],
        ["Public source 1","NJGIN MOD-IV tax parcels, spatial geometry (live)"],
        ["Public source 2","NJDEP Other impervious 2015 — not a parking layer"],
        ["OSM parking evidence","OSM amenity=parking tagged closed ways, clipped to parcel footprint"],
        ["OSM capacity","Volunteered open map tag; not verified stall count"],
        ["Aerial previews","NJ official 2020 orthophoto; imagery only, no model-verified stall count"],
        ["Existing solar","OSM tags can FLAG solar; absence does not establish no existing panels"],
        ["Utility hosting capacity","Unknown until verified at exact feeder/point"],
        ["Ownership","Intentionally blank for user's separate verification"],
        ["First-stage results",len(enriched)],
        ["OSM-backed parking polygons",meta["osm_mapped_parking"]],
        ["Images actually exported",meta["aerial_previews"]],
        ["OSM request failures",meta["osm_query_failures"]],
        ["GIS tiles succeeded",audit.get("succeeded_tiles","")],
        ["Proxy parking-space numbers","NOT USED as real parking capacity. Avoid deriving spaces from non-parking pavement."],
        ["Main GIS source",str(audit.get("source_health",{}).get("NJGIN parcels",{}).get("url",""))],
        ["State map",ORTHO],
        ["Quality limitation","The workbook is a candidate shortlist for manual review, not 20 qualified carport development sites"]
    ]
    path=report_dir/f"{day}_NJ_solar_carport_prospects.xlsx"
    write_xlsx(path,[("Solar Carport Leads",sheet,widths),("Method and Audit",methods,[30,105])])
    print(json.dumps(meta))
    print(str(path))

if __name__=="__main__":
    try:run()
    except Exception as exc:
        print(f"Enrichment failed: {exc}",file=sys.stderr)
        sys.exit(2)
