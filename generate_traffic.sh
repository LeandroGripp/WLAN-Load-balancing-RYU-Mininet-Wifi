#!/bin/bash  
./m server "iperf -s -u -p 8 -i 1 > server_output.txt" &
./m sta1 "iperf -c 10.0.0.1 -u -p 8 -b 7m -t 120" &
./m sta2 "iperf -c 10.0.0.1 -u -p 8 -b 5m -t 120" &
./m sta3 "iperf -c 10.0.0.1 -u -p 8 -b 6m -t 120" &
./m sta4 "iperf -c 10.0.0.1 -u -p 8 -b 5m -t 120"