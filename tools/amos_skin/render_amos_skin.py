import math, random
from PIL import Image, ImageDraw
W=H=200; CX,CY=100,84
STATES=["idle","listening","transcribing","thinking","synthesizing","speaking","error","busy","offline"]
BAYER=[[0,8,2,10],[12,4,14,6],[3,11,1,9],[15,7,13,5]]
def halo(px, r_in, r_out, strength):
    # ordered-dither glow ring between r_in and r_out (ink on paper)
    for y in range(20,148):
        for x in range(W):
            d=math.hypot(x-CX,y-CY)
            if r_in<=d<=r_out:
                t=1-(d-r_in)/(r_out-r_in)
                if t*strength*16 > BAYER[y%4][x%4]: px[x,y]=0
def grid(dr):
    for x in range(10,200,16):
        for y in range(24,146,3): dr.point((x,y),fill=0)
    for y in range(28,146,16):
        for x in range(4,198,3): dr.point((x,y),fill=0)
def ring(dr,r,w,fill=0): dr.ellipse([CX-r,CY-r,CX+r,CY+r],outline=fill,width=w)
def arcseg(dr,r,w,a0,a1): dr.arc([CX-r,CY-r,CX+r,CY+r],a0,a1,fill=0,width=w)
def ticks(dr,r0,r1,n,skip=()):
    for i in range(n):
        if i in skip: continue
        a=2*math.pi*i/n
        dr.line([(CX+r0*math.cos(a),CY+r0*math.sin(a)),(CX+r1*math.cos(a),CY+r1*math.sin(a))],fill=0,width=1)
def render(st):
    im=Image.new("1",(W,H),1); px=im.load(); dr=ImageDraw.Draw(im)
    if st!="offline": grid(dr)
    # clear disk behind the eye
    dr.ellipse([CX-60,CY-60,CX+60,CY+60],fill=1)
    glow={"idle":.55,"listening":.8,"transcribing":.6,"thinking":.6,"synthesizing":.7,"speaking":.9,"error":.35,"busy":.45,"offline":0}[st]
    if glow: halo(px,52,62,glow)
    ring(dr,52,4)
    if st=="transcribing":
        for a in range(0,360,30): arcseg(dr,44,3,a,a+18)
    elif st=="busy":
        arcseg(dr,44,3,-90,90)
    elif st=="synthesizing":
        ring(dr,44,1); ticks(dr,38,44,24)
    elif st!="offline":
        ring(dr,44,1)
    ticks(dr,46,51,36) if st not in("offline","error") else None
    # iris / pupil
    if st=="offline":
        dr.line([(CX-24,CY),(CX+24,CY)],fill=0,width=3)
        from PIL import ImageFont
        f=ImageFont.load_default(size=14); dr.text((CX+40,CY-52),"z",fill=0,font=f); dr.text((CX+52,CY-66),"Z",fill=0,font=ImageFont.load_default(size=18))
    elif st=="error":
        ring(dr,24,3)
        dr.line([(CX-12,CY-12),(CX+12,CY+12)],fill=0,width=4); dr.line([(CX-12,CY+12),(CX+12,CY-12)],fill=0,width=4)
        dr.line([(CX+30,CY-48),(CX+38,CY-30),(CX+33,CY-22)],fill=1,width=3)  # crack in ring
    else:
        off={"thinking":(9,-9)}.get(st,(0,0))
        ir={"listening":28,"speaking":26}.get(st,22)
        x,y=CX+off[0],CY+off[1]
        dr.ellipse([x-ir,y-ir,x+ir,y+ir],outline=0,width=3)
        pr={"listening":12,"speaking":11,"thinking":7,"busy":8}.get(st,9)
        dr.ellipse([x-pr,y-pr,x+pr,y+pr],fill=0)
        dr.rectangle([x+pr//3,y-pr//2-1,x+pr//3+2,y-pr//2+1],fill=1)  # glint
    if st=="listening":
        for k,r in enumerate((66,73)):
            arcseg(dr,r,2,150,210); arcseg(dr,r,2,-30,30)
    if st=="speaking":
        hs=[4,9,14,7,12,5,10,3]
        for i,h in enumerate(hs):
            x=CX-35+i*10; dr.rectangle([x,140-h,x+5,143],fill=0)
    if st=="thinking":
        for i,(dx,dy) in enumerate([(46,-48),(56,-55),(67,-60)]):
            r=2+i; dr.ellipse([CX+dx-r,CY+dy-r,CX+dx+r,CY+dy+r],fill=0)
    # night panel: invert the art band so the eye glows out of black
    band=im.crop((0,20,W,148)); from PIL import ImageOps
    band=ImageOps.invert(band.convert("L")).convert("1"); im.paste(band,(0,20))
    return im
import sys
out=sys.argv[1]
for st in STATES: render(st).save(f"{out}/amos_{st}_200x200_1bit.png")
