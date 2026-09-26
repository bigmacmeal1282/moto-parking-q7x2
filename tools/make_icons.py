import os
from PIL import Image, ImageDraw, ImageFont
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
BG=(22,27,34); FG=(255,255,255); ACC=(46,158,68); ACC2=(242,183,5); ACC3=(74,111,165)
def icon(size, rounded, out, k=1.0):
    S=size*4
    im=Image.new("RGBA",(S,S),(0,0,0,0)); d=ImageDraw.Draw(im)
    if rounded: d.rounded_rectangle([0,0,S-1,S-1],radius=int(S*0.22),fill=BG)
    else: d.rectangle([0,0,S,S],fill=BG)
    f=ImageFont.truetype(FONT,int(S*0.62*k))
    bb=d.textbbox((0,0),"P",font=f); w=bb[2]-bb[0]; h=bb[3]-bb[1]
    d.text(((S-w)/2-bb[0],(S*(0.5-0.06*k))-h/2-bb[1]),"P",font=f,fill=FG)
    # curb stripe in legend colors
    y0=int(S*(0.5+0.26*k)); y1=int(S*(0.5+0.32*k)); x0=int(S*(0.5-0.3*k)); x1=int(S*(0.5+0.3*k)); seg=(x1-x0)/3; g=int(S*0.02)
    for i,c in enumerate([ACC,ACC2,ACC3]):
        d.rounded_rectangle([x0+i*seg+(g if i else 0),y0,x0+(i+1)*seg-(g if i<2 else 0),y1],radius=(y1-y0)//2,fill=c)
    im=im.resize((size,size),Image.LANCZOS)
    if not rounded: im=im.convert("RGB")
    im.save(out,optimize=True)
icon(180,False,os.path.join(ROOT,"apple-touch-icon.png"))
icon(192,True,os.path.join(ROOT,"icon-192.png"))
icon(512,True,os.path.join(ROOT,"icon-512.png"))
icon(512,False,os.path.join(ROOT,"icon-maskable-512.png"),k=0.8)
icon(32,True,os.path.join(ROOT,"favicon-32.png"))
