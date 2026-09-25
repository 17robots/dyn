#include <stdbool.h>
#define CGLTF_IMPLEMENTATION
#include <cgltf.h>
#undef CGLTF_IMPLEMENTATION
#define CGLTF_WRITE_IMPLEMENTATION
#include <cgltf_write.h>
#include <string.h>
int dyn_cgltf_parse(const void *bytes, size_t size, cgltf_data **out) {
    cgltf_options options={0}; if (!out) return -1; *out=NULL;
    if (!bytes || !size) return -1;
    return cgltf_parse(&options,bytes,size,out);
}
int dyn_cgltf_embedded(cgltf_data *data) {
    if (!data) return -1;
    for (size_t i=0;i<data->buffers_count;i++) {
        const char *uri=data->buffers[i].uri;
        if (!data->buffers[i].data && uri && strncmp(uri,"data:",5)) return -2;
    }
    cgltf_options options={0}; return cgltf_load_buffers(&options,data,NULL);
}
size_t dyn_cgltf_nodes(cgltf_data *data) { return data?data->nodes_count:0; }
size_t dyn_cgltf_accessors(cgltf_data *data) { return data?data->accessors_count:0; }
bool dyn_cgltf_read(cgltf_data *data,size_t index,size_t element,float *out,size_t count) {
    if (!data || !out || index>=data->accessors_count || cgltf_validate(data)!=cgltf_result_success) return false;
    const cgltf_accessor *a=&data->accessors[index];
    if (element>=a->count || a->is_sparse || count<cgltf_num_components(a->type)) return false;
    return cgltf_accessor_read_float(a,element,out,count)!=0;
}
size_t dyn_cgltf_buffers(cgltf_data *d) { return d?d->buffers_count:0; }
const char *dyn_cgltf_uri(cgltf_data *d,size_t i) { return d && i<d->buffers_count?d->buffers[i].uri:NULL; }
size_t dyn_cgltf_buffer_size(cgltf_data *d,size_t i) { return d && i<d->buffers_count?d->buffers[i].size:0; }
bool dyn_cgltf_attach(cgltf_data *d,size_t i,const void *bytes,size_t size) {
    if (!d || i>=d->buffers_count || !bytes || size<d->buffers[i].size || d->buffers[i].data) return false;
    d->buffers[i].data=(void*)bytes;d->buffers[i].data_free_method=cgltf_data_free_method_none;return true;
}
size_t dyn_cgltf_meshes(cgltf_data *d) { return d?d->meshes_count:0; }
size_t dyn_cgltf_materials(cgltf_data *d) { return d?d->materials_count:0; }
size_t dyn_cgltf_primitives(cgltf_data *d,size_t mesh) { return d && mesh<d->meshes_count?d->meshes[mesh].primitives_count:0; }
static cgltf_primitive *primitive(cgltf_data *d,size_t m,size_t p) {
    return d && m<d->meshes_count && p<d->meshes[m].primitives_count?&d->meshes[m].primitives[p]:NULL;
}
/* Signed indices use -1 for absent/invalid, matching no unsigned sentinel ABI. */
int64_t dyn_cgltf_attribute(cgltf_data *d,size_t m,size_t p,int type,int set) {
    cgltf_primitive *v=primitive(d,m,p);if (!v || type<1 || type>7 || set<0) return -1;
    const cgltf_accessor *a=cgltf_find_accessor(v,(cgltf_attribute_type)type,set);
    return a?(int64_t)(a-d->accessors):-1;
}
int64_t dyn_cgltf_indices(cgltf_data *d,size_t m,size_t p) { cgltf_primitive *v=primitive(d,m,p);return v && v->indices?(int64_t)(v->indices-d->accessors):-1; }
int64_t dyn_cgltf_material(cgltf_data *d,size_t m,size_t p) { cgltf_primitive *v=primitive(d,m,p);return v && v->material?(int64_t)(v->material-d->materials):-1; }
int dyn_cgltf_topology(cgltf_data *d,size_t m,size_t p) { cgltf_primitive *v=primitive(d,m,p);return v?(int)v->type:0; }
size_t dyn_cgltf_elements(cgltf_data *d,size_t i) { return d && i<d->accessors_count?d->accessors[i].count:0; }
bool dyn_cgltf_index(cgltf_data *d,size_t i,size_t element,uint32_t *out) {
    if (!d || !out || i>=d->accessors_count || cgltf_validate(d)!=cgltf_result_success) return false;
    cgltf_accessor *a=&d->accessors[i];
    if (element>=a->count || a->is_sparse || a->type!=cgltf_type_scalar || (a->component_type!=cgltf_component_type_r_8u && a->component_type!=cgltf_component_type_r_16u && a->component_type!=cgltf_component_type_r_32u) || !a->buffer_view || !a->buffer_view->buffer->data) return false;
    *out=(uint32_t)cgltf_accessor_read_index(a,element);return true;
}
bool dyn_cgltf_base_color(cgltf_data *d,size_t i,float *out) {
    if (!d || i>=d->materials_count || !out) return false;
    memcpy(out,d->materials[i].pbr_metallic_roughness.base_color_factor,4*sizeof(float));return true;
}
int64_t dyn_cgltf_node_mesh(cgltf_data *d,size_t i) { return d && i<d->nodes_count && d->nodes[i].mesh?(int64_t)(d->nodes[i].mesh-d->meshes):-1; }
bool dyn_cgltf_transform(cgltf_data *d,size_t i,float *out) {
    if (!d || i>=d->nodes_count || !out || cgltf_validate(d)!=cgltf_result_success) return false;
    cgltf_node_transform_world(&d->nodes[i],out);return true;
}
