#!/bin/env python
# -*- coding: utf-8 -*-

import random
from sh import nsenter, ip
from dockerfly.errors import (VEthCreateException, VEthUpException,
                              VEthDownException, VEthAttachException,
                              VEthDeleteException)
from dockerfly.logger import getLogger
logger = getLogger()

class VEth(object):
    """support ip link add vethxxx ...

    You can setup your own macvlan,macvtap, bridge,veth...
    """

    def __init__(self, name, ip_netmask, link_to):
        """

        Args:
            name: em0v0
            ip_netmask: 192.168.159.1/24
            link_to: em0
        """

        self._veth_name = name
        self._ip_netmask = ip_netmask
        self._link_to = link_to

    def attach_to_container(self, container_pid):
        raise NotImplementedError

    @classmethod
    def gen_mac_address(cls):
        """fake a unique mac address"""
        # The first line is defined for specified vendor
        mac = [ 0x00, 0x24, 0x81,
        random.randint(0x00, 0x7f),
        random.randint(0x00, 0xff),
        random.randint(0x00, 0xff) ]

        return ':'.join(map(lambda x: "%02x" % x, mac))

class MacvlanEth(VEth):
    """add a macvlan eth to net namespace and attach to container

    macvlan_eth = MacvlanEth('em0v0', '192.168.1.10/24', 'em0').create()
    macvlan_eth.attatch(container pid)

    as the same as exec commands below:

        ip link add em0v0 link em0 type macvlan mode bridge
        ip link set netns $(docker container pid) em0v0

    if macvlan_eth is default route, then do:

        nsenter -t $(docker container pid) -n ip route del default
        nsenter -t $(docker container pid) -n ip addr add 192.168.1.10 dev em0v0
        nsenter -t $(docker container pid) -n ip route add default via 192.168.159.2 dev em0v0

    if ip='0.0.0.0/0', don't set ip address
    """

    def __init__(self, name, ip, link_to):
        super(MacvlanEth, self).__init__(name, ip, link_to)
        self._is_attach_to_container = False
        self._attach_to_container_pid = None

    def create(self):
        try:
            ip('link', 'add', self._veth_name,
                'link', self._link_to, 'address', self.gen_mac_address(), 'type', 'macvlan', 'mode', 'bridge')
        except Exception as e:
            raise VEthCreateException("create macvlan eth error:\n{}".format(e.message))
        return self

    def up(self):
        try:
            if self._is_attach_to_container:
                nsenter('-t', self._attach_to_container_pid,
                        '-n', 'ip', 'link', 'del', self._veth_name)
            else:
                ip('link', 'set', self._veth_name, 'up')
        except Exception as e:
            raise VEthUpException("up macvlan eth error:\n{}".format(e.message))
        return self

    def down(self):
        try:
            if self._is_attach_to_container:
                nsenter('-t', self._attach_to_container_pid,
                        '-n', 'ip', 'link', self._veth_name, 'down')
            else:
                ip('link', 'set', self._veth_name, 'down')
        except Exception as e:
            raise VEthDownException("down macvlan eth error:\n{}".format(e.message))
        return self

    def delete(self):
        try:
            if self._is_attach_to_container:
                nsenter('-t', self._attach_to_container_pid,
                        '-n', 'ip', 'link', 'del', self._veth_name)
            else:
                ip('link', 'del', self._veth_name)
        except Exception as e:
            raise VEthDeleteException("delete macvlan eth error:\n{}".format(e.message))

    def attach_to_container(self, container_pid, is_route=False, gateway=None):
        self._is_attach_to_container = True
        self._attach_to_container_pid = container_pid

        try:
            ip('link', 'set', 'netns', self._attach_to_container_pid, self._veth_name)
            nsenter('-t', self._attach_to_container_pid,
                    '-n', 'ip', 'link', 'set', self._veth_name, 'up')

            if '0.0.0.0' not in self._ip_netmask:
                nsenter('-t', self._attach_to_container_pid,
                    '-n', 'ip', 'addr', 'add', self._ip_netmask, 'dev', self._veth_name)
        except Exception as e:
            raise VEthAttachException("attach macvlan eth error:\n{}".format(e.message))

        if is_route:
            if not gateway:
                raise ValueError("Please set the gateway for %s" % self._veth_name)
            else:
                nsenter('-t', self._attach_to_container_pid,
                        '-n', 'ip', 'route', 'del', 'default')
                nsenter('-t', self._attach_to_container_pid,
                        '-n', 'ip', 'route', 'add', 'default', 'via', gateway, 'dev', self._veth_name)
                #arping my gateway, cause the gateway to flush the ARP cache for my IP address
                try:
                    nsenter('-t', self._attach_to_container_pid,
                            '-n', 'ping', '-c', '1', gateway)
                except Exception as e:
                    logger.warning(e.message)

        return self
