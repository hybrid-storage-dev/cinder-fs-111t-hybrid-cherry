# vim: tabstop=4 shiftwidth=4 softtabstop=4

"""
[VRM DRIVER] VRM CLIENT.

"""
import urlparse

from oslo.config import cfg
from cinder.openstack.common import log as logging
from cinder.openstack.common.gettextutils import _
from cinder.volume.drivers.huawei.vrm.conf import FC_DRIVER_CONF
from cinder.volume.drivers.huawei.vrm.http_client import VRMHTTPClient


TASK_WAITING = 'waiting'
TASK_RUNNING = 'running'
TASK_SUCCESS = 'success'
TASK_FAILED = 'failed'
TASK_CANCELLING = 'cancelling'
TASK_UNKNOWN = 'unknown'

CONF = cfg.CONF

LOG = logging.getLogger(__name__)


class BaseProxy(object):
    '''
    BaseProxy
    '''
    def __init__(self):
        '''

        :return:
        '''
        self.vrmhttpclient = VRMHTTPClient()

        self.site_uri = self.vrmhttpclient.get_siteuri()
        self.site_urn = self.vrmhttpclient.get_siteurn()
        self.limit = 100
        self.BASIC_URI = '/service'

    def _joined_params(self, params):
        '''

        :param params:
        :return:
        '''
        param_str = []
        for k, v in params.items():
            if (k is None) or (v is None) or len(k) == 0:
                continue
            if k == 'scope' and v == self.site_urn:
                continue
            param_str.append("%s=%s" % (k, str(v)))
        return '&'.join(param_str)

    def _generate_url(self, path, query=None, frag=None):
        '''

        :param path:
        :param query:
        :param frag:
        :return:
        '''
        LOG.info(_("[BRM-DRIVER] call _generate_url(%s) "), path)
        if CONF.vrm_ssl:
            scheme = 'https'
        else:
            scheme = 'http'
        fc_ip = FC_DRIVER_CONF.fc_ip


        netloc = str(fc_ip) + ':' + str(CONF.vrm_port)
        if path.startswith(self.BASIC_URI):
            url = urlparse.urlunsplit((scheme, netloc, path, query, frag))
        else:
            url = urlparse.urlunsplit((scheme, netloc, self.BASIC_URI + str(path), query, frag))
        LOG.info(_("[BRM-DRIVER] end _generate_url[%s] "), url)
        return url



