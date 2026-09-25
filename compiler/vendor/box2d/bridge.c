#include <stddef.h>
#include <box2d/box2d.h>
#include <math.h>
#include <stdint.h>
uint32_t dyn_b2_world_create(float x, float y) {
    if (!isfinite(x) || !isfinite(y)) return 0;
    b2WorldDef def = b2DefaultWorldDef(); def.gravity = (b2Vec2){x,y};
    return b2StoreWorldId(b2CreateWorld(&def));
}
bool dyn_b2_world_destroy(uint32_t id) {
    b2WorldId world=b2LoadWorldId(id); if (!b2World_IsValid(world)) return false;
    b2DestroyWorld(world); return true;
}
bool dyn_b2_step(uint32_t id, float dt, int steps) {
    b2WorldId world=b2LoadWorldId(id);
    if (!b2World_IsValid(world) || !isfinite(dt) || dt<=0 || dt>1 || steps<1 || steps>64) return false;
    b2World_Step(world,dt,steps); return true;
}
uint64_t dyn_b2_body(uint32_t id, float x, float y, bool dynamic) {
    b2WorldId world=b2LoadWorldId(id);
    if (!b2World_IsValid(world) || !isfinite(x) || !isfinite(y)) return 0;
    b2BodyDef def=b2DefaultBodyDef(); def.position=(b2Vec2){x,y};
    def.type=dynamic ? b2_dynamicBody : b2_staticBody;
    return b2StoreBodyId(b2CreateBody(world,&def));
}
bool dyn_b2_body_destroy(uint64_t id) {
    b2BodyId body=b2LoadBodyId(id); if (!b2Body_IsValid(body)) return false;
    b2DestroyBody(body); return true;
}
uint64_t dyn_b2_box(uint64_t id, float hx, float hy, float density) {
    b2BodyId body=b2LoadBodyId(id);
    if (!b2Body_IsValid(body) || !isfinite(hx) || !isfinite(hy) || !isfinite(density) || hx<=0 || hy<=0 || density<0) return 0;
    b2ShapeDef def=b2DefaultShapeDef(); def.density=density;
    b2Polygon shape=b2MakeBox(hx,hy);
    return b2StoreShapeId(b2CreatePolygonShape(body,&def,&shape));
}
bool dyn_b2_position(uint64_t id, float *x, float *y) {
    b2BodyId body=b2LoadBodyId(id); if (!x || !y || !b2Body_IsValid(body)) return false;
    b2Vec2 p=b2Body_GetPosition(body); *x=p.x; *y=p.y; return true;
}
uint64_t dyn_b2_circle(uint64_t id,float radius,float density) {
    b2BodyId body=b2LoadBodyId(id);
    if (!b2Body_IsValid(body) || !isfinite(radius) || radius<=0 || !isfinite(density) || density<0) return 0;
    b2ShapeDef def=b2DefaultShapeDef();def.density=density;
    b2Circle circle={.radius=radius};return b2StoreShapeId(b2CreateCircleShape(body,&def,&circle));
}
uint64_t dyn_b2_distance(uint64_t a,uint64_t b,float length) {
    b2BodyId first=b2LoadBodyId(a),second=b2LoadBodyId(b);
    if (a==b || !b2Body_IsValid(first) || !b2Body_IsValid(second) || !isfinite(length) || length<=0) return 0;
    b2WorldId world=b2Body_GetWorld(first);
    if (b2StoreWorldId(world)!=b2StoreWorldId(b2Body_GetWorld(second))) return 0;
    b2DistanceJointDef def=b2DefaultDistanceJointDef();def.bodyIdA=first;def.bodyIdB=second;def.length=length;
    return b2StoreJointId(b2CreateDistanceJoint(world,&def));
}
bool dyn_b2_joint_destroy(uint64_t id) {
    b2JointId joint=b2LoadJointId(id);if (!b2Joint_IsValid(joint)) return false;b2DestroyJoint(joint);return true;
}
bool dyn_b2_events(uint64_t id,bool enabled) {
    b2ShapeId shape=b2LoadShapeId(id);if (!b2Shape_IsValid(shape)) return false;b2Shape_EnableContactEvents(shape,enabled);return true;
}
int dyn_b2_contact_count(uint32_t id,bool begin) {
    b2WorldId world=b2LoadWorldId(id);if (!b2World_IsValid(world)) return -1;
    b2ContactEvents events=b2World_GetContactEvents(world);return begin?events.beginCount:events.endCount;
}
bool dyn_b2_contact(uint32_t id,bool begin,int index,uint64_t *a,uint64_t *b) {
    b2WorldId world=b2LoadWorldId(id);if (!a || !b || index<0 || !b2World_IsValid(world)) return false;
    b2ContactEvents events=b2World_GetContactEvents(world);
    if (index >= (begin?events.beginCount:events.endCount)) return false;
    *a=b2StoreShapeId(begin?events.beginEvents[index].shapeIdA:events.endEvents[index].shapeIdA);
    *b=b2StoreShapeId(begin?events.beginEvents[index].shapeIdB:events.endEvents[index].shapeIdB);return true;
}
typedef struct { uint64_t *items;size_t capacity,count; } Query;
static bool query_shape(b2ShapeId shape,void *context) {
    Query *q=context;if (q->count<q->capacity) q->items[q->count]=b2StoreShapeId(shape);q->count++;return true;
}
int64_t dyn_b2_query(uint32_t id,float x0,float y0,float x1,float y1,uint64_t *items,size_t capacity) {
    b2WorldId world=b2LoadWorldId(id);
    if (!b2World_IsValid(world) || (!items && capacity) || !isfinite(x0) || !isfinite(y0) || !isfinite(x1) || !isfinite(y1) || x0>x1 || y0>y1) return -1;
    Query q={items,capacity,0};b2AABB box={{x0,y0},{x1,y1}};
    b2World_OverlapAABB(world,box,b2DefaultQueryFilter(),query_shape,&q);return (int64_t)q.count;
}
