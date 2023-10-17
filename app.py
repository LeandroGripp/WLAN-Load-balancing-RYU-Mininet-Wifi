from ryu.base import app_manager
from ryu.controller import ofp_event
from ryu.controller.handler import CONFIG_DISPATCHER, MAIN_DISPATCHER
from ryu.controller.handler import set_ev_cls
from ryu.ofproto import ofproto_v1_3
from ryu.lib.packet import packet
from ryu.lib.packet import ethernet
from ryu.lib.packet import ether_types
from ryu.lib.packet import ipv4
from ryu.lib import hub

import os
import subprocess
import redis
import threading
import time
import pickle

STATION_THRESHOLD = 2
LOAD_THRESHOLD = 10*1000*1000 # 10Mbytes
SIGNAL_THRESHOLD = -90 # dBm

mappings_path = "mappings.txt"

station_name_mappings = {}
name_ip_mac_mappings = {}

def read_mappings():
    with open(mappings_path) as f:
        for line in f:
            data = line.split(' ')
            station_name_mappings[data[1]] = data[0]
            name_ip_mac_mappings[data[0]] = {
                "ip": data[2].split('/')[0],
                "mac": data[1]
            }

    print('mapping', name_ip_mac_mappings)
class SimpleSwitch13(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_3.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        read_mappings()
        super(SimpleSwitch13, self).__init__(*args, **kwargs)
        self.mac_to_port = {}
        self.statistics = []
        self.datapaths = {}

        # redis code
        self.redis = redis.Redis('127.0.0.1')
        self.pubsub = self.redis.pubsub()
        self.pubsub.subscribe(['statistics'])        
        self.monitor_thread = hub.spawn(self.monitor)

    def monitor(self):
        self.logger.info("start ap monitoring thread")
        for item in self.pubsub.listen():
            tmp = item['data']
            # ignore the first/initial return
            if tmp == 1:
                continue
            self.statistics = pickle.loads(tmp)
            print("---------------------------")
            print("received the statistics ", self.statistics)
            print("---------------------------")
            oaps =  self.get_overloaded_aps()
            print("Overloaded aps", oaps)
            print("---------------------------")
            uaps = self.get_underloaded_aps()
            print("Underloaded aps", uaps)
            print("---------------------------")
            
            if oaps and len(oaps) > 0 and uaps and len(uaps) > 0:
                self.get_possible_handover(oaps, uaps)

                station, new_ap = self.get_possible_handover(oaps, uaps)

                if station and new_ap:
                    migration_instruction = {'station_name': station, 'ssid': new_ap}
                    print("station to be migrated ", migration_instruction)
                    print("---------------------------")

                    pvalue = pickle.dumps(migration_instruction)
                    self.delete_flows_with_ip_and_mac(name_ip_mac_mappings[station])
                    self.redis.publish("sdn", pvalue)

    def get_overloaded_aps(self):
        overloaded_aps = []
        for stat in self.statistics:
            if len(stat['stations_associated']) > STATION_THRESHOLD:
                overloaded_aps.append(stat)

        return overloaded_aps

    def get_underloaded_aps(self):
        underloaded_aps = []
        for stat in self.statistics:
            if len(stat['stations_associated']) < STATION_THRESHOLD:
                underloaded_aps.append(stat)
        
        return underloaded_aps
    
    def get_possible_handover(self, oaps, uaps):
        uap_ssids = set([sta['ssid'] for sta in uaps])

        for oap in oaps:
            for station in oap['stations_associated']:
                station_aps = oap['stations_associated'][station]['aps']

                strong_ssids = set([ap for ap in station_aps if float(station_aps[ap]) > SIGNAL_THRESHOLD and ap != oap['ssid']])
                possible_uaps = strong_ssids & uap_ssids
                if len(possible_uaps) > 0:
                    new_ap = next(iter(possible_uaps))
                    print("possible handover", station, new_ap)
                    return station, new_ap
                    
                    
                
        return None, None
        
        


    @set_ev_cls(ofp_event.EventOFPSwitchFeatures, CONFIG_DISPATCHER)
    def switch_features_handler(self, ev):
        datapath = ev.msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        self.datapaths[datapath.id] = datapath
        match = parser.OFPMatch()
        actions = [parser.OFPActionOutput(ofproto.OFPP_CONTROLLER,
                                          ofproto.OFPCML_NO_BUFFER)]
        self.add_flow(datapath, 0, match, actions)

    def add_flow(self, datapath, priority, match, actions, buffer_id=None, idle=0):
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser

        inst = [parser.OFPInstructionActions(ofproto.OFPIT_APPLY_ACTIONS,
                                             actions)]
        if buffer_id:
            mod = parser.OFPFlowMod(datapath=datapath, buffer_id=buffer_id,
                                    priority=priority, match=match,
                                    idle_timeout=idle,
                                    instructions=inst)
        else:
            mod = parser.OFPFlowMod(datapath=datapath, priority=priority,idle_timeout=idle,
                                    match=match, instructions=inst)
        datapath.send_msg(mod)

    def delete_flows_with_ip_and_mac(self, ip_and_mac):
        ip = ip_and_mac['ip']
        mac = ip_and_mac['mac']
        for dp in self.datapaths.values():
            # IP as destination
            parser = dp.ofproto_parser
            match = parser.OFPMatch(ipv4_dst=ip, eth_type=0x0800)
            mod = parser.OFPFlowMod(datapath=dp, 
                                    command=dp.ofproto.OFPFC_DELETE,
                                    out_port=dp.ofproto.OFPP_ANY, out_group=dp.ofproto.OFPG_ANY,
                                    priority=1, match=match)
            dp.send_msg(mod)

            # IP as source
            match = parser.OFPMatch(ipv4_src=ip, eth_type=0x0800)
            mod = parser.OFPFlowMod(datapath=dp, 
                                    command=dp.ofproto.OFPFC_DELETE,
                                    out_port=dp.ofproto.OFPP_ANY, out_group=dp.ofproto.OFPG_ANY,
                                    priority=1, match=match)
            dp.send_msg(mod)

            # MAC as destination
            match = parser.OFPMatch(eth_dst=mac)
            mod = parser.OFPFlowMod(datapath=dp,
                                    command=dp.ofproto.OFPFC_DELETE,
                                    out_port=dp.ofproto.OFPP_ANY, out_group=dp.ofproto.OFPG_ANY,
                                    priority=1, match=match)
            
            dp.send_msg(mod)

            # MAC as source
            match = parser.OFPMatch(eth_src=mac)
            mod = parser.OFPFlowMod(datapath=dp, 
                                    command=dp.ofproto.OFPFC_DELETE,
                                    out_port=dp.ofproto.OFPP_ANY, out_group=dp.ofproto.OFPG_ANY,
                                    priority=1, match=match)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def _packet_in_handler(self, ev):
        # If you hit this you might want to increase
        # the "miss_send_length" of your switch
        if ev.msg.msg_len < ev.msg.total_len:
            self.logger.debug("packet truncated: only %s of %s bytes",
                              ev.msg.msg_len, ev.msg.total_len)
        msg = ev.msg
        datapath = msg.datapath
        ofproto = datapath.ofproto
        parser = datapath.ofproto_parser
        in_port = msg.match['in_port']

        pkt = packet.Packet(msg.data)
        eth = pkt.get_protocols(ethernet.ethernet)[0]

        if eth.ethertype == ether_types.ETH_TYPE_LLDP:
            # ignore lldp packet
            return
        dst = eth.dst
        src = eth.src

        dpid = datapath.id
        self.mac_to_port.setdefault(dpid, {})

        self.logger.info("packet in %s %s %s %s", dpid, src, dst, in_port)

        # learn a mac address to avoid FLOOD next time.
        self.mac_to_port[dpid][src] = in_port

        if dst in self.mac_to_port[dpid]:
            out_port = self.mac_to_port[dpid][dst]
        else:
            out_port = ofproto.OFPP_FLOOD

        actions = [parser.OFPActionOutput(out_port)]

        # install a flow to avoid packet_in next time
        if out_port != ofproto.OFPP_FLOOD:

            # check IP Protocol and create a match for IP
            if eth.ethertype == ether_types.ETH_TYPE_IP:
                ip = pkt.get_protocol(ipv4.ipv4)
                srcip = ip.src
                dstip = ip.dst
                match = parser.OFPMatch(eth_type=ether_types.ETH_TYPE_IP,
                                        ipv4_src=srcip,
                                        ipv4_dst=dstip
                                        )
                # verify if we have a valid buffer_id, if yes avoid to send both
                # flow_mod & packet_out
                if msg.buffer_id != ofproto.OFP_NO_BUFFER:
                    self.add_flow(datapath, 1, match, actions, msg.buffer_id, idle=30)
                    return
                else:
                    self.add_flow(datapath, 1, match, actions,idle=30)
        data = None
        if msg.buffer_id == ofproto.OFP_NO_BUFFER:
            data = msg.data

        out = parser.OFPPacketOut(datapath=datapath, buffer_id=msg.buffer_id,
                                  in_port=in_port, actions=actions, data=data)
        datapath.send_msg(out)
