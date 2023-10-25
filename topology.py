import sys

from mininet.log import setLogLevel, info
from mn_wifi.cli import CLI
from mn_wifi.net import Mininet_wifi
from mininet.node import RemoteController
from mn_wifi.node import OVSKernelAP
from mn_wifi.link import wmediumd
from mininet.link import TCLink
from mn_wifi.wmediumdConnector import interference

N_hosts = 4

mappings_file_path = "mappings.txt"

class Host:
    def __init__(self,name, mac, ip):
        self.name = name
        self.mac = mac
        self.ip = ip

hostsInfo = []
hostsArray = []

for i in range (N_hosts):
    Nsta = i+1
    NIP = i+2
    Nmac = i+2
    CurrentHost = Host('sta' + str(Nsta),
                       '00:00:00:00:00:0' + str(Nmac),
                       '10.0.0.' + str(NIP) + '/8')
    hostsInfo.append(CurrentHost)

def topology():
    info("*** Creating network\n")
    net = Mininet_wifi(controller = RemoteController,
                       accessPoint=OVSKernelAP,
                       autoAssociation=False, 
                       link=wmediumd, wmediumd_mode=interference)

    info("*** Adding 2 APs and controllers\n")

    ap1 = net.addAccessPoint('ap1', ssid='ssid-ap1', channel='1',mode='g', position='30,30,0', range=30)
    ap2 = net.addAccessPoint('ap2', ssid='ssid-ap2', channel='6',mode='g', position='70,30,0', range=30)

    c1 = net.addController('c1', controller=RemoteController)


    info("*** Adding stations to the topology\n")

    server = net.addHost('server', mac='00:00:00:00:00:01', ip='10.0.0.1/8')

    staPositions = ['50,30,0', '30,20,0', '10,30,0', '80,40,0']
    f = open(mappings_file_path, "w")
    for i in range (int(N_hosts)):
        sta = net.addStation(hostsInfo[i].name, 
                             mac=hostsInfo[i].mac, ip=hostsInfo[i].ip,
                   position=staPositions[i], range=10
                   )
        f.write(hostsInfo[i].name + " " + hostsInfo[i].mac + " " + hostsInfo[i].ip + "\n")
        hostsArray.append(sta)

    f.close()

    net.setPropagationModel(model="logDistance", exp=5.5)

    info("*** Configuring wifi nodes\n")
    net.configureWifiNodes()

    info("*** Creating links\n")
    net.addLink(ap1, ap2)

    net.addLink(server, ap1, cls=TCLink, bw=20)
    net.addLink(server, ap2, cls=TCLink, bw=20)

    net.addLink(hostsArray[0], ap1)
    net.addLink(hostsArray[1], ap1)
    net.addLink(hostsArray[2], ap1)
    net.addLink(hostsArray[3], ap2)

    net.plotGraph(min_x=0, max_x=100, min_y=-10, max_y=70)

    # net.setMobilityModel(ac_method='ssf')

    info("*** Starting network\n")
    net.build()
    c1.start()
    ap1.start([c1])
    ap2.start([c1])

    info("*** Running CLI\n")
    CLI(net)

    info("*** Stopping network\n")
    net.stop()

if __name__ == '__main__':
    setLogLevel('info')
    topology()