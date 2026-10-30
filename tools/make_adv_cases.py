import json, copy, sys
from pathlib import Path
import jsonschema
REPO = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
OUT = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("tests/cases_adv")
OUT.mkdir(parents=True, exist_ok=True)
schema = json.load(open(REPO / "chameleon_design_schema_v0.9.json"))
W="rgba(255,255,255,1)"; OR="rgba(232,106,58,1)"; PL="rgba(43,27,46,1)"; GOLD="rgba(240,178,66,1)"
def T(id,x,y,w,h,c,s,z=5,fam="Solstice Sans",**k):
    d={"id":id,"type":"text","x":x,"y":y,"width":w,"height":h,"z_index":z,"content":c,"font_family":fam,
       "font_size":s,"color":k.pop("color",W),"text_align":k.pop("text_align","center")}; d.update(k); return d
def I(id,x,y,w,h,a,z=3,fit="contain",**k):
    d={"id":id,"type":"image","x":x,"y":y,"width":w,"height":h,"z_index":z,"asset_id":a,"fit":fit}; d.update(k); return d
def S(id,x,y,w,h,z=2,shape="rectangle",fill=OR,**k):
    d={"id":id,"type":"shape","x":x,"y":y,"width":w,"height":h,"z_index":z,"shape_type":shape,"fill_color":fill}; d.update(k); return d
BG=lambda w,h: I("bg",0,0,w,h,"solstice_bg_gradient.png",z=0,fit="cover")
LOGO="solstice_logo_lockup.png"; BOT="solstice_bottle.png"
samples={json.load(open(f))["task_id"]:json.load(open(f))["source"] for f in sorted((REPO/"input").glob("*.json"))}
cases={}
# a1 nearby: core square -> IG portrait
cases["near_core_sq_to_portrait"]=(samples["core_01"],(1080,1350))
# a2 nearby: fb-link style -> 1280x720
fb={"canvas":{"width":1200,"height":628},"elements":[BG(1200,628),
  I("logo",60,40,240,80,LOGO,z=4),
  T("headline",60,170,620,180,"Chase the Light This Summer",60,fam="Solstice Serif",font_weight="bold",text_align="left"),
  T("sub",60,370,620,80,"Botanical sparkling infusions, crafted for golden hour.",26,text_align="left"),
  S("cta_bg",60,480,300,80,z=3,corner_radius=40,group_id="cta"),
  T("cta_label",60,500,300,40,"Shop now",26,font_weight="bold",group_id="cta"),
  I("product",740,60,420,520,BOT,z=3)]}
cases["near_fb_to_yt"]=(fb,(1280,720))
# b square with many elements -> billboard 970x250
els=[BG(1080,1080),I("logo",40,30,240,80,LOGO,z=4),
  S("badge_bg",800,40,240,56,z=3,corner_radius=28,group_id="b"),T("badge_t",800,52,240,32,"NEW FLAVOR",18,font_weight="bold",group_id="b"),
  I("product",340,140,400,400,BOT),
  T("headline",90,560,900,120,"Six Flavors of Golden Hour",64,fam="Solstice Serif",font_weight="bold"),
  T("sub",140,690,800,70,"Small-batch, botanical, alcohol-free. Bottled at sunset.",24)]
for i,(n,c) in enumerate([("f1","Blood Orange"),("f2","Wild Honey"),("f3","Smoked Rosemary"),("f4","Yuzu Mint"),("f5","Fig Leaf"),("f6","Pink Pepper")]):
  els.append(S(n+"_bg",60+i*162,790,150,50,z=3,corner_radius=25,fill=PL if i%2 else OR,group_id=n))
  els.append(T(n+"_t",60+i*162,803,150,26,c,15,font_weight="bold",group_id=n))
els+= [S("cta_bg",330,880,420,90,z=3,corner_radius=45,group_id="cta"),T("cta_label",330,905,420,44,"Find Your Flavor",24,font_weight="bold",group_id="cta"),
  T("legal",60,1030,960,30,"Alcohol-free. Contains natural flavors. solstice.com",13,color="rgba(255,255,255,0.6)")]
cases["many_sq_to_billboard"]=({"canvas":{"width":1080,"height":1080},"elements":els},(970,250))
# c many long text -> 336x280
lorem=["Every bottle starts with a single question: what does the last hour of sunlight taste like? We answer it with honey, citrus and herbs.",
 "Our blenders forage rosemary from the hills behind the distillery and press blood oranges within hours of picking them from the grove.",
 "Nothing artificial ever touches the bottle. No syrups, no concentrates, no shortcuts, just slow infusions that take eleven days to finish.",
 "Each batch is numbered by hand and tasted by the whole team before it ships, which is why some weeks we simply release nothing at all.",
 "Find us at farmers markets across the coast every Saturday morning, or order a mixed case online with free delivery on orders over forty.",
 "Subscribers get first access to seasonal releases, invitations to rooftop tastings, and a handwritten note from the blender every quarter."]
els=[S("bg_rect",0,0,1080,1350,z=0,fill=PL),T("title",60,50,960,140,"Notes From the Distillery: A Long Letter About Light",54,fam="Solstice Serif",font_weight="bold",text_align="left")]
for i,t in enumerate(lorem): els.append(T(f"para{i}",60,220+i*170,960,150,t,28,text_align="left",color="rgba(250,240,225,1)"))
cases["longcopy_to_336x280"]=({"canvas":{"width":1080,"height":1350},"elements":els},(336,280))
# d mixed image proportions -> story
mi={"canvas":{"width":1920,"height":1080},"elements":[S("bg_rect",0,0,1920,1080,z=0,fill="rgba(250,240,225,1)"),
  I("strip",80,60,1200,300,"solstice_bg_gradient.png",z=2,fit="fill"),
  I("square",80,420,520,500,BOT,z=3),
  I("tall_missing",1400,60,420,960,"lifestyle_portrait_7x16.png",z=3),
  I("logo",680,440,600,200,LOGO,z=3),
  T("headline",680,680,640,160,"One Summer, Four Shapes",64,fam="Solstice Serif",font_weight="bold",color=PL,text_align="left"),
  T("caption",680,860,640,80,"Strip, square, tower and lockup must all survive.",26,color=PL,text_align="left")]}
cases["mixed_aspects_to_story"]=(mi,(1080,1920))
# e tiny logo + product -> half page
tl={"canvas":{"width":1080,"height":1080},"elements":[BG(1080,1080),
  I("logo",960,1020,90,30,LOGO,z=4),
  I("product",140,100,800,620,BOT,z=3),
  I("product2",780,560,240,240,BOT,z=4),
  T("headline",90,760,900,120,"The Bottle Is the Hero",64,fam="Solstice Serif",font_weight="bold"),
  T("sub",140,890,800,60,"Logo is a 90x30 footnote in the source.",24)]}
cases["tiny_logo_to_halfpage"]=(tl,(300,600))
# f text over decor shape + text on product art
ta={"canvas":{"width":1080,"height":1080},"elements":[S("bg_rect",0,0,1080,1080,z=0,fill="rgba(250,240,225,1)"),
  I("art",200,80,700,700,BOT,z=1),
  T("headline",120,300,840,200,"BOLD OVER THE BOTTLE",88,z=5,fam="Solstice Serif",font_weight="bold",color=PL),
  S("blob",620,760,520,360,z=2,shape="ellipse",fill=PL),
  T("blob_text",660,860,380,120,"Text sits on a dark blob that is NOT grouped",30,z=5,color=W,text_align="left"),
  T("dark_note",60,860,520,120,"Dark text on cream, left of the blob.",32,color=PL,text_align="left")]}
cases["text_on_art_and_blob_to_yt"]=(ta,(1280,720))
# g collage 3 overlapping images, z-layered, no group
co={"canvas":{"width":1080,"height":1080},"elements":[BG(1080,1080),
  I("c1",100,140,500,500,BOT,z=2,fit="cover"),
  I("c2",300,300,500,500,BOT,z=3,fit="cover"),
  I("c3",500,460,500,500,BOT,z=4,fit="cover"),
  T("headline",60,40,960,90,"Layered Collage",64,z=6,fam="Solstice Serif",font_weight="bold"),
  T("cap",60,980,400,60,"Three overlapping frames",24,z=6,text_align="left")]}
cases["collage_overlap_to_fb"]=(co,(1200,628))
# h rotated elements
ro={"canvas":{"width":1080,"height":1080},"elements":[BG(1080,1080),
  T("tilted",200,120,680,120,"Tilted Headline Alone",64,fam="Solstice Serif",font_weight="bold",rotation=-15),
  I("rot_img",340,330,400,400,BOT,z=3,rotation=30),
  T("vertical",-250,510,600,60,"VERTICAL SIDE LABEL",36,font_weight="bold",rotation=90),
  T("sub",140,820,800,60,"Three rotations: -15, 30, 90 degrees.",28),
  S("cta_bg",330,920,420,90,z=3,corner_radius=45,group_id="cta"),T("cta_label",330,945,420,44,"Rotate Me",24,font_weight="bold",group_id="cta")]}
cases["rotations_to_skyscraper"]=(ro,(160,600))
cases["rotations_to_leader"]=(ro,(728,90))
# i missing main product + watermark sample
mm=copy.deepcopy(samples["core_01"]); 
for e in mm["elements"]:
  if e["id"]=="product": e["asset_id"]="solstice_bottle_v2_missing.png"
cases["missing_main_product_to_story"]=(mm,(1080,1920))
# j extremes
cases["advanced_to_320x50"]=(samples["advanced_01"],(320,50))
els=[BG(1080,1920),I("logo",390,40,300,100,LOGO,z=4)]
for i in range(23):
  r,c=divmod(i,2)
  if i==22: els.append(T("legal",60,1860,960,40,"All 25 elements must remain legible in landscape. Terms apply.",14)); break
  if i%3==0: els.append(I(f"img{i}",80+c*480,180+r*150,140,140,BOT,z=3))
  else: els.append(T(f"t{i}",80+c*480+(160 if i%3==0 else 0),180+r*150,440,130,f"Item {i}: a reasonably long line of descriptive copy",26,text_align="left"))
cases["tall25_to_1920x1080"]=({"canvas":{"width":1080,"height":1920},"elements":els},(1920,1080))
# k structural edge cases -> A4 at 300dpi-ish 2480x3508
ed={"canvas":{"width":1080,"height":1080},"elements":[
  S("bg_shape",0,0,1080,1080,z=0,shape="rectangle",fill=PL),
  I("bg_grad",0,0,1080,1080,"solstice_bg_gradient.png",z=0,fit="cover",opacity=0.5),
  S("zero_w",500,100,0,80,z=3,fill=OR),
  T("zero_h",100,100,300,0,"zero height box",20,z=3),
  T("empty",100,200,400,60,"",30,z=3),
  T("newline",100.5,300.25,880,200,"Line one\nLine two\n\nLine four after blank",44,z=4,fam="Solstice Serif"),
  I("offcanvas",880,700,400,400,BOT,z=3),
  T("tie_a",100,600,500,60,"z tie A",30,z=4,text_align="left"),
  S("tie_b",80,590,300,80,z=4,fill=OR,corner_radius=20),
  T("tie_c",120.75,610.5,500,60,"z tie C over B?",30,z=4,text_align="left"),
  I("logo",33.3,960.7,180.4,60.15,LOGO,z=5)]}
cases["edge_kitchen_sink_to_a4"]=(ed,(2480,3508))
cases["edge_kitchen_sink_to_banner"]=(ed,(1584,396))
cases["only_text_to_story"]=({"canvas":{"width":1200,"height":628},"elements":[T("only",100,200,1000,200,"Only one text element and nothing else at all",56,color=PL)]},(1080,1920))
# xy-cut defeat: diagonal stagger with overlapping bands
dg={"canvas":{"width":1080,"height":1080},"elements":[BG(1080,1080)]}
for i in range(6):
  x=40+i*150; y=40+i*150
  if i%2==0: dg["elements"].append(I(f"d{i}",x,y,260,260,BOT,z=3))
  else: dg["elements"].append(T(f"d{i}",x,y,300,200,f"Stagger step {i}, overlapping bands",34,text_align="left",font_weight="bold"))
cases["diagonal_stagger_to_banner"]=(dg,(1584,396))
cases["diagonal_stagger_to_story"]=(dg,(1080,1920))
v=jsonschema.Draft202012Validator(schema)
for k,(src,(w,h)) in cases.items():
  errs=list(v.iter_errors(src)); assert not errs,(k,errs[0].message)
  (OUT/f"{k}.json").write_text(json.dumps({"task_id":k,"source":src,"target_canvas":{"width":w,"height":h}},indent=1))
print(len(cases),"cases written, all schema-valid")
