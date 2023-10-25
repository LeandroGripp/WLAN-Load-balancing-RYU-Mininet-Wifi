import os
import random
import time

random.seed(1)

N_hosts = 20

os.system('./m server iperf -s -u -p 8 -i 1 > server_output.txt &')

for i in range (N_hosts):
    Nsta = i+1
    traffic = random.random() * 5
    os.system(f'./m sta{Nsta} iperf -c 10.0.0.1 -u -p 8 -b {traffic:.2f}m -t 120 &')
    # time.sleep(0.5)

time.sleep(120)