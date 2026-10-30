"""Diagnose four NJ distributed-generation hosting-capacity map sources.

Public URLs only; emitted report is metadata, not utility confidential data.
"""
import json,requests,re,sys
from pathlib import Path
s=requests.Session()
s.headers.update({"User-Agent":"NJ-Solar-Carport-GIS-DueDiligence/1.0"})
sources={
"ACE_2026":"https://services3.arcgis.com/agWTKEK7X5K1Bx7o/ArcGIS/rest/services/PHI_Hosting_Capacity10_2_2026/FeatureServer/4",
"ORU_segmented":"https://services.arcgis.com/ciPnsNFi1JLWVjva/ArcGIS/rest/services/ORU_NodalHCV_Prod/FeatureServer/0",
"ORU_combined":"https://services.arcgis.com/ciPnsNFi1JLWVjva/ArcGIS/rest/services/IEDR_ORU/FeatureServer/10",
"ACE_prior":"https://services3.arcgis.com/agWTKEK7X5K1Bx7o/arcgis/rest/services/PHI_Hosting_Capacity_Public/FeatureServer/4",
}
def get(url,params={"f":"json"},timeout=17):
 try:
  r=s.get(url,params=params,timeout=timeout)
  if r.status_code>=400:return {"http":r.status_code,"error":r.text[:200]}
  if "json" not in r.headers.get("content-type","").lower():return {"http":r.status_code,"not_json":r.text[:130]}
  return r.json()
 except Exception as e:return {"error":str(e)[:210]}
report={"layers":{},"maps":{},"search":{}}
for key,url in sources.items():
 d=get(url)
 report["layers"][key]={"url":url,"error":d.get("error"),"http":d.get("http"),
    "id":d.get("id"),"name":d.get("name"),"geometryType":d.get("geometryType"),
    "fields":[{"name":f.get("name"),"alias":f.get("alias"),"type":f.get("type")} for f in d.get("fields",[])],
    "editingInfo":d.get("editingInfo")}
for key,id in {
"JCP_app":"d43cf2482a344e469eae6ca569403c24",
"JCP_older":"546e9834416b42aba00b30ce6f59cc5f",
"PSEG_older":"40cd14eeba9944ab82398e04bec5ab7a",
"ACE_older":"4ace7e2133ec4ecfb689f086669a5c8d"
}.items():
 item=get(f"https://www.arcgis.com/sharing/rest/content/items/{id}")
 dat=get(f"https://www.arcgis.com/sharing/rest/content/items/{id}/data")
 report["maps"][key]={"item":{k:item.get(k) for k in ("id","title","type","url","access","owner","modified","error")},"data_keys":list(dat.keys())[:22],
      "operationalLayers":[{"id":x.get("id"),"title":x.get("title"),"url":x.get("url"),"itemId":x.get("itemId")} for x in dat.get("operationalLayers",[])],
      "map":dat.get("map"),"data_error":dat.get("error")}
for key,url in {
"PSEG_web":"https://nj.pseg.com/saveenergyandmoney/solarandrenewableenergy/solarpowersustanibility",
"JCP_app_page":"https://firstenergycorp.maps.arcgis.com/apps/webappviewer/index.html?id=d43cf2482a344e469eae6ca569403c24"
}.items():
 try:
  r=s.get(url,timeout=15); txt=r.text
  found=re.findall(r"https?[^\s\"'<>]{8,180}(?:arcgis|FeatureServer|MapServer)[^\s\"'<>]{0,200}",txt,re.I)
  report["maps"][key]={"http":r.status_code,"url":r.url,"matched_urls":found[:15],"bytes":len(txt)}
 except Exception as e:report["maps"][key]={"error":str(e)[:210]}
for q in ['PSE&G solar suitability map','PSE&G hosting capacity New Jersey','JCP&L solar accommodation map','FirstEnergy New Jersey hosting capacity']:
 d=get("https://www.arcgis.com/sharing/rest/search",{"f":"json","q":q,"num":30},timeout=19)
 report["search"][q]=[{"id":x.get("id"),"title":x.get("title"),"type":x.get("type"),"url":x.get("url"),"modified":x.get("modified")} for x in d.get("results",[])[:12]]
Path("hosting_probe.json").write_text(json.dumps(report,indent=2))
print(json.dumps({k:{"status":v.get("http") or "ok","fields":[f["name"] for f in v.get("fields",[])]} for k,v in report["layers"].items()}))
