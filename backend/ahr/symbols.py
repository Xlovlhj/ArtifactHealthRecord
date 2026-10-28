"""Shared, paper-millimetre geometry for the six verified GB/T symbol definitions.

Source measurements are loaded from the versioned package. SVG and PDF consume
the same primitives, avoiding independent display-dependent symbol dimensions.
"""
import math
from .catalog import symbol_package


def distance_to_segment(point,a,b):
    dx,dy=b[0]-a[0],b[1]-a[1]
    norm=dx*dx+dy*dy
    if not norm:return math.dist(point,a)
    t=max(0,min(1,((point[0]-a[0])*dx+(point[1]-a[1])*dy)/norm))
    return math.dist(point,(a[0]+t*dx,a[1]+t*dy))


def inside(point,polygon):
    x,y=point;result=False
    for a,b in zip(polygon,polygon[1:]+polygon[:1]):
        if distance_to_segment(point,a,b)<1e-8:return True
        if (a[1]>y)!=(b[1]>y) and x<(b[0]-a[0])*(y-a[1])/(b[1]-a[1])+a[0]:result=not result
    return result


def boundary_hatch(polygon,band,spacing):
    """Clip diagonal hatch strokes to the polygon's exact inner boundary band.

    Candidate changes are polygon crossings and distance-to-edge=band crossings
    (parallel edge offsets and vertex circles). Midpoint classification then
    produces straight subsegments without approximating an inward polygon offset.
    """
    minx,miny=min(p[0] for p in polygon),min(p[1] for p in polygon)
    maxx,maxy=max(p[0] for p in polygon),max(p[1] for p in polygon)
    step=spacing*math.sqrt(2)
    output=[]
    direction=(1/math.sqrt(2),1/math.sqrt(2))
    edges=list(zip(polygon,polygon[1:]+polygon[:1]))
    intercept=math.floor((miny-maxx)/step)*step
    while intercept<=maxy-minx:
        origin=(minx-1,minx-1+intercept)
        stop=math.sqrt(2)*(maxx-minx+2)
        values=[0.,stop]
        ux,uy=direction
        for a,b in edges:
            ex,ey=b[0]-a[0],b[1]-a[1];length=math.hypot(ex,ey)
            if not length:continue
            cross=ex*uy-ey*ux
            if abs(cross)>1e-12:
                offset=ex*(origin[1]-a[1])-ey*(origin[0]-a[0])
                for side in (-band,0,band):
                    t=(side*length-offset)/cross
                    point=(origin[0]+t*ux,origin[1]+t*uy)
                    projection=((point[0]-a[0])*ex+(point[1]-a[1])*ey)/(length*length)
                    if 0<=t<=stop and 0<=projection<=1:values.append(t)
            # Each vertex circle covers the rounded ends of its edge capsule.
            vx,vy=origin[0]-a[0],origin[1]-a[1]
            linear=vx*ux+vy*uy
            determinant=linear*linear-(vx*vx+vy*vy-band*band)
            if determinant>=0:
                for t in (-linear-math.sqrt(determinant),-linear+math.sqrt(determinant)):
                    if 0<=t<=stop:values.append(t)
        values=sorted(set(values))
        for left,right in zip(values,values[1:]):
            if right-left<1e-8:continue
            middle=(left+right)/2
            point=(origin[0]+middle*ux,origin[1]+middle*uy)
            if inside(point,polygon) and min(distance_to_segment(point,a,b) for a,b in edges)<=band+1e-8:
                output.append([(origin[0]+left*ux,origin[1]+left*uy),(origin[0]+right*ux,origin[1]+right*uy)])
        intercept+=step
    return output


def symbol_geometry(row,mm_per_pixel):
    package=symbol_package()
    definition=next((s for s in package["symbols"] if s["name"]==row["type"]),None)
    polygon=[(x*mm_per_pixel,y*mm_per_pixel) for x,y in row["polygon"]]
    result={"polygon":polygon,"paths":[],"warnings":[],"stroke_width_mm":package["stroke_width_mm"],
            "outline":True,"clip":True,"symbol_key":definition["key"] if definition else "unmapped",
            "package_id":package["package_id"]}
    if not definition:
        result["warnings"].append("未找到已核验图示定义")
        return result
    parameters=definition["parameters"];key=definition["key"]
    minx,miny=min(p[0] for p in polygon),min(p[1] for p in polygon)
    maxx,maxy=max(p[0] for p in polygon),max(p[1] for p in polygon)
    if key in {"triangle","chevron"}:
        width,height=parameters["symbol_box_mm"]
        gap=parameters.get("implemented_clear_gap_mm",parameters["min_gap_mm"])
        y=math.floor(miny/(height+gap))*(height+gap)
        while y<=maxy:
            x=math.floor(minx/(width+gap))*(width+gap)
            while x<=maxx:
                if key=="triangle":path=[(x,y+height),(x+width/2,y),(x+width,y+height),(x,y+height)]
                else:path=[(x,y),(x+width/2,y+height),(x+width,y)]
                result["paths"].append(path)
                x+=width+gap
            y+=height+gap
    elif key=="horizontal_lines":
        spacing=parameters["spacing_mm"]
        y=math.floor(miny/spacing)*spacing
        while y<=maxy:
            result["paths"].append([(minx,y),(maxx,y)])
            y+=spacing
    elif key=="hatched_boundary_band":
        result["paths"]=boundary_hatch(polygon,parameters["band_width_mm"],parameters["hatch_spacing_mm"])
    elif key=="crack_centerline":
        line=row.get("centerline")
        result["outline"]=False
        if not line:
            result["warnings"].append("裂隙中心线未录入；仅显示调查范围，不推断标准裂隙线")
            result["outline"]=True
            return result
        line=[(x*mm_per_pixel,y*mm_per_pixel) for x,y in line]
        result["clip"]=False
        result["paths"].append(line)
        step=parameters["tick_spacing_mm"];tick=parameters["tick_length_mm"]
        next_at=step;traversed=0
        for a,b in zip(line,line[1:]):
            length=math.dist(a,b)
            if not length:continue
            while next_at<=traversed+length:
                distance=next_at-traversed
                x=a[0]+(b[0]-a[0])*distance/length;y=a[1]+(b[1]-a[1])*distance/length
                nx=-(b[1]-a[1])/length*tick/2;ny=(b[0]-a[0])/length*tick/2
                result["paths"].append([(x-nx,y-ny),(x+nx,y+ny)])
                next_at+=step
            traversed+=length
    return result
