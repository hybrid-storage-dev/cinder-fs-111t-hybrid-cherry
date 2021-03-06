# vim: tabstop=4 shiftwidth=4 softtabstop=4

"""
[VRM DRIVER] VRM CLIENT.

"""
import json
import urlparse

import requests
from oslo.config import cfg
from FSComponentUtil import crypt
from cinder.openstack.common import log as logging
from cinder.volume.drivers.huawei.vrm import exception as driver_exception
from cinder.openstack.common.gettextutils import _
from cinder.volume.drivers.huawei.vrm.conf import FC_DRIVER_CONF
from cinder.volume.drivers.huawei.vrm import utils as apiutils


try:
    from eventlet import sleep
except ImportError:
    from time import sleep

TASK_WAITING = 'waiting'
TASK_RUNNING = 'running'
TASK_SUCCESS = 'success'
TASK_FAILED = 'failed'
TASK_CANCELLING = 'cancelling'
TASK_UNKNOWN = 'unknown'

CONF = cfg.CONF

LOG = logging.getLogger(__name__)


class VRMHTTPClient(object):
    """Executes volume driver commands on VRM."""

    USER_AGENT = 'VRM-HTTP-Client for OpenStack'
    RESOURCE_URI = 'uri'
    TASK_URI = 'taskUri'
    BASIC_URI = '/service'
    vrm_commands = None

    def __init__(self):
        '''
        __init__

        :return:
        '''
        fc_ip = FC_DRIVER_CONF.fc_ip
        fc_image_path = FC_DRIVER_CONF.fc_image_path
        fc_user = FC_DRIVER_CONF.fc_user
        fc_pwd = FC_DRIVER_CONF.fc_pwd_for_cinder
        self.ssl = CONF.vrm_ssl
        self.host = fc_ip
        self.port = CONF.vrm_port
        self.user = fc_user
        self.userType = CONF.vrm_usertype
        self.password = apiutils.sha256_based_key(fc_pwd)
        self.retries = CONF.vrm_retries
        self.timeout = CONF.vrm_timeout
        self.limit = CONF.vrm_limit
        self.image_url = fc_image_path
        self.image_type = '.xml'

        self.versions = None
        self.version = None
        self.auth_uri = None
        self.auth_url = None

        self.auth_token = None

        self.sites = None
        self.site_uri = None
        self.site_urn = None
        self.site_url = None

        self.shared_hosts = None
        self.shared_datastores = None
        self.shared_volumes = None

    def _generate_url(self, path, query=None, frag=None):
        '''
        _generate_url

        :param path:
        :param query:
        :param frag:
        :return:
        '''
        LOG.debug(_("[BRM-DRIVER] start _generate_url(%s) "), path)
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
        LOG.debug(_("[BRM-DRIVER] end _generate_url [%s] "), url)
        return url

    def _http_log_req(self, args, kwargs):
        '''
        _http_log_req

        :param args:
        :param kwargs:
        :return:
        '''
        string_parts = ['\n curl -i']
        for element in args:
            if element in ('GET', 'POST', 'DELETE', 'PUT'):
                string_parts.append(' -X %s' % element)
            else:
                string_parts.append(' %s' % element)

        for element in kwargs['headers']:
            header = ' -H "%s: %s"' % (element, kwargs['headers'][element])
            string_parts.append(header)
            LOG.info(_("[VRM-CINDER] element [%s]"), element)

        if 'body' in kwargs:
            string_parts.append(" -d '%s'" % (kwargs['body']))


    def _http_log_resp(self, resp):
        '''
        _http_log_resp

        :param resp:
        :return:
        '''
        try:
            if resp.status_code:
                LOG.debug(_("RESP status_code: [%s]"), resp.status_code)


            if resp.content:
                LOG.debug(_("RESP content: [%s]"), resp.content)
        except Exception:
            LOG.debug(_("[VRM-CINDER] _http_log_resp exception"))

    def request(self, url, method, **kwargs):
        '''
        request

        :param url:
        :param method:
        :param kwargs:
        :return:
        '''
        LOG.info(_("[VRM-CINDER] request (%s)[%s]"), method, url)
        auth_attempts = 0
        attempts = 0
        step = 1
        while True:
            step *= 2
            attempts += 1
            LOG.info(_("[VRM-CINDER] request (%s)[%s]"), method, url)
            if not self.auth_url or not self.auth_token or not self.site_uri:
                LOG.info(_("[VRM-CINDER] auth_url is none. "))

            kwargs.setdefault('headers', {})['X-Auth-Token'] = self.auth_token
            try:
                LOG.info(_("[VRM-CINDER] request (%s)[%s]"), method, url)
                resp, body = self.try_request(url, method, **kwargs)
                return resp, body

            except driver_exception.Unauthorized:
                if auth_attempts > 10:
                    LOG.info(_("[VRM-CINDER] request (%s)[%s]"), method, url)
                    raise driver_exception.ClientException(101)
                LOG.debug("Unauthorized, reauthenticating.")
                self.auth_url = None
                self.auth_token = None
                attempts -= 1
                auth_attempts += 1
                sleep(step)
                self.authenticate()
                continue
            except driver_exception.ClientException as ex:
                if attempts > self.retries:
                    LOG.info(_("[VRM-CINDER] ClientException "))
                    raise ex
                if 500 <= ex.code <= 599:
                    LOG.info(_("[VRM-CINDER] ClientException "))
                else:
                    LOG.info(_("[VRM-CINDER] ClientException "))
                    raise ex
            except requests.exceptions.ConnectionError as ex:

                LOG.debug("Connection refused: %s" % ex)
                raise ex
            LOG.debug(
                "Failed attempt(%s of %s), retrying in %s seconds" %
                (attempts, self.retries, step))
            sleep(step)


    def try_request(self, url, method, **kwargs):
        '''
        request

        :param url:
        :param method:
        :param kwargs:
        :return:
        '''
        LOG.debug(_("[VRM-CINDER] try_request url [%s]"), url)
        no_version = False
        if not self.version:
            no_version = True
        if url.endswith('session'):
            no_version = True

        kwargs.setdefault('headers', kwargs.get('headers', {}))
        kwargs['headers']['User-Agent'] = self.USER_AGENT
        if no_version:
            kwargs['headers']['Accept'] = 'application/json;charset=UTF-8'
        else:
            version = self.version.lstrip(' v')
            if url.endswith('/action/export'):
                export_version = FC_DRIVER_CONF.export_version
                version = '1.2' if export_version == 'v1.2' else self.version.lstrip(' v')
            kwargs['headers']['Accept'] = 'application/json;version=' + version + ';charset=UTF-8'
            kwargs['headers']['X-Auth-Token'] = self.auth_token
        kwargs['headers']['Accept-Language'] = 'zh_CN'
        if 'body' in kwargs:
            if kwargs['body'] and len(kwargs['body']) > 0:
                kwargs['headers']['Content-Type'] = 'application/json;charset=UTF-8'
                kwargs['data'] = kwargs['body']

            body = apiutils.str_drop_password_key(kwargs['body'])
            LOG.debug(_("[VRM-CINDER] request body [%s]"), body)
            del kwargs['body']

        LOG.debug(_("[VRM-CINDER] request header [%s]"), kwargs['headers']['Accept'])
        self._http_log_req((url, method,), kwargs)
        resp = requests.request(
            method,
            url,
            verify=False,
            **kwargs)
        self._http_log_resp(resp)

        if resp.content:
            try:
                body = json.loads(resp.content)
            except ValueError:
                body = None
        else:
            body = None
        LOG.info(_("[VRM-CINDER] request status_code [%d]"), resp.status_code)
        if resp.status_code >= 400:
            LOG.error(_("error response, error is %s"), body)
            raise driver_exception.exception_from_response(resp, body)

        return resp, body

    def _prepare_version_and_auth_url(self):
        '''
        _prepare_version_and_auth_url

        :return:
        '''
        LOG.debug(_("[VRM-CINDER] start _prepare_version_and_auth_url()"))
        self.version = CONF.vrm_version
        self.auth_uri = '/service/session'
        self.auth_url = self._generate_url(self.auth_uri)

        LOG.debug(_("[VRM-CINDER] end _prepare_version_and_auth_url(%s)"), self.version)

    def _prepare_auth_token(self):
        '''
        _prepare_auth_token

        :return:
        '''
        LOG.debug(_("[VRM-CINDER] start _prepare_auth_token()"))
        uri = '/service/session'
        new_url = self._generate_url(uri)
        self.auth_token = None
        headers = {'X-Auth-User': self.user,
                   'X-Auth-Key': self.password,
                   'X-Auth-UserType': self.userType, }
        resp, body = self.try_request(new_url, 'POST', headers=headers)
        if resp.status_code in (200, 204):
            self.auth_token = resp.headers['x-auth-token']
        LOG.debug(_("[VRM-CINDER] end _prepare_auth_token()"))

    def _prepare_site_uri(self):
        '''
        _prepare_site_uri

        :return:
        '''
        LOG.debug(_("[VRM-CINDER] start _prepare_site_uri()"))
        self.site_uri = self.site_urn = self.site_url = None
        url = self._generate_url('/sites')
        headers = {'X-Auth-Token': self.auth_token}

        resp, body = self.try_request(url, 'GET', headers=headers)
        if resp.status_code in (200, 204):
            self.sites = body['sites']
            if len(self.sites) == 1:
                self.site_uri = self.sites[0]['uri']
                self.site_urn = self.sites[0]['urn']
                self.site_url = self._generate_url(self.site_uri)
                return
            else:
                for si in self.sites:
                    if si['urn'] == FC_DRIVER_CONF.vrm_siteurn:
                        self.site_uri = si['uri']
                        self.site_urn = si['urn']
                        self.site_url = self._generate_url(self.site_uri)
                        return

                LOG.info(_("[VRM-CINDER] can not found site (%s)") % FC_DRIVER_CONF.vrm_siteurn)
                raise driver_exception.NotFound()


    def authenticate(self):
        '''
        authenticate

        :return:
        '''
        LOG.debug(_("[VRM-CINDER] start authenticate()"))
        self._prepare_version_and_auth_url()
        self._prepare_auth_token()
        self._prepare_site_uri()

        if not self.version:
            LOG.info(_("[VRM-CINDER] (%s)"), 'AuthorizationFailure')
            raise driver_exception.AuthorizationFailure
        if not self.auth_url:
            LOG.info(_("[VRM-CINDER] (%s)"), 'AuthorizationFailure')
            raise driver_exception.AuthorizationFailure
        if not self.site_uri:
            LOG.info(_("[VRM-CINDER] (%s)"), 'AuthorizationFailure')
            raise driver_exception.AuthorizationFailure


    def get_version(self):
        '''
        get_version

        :return:
        '''
        LOG.debug(_("[VRM-CINDER] start get_version()"))
        return self.version

    def get_siteurn(self):
        '''
        get_siteurn

        :return:
        '''
        LOG.debug(_("[VRM-CINDER] start get_siteurn()"))
        if self.site_uri is None:
            self.init()
        return self.site_urn

    def get_siteuri(self):
        '''
        get_siteurn

        :return:
        '''
        LOG.debug(_("[VRM-CINDER] start get_siteurn()"))
        if self.site_uri is None:
            self.init()
        return self.site_uri

    def init(self):
        '''
        init

        :return:
        '''
        LOG.debug(_("[VRM-CINDER] start init()"))
        self.authenticate()




