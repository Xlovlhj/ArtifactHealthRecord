import math
from fastapi import HTTPException


def validate_polygon(points, width, height):
    if not isinstance(points,list) or not 3 <= len(points) <= 2000:
        raise HTTPException(422, "多边形需包含3至2000个顶点")
    for p in points:
        if not isinstance(p,(list,tuple)) or len(p) != 2 or any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in p):
            raise HTTPException(422, "顶点坐标必须是有限数值")
        if not (0 <= p[0] <= width and 0 <= p[1] <= height):
            raise HTTPException(422, "标注超出原图范围")
    if points[0] == points[-1]: points = points[:-1]
    if len({tuple(p) for p in points}) != len(points):
        raise HTTPException(422, "多边形不能包含重复顶点")
    def orient(a,b,c): return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
    for i in range(len(points)):
        a,b = points[i],points[(i+1)%len(points)]
        for j in range(i+2,len(points)):
            if i == 0 and j == len(points)-1: continue
            c,d=points[j],points[(j+1)%len(points)]
            if orient(a,b,c)*orient(a,b,d)<0 and orient(c,d,a)*orient(c,d,b)<0:
                raise HTTPException(422,"多边形不能自相交")
    area = abs(sum(points[i][0]*points[(i+1)%len(points)][1]-points[(i+1)%len(points)][0]*points[i][1] for i in range(len(points))))/2
    if area <= 0: raise HTTPException(422,"标注面积必须大于0")
    return points, area


def calibration(points, length_cm, width, height):
    if not isinstance(points,list) or len(points)!=2 or any(not isinstance(p,list) or len(p)!=2 for p in points):
        raise HTTPException(422,"尺度标定需要两个点")
    if not isinstance(length_cm,(int,float)) or not math.isfinite(length_cm) or length_cm <= 0:
        raise HTTPException(422,"实际长度必须大于0")
    for p in points:
        if any(not isinstance(v,(int,float)) or not math.isfinite(v) for v in p) or not (0<=p[0]<=width and 0<=p[1]<=height):
            raise HTTPException(422,"标尺点超出原图范围")
    length_px=math.dist(*points)
    if length_px < 1: raise HTTPException(422,"标尺像素长度过短")
    return {"points":points,"length_cm":length_cm,"length_px":length_px,"cm_per_pixel":length_cm/length_px,"assumption":"局部平面且拍摄近似正射；单段标尺不能校正透视/曲面误差"}


def validate_centerline(points,width,height):
    if points is None:return None
    if not isinstance(points,list) or not 2<=len(points)<=2000:
        raise HTTPException(422,"裂隙中心线需要2至2000个实测顶点")
    for point in points:
        if len(point)!=2 or any(not math.isfinite(v) for v in point) or not (0<=point[0]<=width and 0<=point[1]<=height):
            raise HTTPException(422,"裂隙中心线超出图像或坐标无效")
    if any(math.dist(a,b)==0 for a,b in zip(points,points[1:])):
        raise HTTPException(422,"裂隙中心线不能有连续重复点")
    return points
