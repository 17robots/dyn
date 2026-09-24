#include <enet/enet.h>
#include <stdbool.h>
#include <stddef.h>
ENetHost *dyn_enet_host(const char *ip, uint16_t port, size_t peers, size_t channels) {
    if (!peers || peers>4095 || channels<1 || channels>255) return NULL;
    ENetAddress address={ENET_HOST_ANY,port};
    if (ip && enet_address_set_host_ip(&address,ip)) return NULL;
    return enet_host_create(ip?&address:NULL,peers,channels,0,0);
}
uint16_t dyn_enet_port(ENetHost *host) { return host?host->address.port:0; }
ENetPeer *dyn_enet_connect(ENetHost *host,const char *ip,uint16_t port,size_t channels) {
    ENetAddress address={0,port}; if (!host || !ip || !port || channels<1 || channels>255 || enet_address_set_host_ip(&address,ip)) return NULL;
    return enet_host_connect(host,&address,channels,0);
}
int dyn_enet_service(ENetHost *host,uint32_t timeout,int *type,ENetPeer **peer,ENetPacket **packet,uint8_t *channel,uint32_t *data) {
    *type=0;*peer=NULL;*packet=NULL;*channel=0;*data=0; if (!host) return -1;
    ENetEvent event={0}; int result=enet_host_service(host,&event,timeout);
    if (result>0) { *type=event.type;*peer=event.peer;*channel=event.channelID;*data=event.data;*packet=event.type==ENET_EVENT_TYPE_RECEIVE?event.packet:NULL; }
    return result;
}
bool dyn_enet_send(ENetPeer *peer,const void *data,size_t size,uint8_t channel) {
    if (!peer || channel>=peer->channelCount || (!data && size) || size>1024*1024) return false;
    ENetPacket *packet=enet_packet_create(data,size,ENET_PACKET_FLAG_RELIABLE);
    if (!packet) return false;
    if (enet_peer_send(peer,channel,packet)) { enet_packet_destroy(packet);return false; }
    return true;
}
const unsigned char *dyn_enet_data(ENetPacket *packet) { return packet?packet->data:NULL; }
size_t dyn_enet_size(ENetPacket *packet) { return packet?packet->dataLength:0; }
