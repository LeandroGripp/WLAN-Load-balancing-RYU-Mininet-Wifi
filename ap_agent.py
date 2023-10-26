'''
AP Agent program
================

1)Metrics collection:
- Read the Stations associated with the AP
Send the Metrics to the  RYU SDN Controller

2) Station handover:
Receive notification from RYU SDN Controller for forceful movement 
of station to  new AP and perform it

Interface to RYU SDN Controller - Redis Pub/Sub 

'''
# Executing Command
import os
import json
import subprocess
import redis
import threading
import time
import pickle

#APs
# aps = ['ap1', 'ap2']
aps = ['ap1', 'ap2', 'ap3', 'ap4']
# stations = ['sta1', 'sta2', 'sta3', 'sta4', 'sta5', 'sta6', 'sta7', 'sta8']
stations_mapping = {}
stations_aps = {}
stations_traffic = {}
ap_metrics = []

mappings_path = "mappings.txt"
AP_METRICS_PERIOD_IN_SECONDS = 10

# Utility functions

def read_mappings():
    with open(mappings_path) as f:
        for line in f:
            data = line.split(' ')
            stations_mapping[data[1]] = data[0]
            stations_aps[data[0]] = {}

    print('mapping', stations_mapping)
    print('aps', stations_aps)

# execute the command
def run_cmd(cmd):
    try:
        output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        #print(cmd, output)
        return output.decode('UTF-8','ignore')

    except subprocess.CalledProcessError as ex:
        if ex.returncode == 255:
            raise RuntimeWarning(ex.output.strip())
        raise RuntimeError('cmd execution returned exit status %d:\n%s'
                % (ex.returncode, ex.output.strip()))

# Parse SSID
def get_ssid(output):
    result = output.split("\n")
    # parse the output and get the ssid
    for data in result:
        if "ssid" in data:
            ssid = data.split(' ')[1]
            return ssid
    return None

# parse stations 
def get_stations(output):
    stations = {}
    result = output.split("\n")
    curr_station = ""
    for data in result:
        if "Station" in data:
            station = data.split(' ')[1]
            curr_station = station
            stations[station] = {}
        elif "rx bytes" in data:
            rx_bytes = data.split('\t')[2]
            stations[curr_station]["rx_bytes"] = rx_bytes
        elif "tx bytes" in data:
            tx_bytes = data.split('\t')[2]
            stations[curr_station]["tx_bytes"] = tx_bytes
    return stations

def get_signal_strengths(output):
    signal_strengths = {}
    result = output.split("\n")
    curr_strength = None
    for data in result:
        if "signal" in data:
            signal = data.split(' ')[1]
            curr_strength = signal
        if "ssid" in data:
            ssid = data.split(' ')[1]
            signal_strengths[ssid] = curr_strength

    return signal_strengths

def get_connected_interface(output):
    if '-- associated' in output:
        return 'wlan0'
    else:
        return 'wlan1'

def measures_ap_metrics():
    dpid = 1
    report = []    
    for ap in aps:
        result = {}
        result["name"] = ap
        result["dpid"] = dpid
        apifname = ap + "-wlan1"
        result["if_name"] = apifname
        #iw dev ap1-wlan1 info
        cmd = ['iw', 'dev', apifname, 'info']
        output = run_cmd(cmd)
        result["ssid"] = get_ssid(str(output))
       
        #get the stations associated
        cmd = ['iw', 'dev', apifname, 'station', 'dump']
        output = run_cmd(cmd)
        stations_associated = get_stations(str(output))
        result['stations_associated'] = {}
        for station in stations_associated:
            prev_rx_bytes = stations_traffic.get(station, {}).get("rx_bytes", 0)
            prev_tx_bytes = stations_traffic.get(station, {}).get("tx_bytes", 0)

            curr_rx_bytes = stations_associated[station].get("rx_bytes", 0)
            curr_tx_bytes = stations_associated[station].get("tx_bytes", 0)

            if int(curr_rx_bytes) < int(prev_rx_bytes):
                prev_rx_bytes = 0
            if int(curr_tx_bytes) < int(prev_tx_bytes):
                prev_tx_bytes = 0

            stations_traffic[station] = {
                "rx_bytes": curr_rx_bytes,
                "tx_bytes": curr_tx_bytes
            }

            rx_bw = (int(curr_rx_bytes) - int(prev_rx_bytes)) / AP_METRICS_PERIOD_IN_SECONDS
            tx_bw = (int(curr_tx_bytes) - int(prev_tx_bytes)) / AP_METRICS_PERIOD_IN_SECONDS

            station_name = stations_mapping[station]
            result['stations_associated'][station_name] = stations_aps[station_name]

            result['stations_associated'][station_name]['rx_rate'] = rx_bw*8/1000000 #convert to Mbps
            result['stations_associated'][station_name]['tx_rate'] = tx_bw*8/1000000 #convert to Mbps

        report.append(result)
        dpid +=1

    return report

class ApMetrics(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        
    def run(self):
        global ap_metrics
        while 1:
            ap_metrics = measures_ap_metrics()
            time.sleep(AP_METRICS_PERIOD_IN_SECONDS)


class StationMetrics(threading.Thread):
    def __init__(self, station_name):
        super().__init__()
        threading.Thread.__init__(self)
        self.station_name = station_name

    def get_ap_strengths(self, station_name):
        #iw dev sta1-wlan0 scan
        ssifname = station_name + "-wlan0"
        cmd = ['./m', station_name, 'iw', 'dev', ssifname, 'scan']
        output = run_cmd(cmd)
        stations_aps[station_name] = {
            'aps': get_signal_strengths(str(output)),
        }
        exit(1)
        
    def run(self):
        self.get_ap_strengths(self.station_name)

class Sender(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.redis = redis.Redis('127.0.0.1')
        self.pubsub = self.redis.pubsub()

    def run(self):
        global ap_metrics
        while 1:
            print(ap_metrics)
            print()
            
            pvalue = pickle.dumps(ap_metrics)
            self.redis.publish("statistics", pvalue)
 
            time.sleep(20)


class Listener(threading.Thread):
    def __init__(self):
        threading.Thread.__init__(self)
        self.redis = redis.Redis('127.0.0.1')
        self.pubsub = self.redis.pubsub()
        self.pubsub.subscribe(['sdn'])

    def run(self):
        for item in self.pubsub.listen():
            tmp = item['data']
            if tmp == 1:
                continue
            data = pickle.loads(tmp)
            print("data received for migration ", data)
            self.migrate(data)

    def migrate(self, data):
        #data['station_name'] = "sta1"
        #data['ssid'] = "ssid_ap2"
        #data['interface'] = "wlan1"
        #./m sta1 iw dev sta1-wlan0 disconnect
        #./m sta1 iw dev sta1-wlan1 connect ssid-ap2

        ifname = data['station_name'] + '-wlan0'

        cmd = ['./m', data['station_name'], 'iw', 'dev', ifname, 'disconnect']
        print( cmd)
        print( run_cmd(cmd))

        cmd = ['./m', data['station_name'], 'iw', 'dev', ifname, 'connect', data['ssid']]
        print( cmd)
        print( run_cmd(cmd))

        print()

if __name__ == '__main__':
    read_mappings()
    # print(stations_mapping)

    for station in stations_mapping:
        station_monitor = StationMetrics(stations_mapping[station])
        station_monitor.start()
    
    ap_monitor = ApMetrics()
    ap_monitor.start()

    sender = Sender()
    receiver = Listener()
    sender.start()
    receiver.start()
