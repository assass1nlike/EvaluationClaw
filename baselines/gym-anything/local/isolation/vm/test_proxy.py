import socket
import ipaddress
from unittest.mock import patch

import pytest

from proxy import resolve_public


@pytest.mark.parametrize('host,port', [
    ('127.0.0.1',80), ('::1',443), ('10.0.2.2',80), ('169.254.169.254',80),
    ('api.deepseek.com.attacker.test',443), ('example.com',443), ('api.deepseek.com',22),
])
def test_denied_destinations_are_not_resolved(host, port):
    with patch('socket.getaddrinfo') as resolver:
        with pytest.raises(ValueError):
            resolve_public(host,port)
        resolver.assert_not_called()


@pytest.mark.parametrize('ip', ['127.0.0.1','10.0.0.1','192.168.1.1','169.254.169.254','::1','::ffff:127.0.0.1','224.0.0.1','ff02::1'])
def test_allowed_name_cannot_resolve_to_private_address(ip):
    answers=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('1.1.1.1',443)),
             (socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,443))]
    with patch('socket.getaddrinfo',return_value=answers):
        with pytest.raises(ValueError):
            resolve_public('api.deepseek.com',443)


def test_returns_validated_ip_instead_of_resolving_again_upstream():
    with patch('socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('1.1.1.1',443))]):
        assert resolve_public('api.deepseek.com',443)=='1.1.1.1'


def test_globally_routable_local_network_is_still_denied():
    with patch('proxy.LOCAL_NETWORKS', [ipaddress.ip_network('101.6.89.0/24')]), \
         patch('socket.getaddrinfo', return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('101.6.89.139',443))]):
        with pytest.raises(ValueError):
            resolve_public('api.deepseek.com',443)
