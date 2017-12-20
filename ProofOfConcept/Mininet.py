from mininet.net import Mininet
from mininet.topo import LinearTopo
from mininet.node import OVSKernelSwitch, OVSSwitch, RemoteController, Host, CPULimitedHost
from threading import Thread
from mininet.cli import CLI
from mininet.link import TCLink
from mininet.util import dumpNodeConnections
from mininet.clean import Cleanup
import os, time
from mininet.util import quietRun
from mininet.link import Intf
from mininet.log import setLogLevel, info
from mininet.nodelib import LinuxBridge
import thread, threading

#--------------------SFLOW----------------------------
from mininet.util import quietRun
from requests import put
from json import dumps
from subprocess import call, check_output
from os import listdir
import re
import socket

collector = '127.0.0.1'
sampling = 10
polling = 10

def getIfInfo(ip):
  s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
  s.connect((ip, 0))
  ip = s.getsockname()[0]
  ifconfig = check_output(['ifconfig'])
  ifs = re.findall(r'^(\S+).*?inet addr:(\S+).*?', ifconfig, re.S|re.M)
  for entry in ifs:
    if entry[1] == ip:
      return entry

def configSFlow(net,collector,ifname):
  print "*** Enabling sFlow:"
  sflow = 'ovs-vsctl -- --id=@sflow create sflow agent=%s target=%s sampling=%s polling=%s --' % (ifname,collector,sampling,polling)
  for s in net.switches:
    sflow += ' -- set bridge %s sflow=@sflow' % s
  print ' '.join([s.name for s in net.switches])
  quietRun(sflow)

def sendTopology(net,agent,collector):
  print "*** Sending topology"
  topo = {'nodes':{}, 'links':{}}
  for s in net.switches:
    topo['nodes'][s.name] = {'agent':agent, 'ports':{}}
  path = '/sys/devices/virtual/net/'
  for child in listdir(path):
    parts = re.match('(^s[0-9]+)-(.*)', child)
    if parts == None: continue
    ifindex = open(path+child+'/ifindex').read().split('\n',1)[0]
    topo['nodes'][parts.group(1)]['ports'][child] = {'ifindex': ifindex}
  i = 0
  for s1 in net.switches:
    j = 0
    for s2 in net.switches:
      if j > i:
        intfs = s1.connectionsTo(s2)
        for intf in intfs:
          s1ifIdx = topo['nodes'][s1.name]['ports'][intf[0].name]['ifindex']
          s2ifIdx = topo['nodes'][s2.name]['ports'][intf[1].name]['ifindex']
          linkName = '%s-%s' % (s1.name, s2.name)
          topo['links'][linkName] = {'node1': s1.name, 'port1': intf[0].name, 'node2': s2.name, 'port2': intf[1].name}
      j += 1
    i += 1

  put('http://'+collector+':8008/topology/json',data=dumps(topo))

def wrapper(fn,collector):
  def result( *args, **kwargs):
    res = fn( *args, **kwargs)
    net = args[0]
    (ifname, agent) = getIfInfo(collector)
    configSFlow(net,collector,ifname)
    sendTopology(net,agent,collector) 
    return res
  return result
#--------------------SFLOW----------------------------

net = Mininet(switch = OVSSwitch, autoSetMacs=True)

#setattr(Mininet, 'start', wrapper(Mininet.__dict__['start'], collector))

poxcontroller = net.addController(name="pox",
				controller=RemoteController, 
				ip="127.0.0.1", protocol="tcp", 
				port=6633) 

#add hosts
client = net.addHost('h1')		#10.0.0.1
attacker = net.addHost('h2')	#10.0.0.2

#add delegators
del1 = net.addHost('h3')		#10.0.0.3
del2 = net.addHost('h4')		#10.0.0.4

#add switch
s1 = net.addSwitch('s1')
s2 = net.addSwitch('s2')
s3 = net.addSwitch('s3')

net.addLink(client, s1)
net.addLink(del1, s1)
net.addLink(del2, s3)
net.addLink(del1, s2)
net.addLink(del2, s2)
net.addLink(attacker, s3)
net.addLink(s1, s2)
net.addLink(s2, s3)

net.build()
net.addNAT().configDefault()
net.start()
net.pingAll()

#Start delegator program on the two delegators
delegatorPath = 'python Delegator.py'
delegator1 = net.get('h3')
delegator2 = net.get('h4')
thread.start_new_thread(delegator1.cmd, (delegatorPath, ))
thread.start_new_thread(delegator2.cmd, (delegatorPath, ))

cli = CLI(net)

net.stop()

