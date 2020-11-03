#!/usr/bin/env python

import ast
import yaml
import time

from ansible.module_utils.basic import AnsibleModule
from ansible.utils.display import Display
from ansible import constants

ANSIBLE_METADATA = {
    'metadata_version': '4',
    'supported_by': 'synthesio',
    'status': ['preview']
}

DOCUMENTATION = '''
---
module: ovh
short_description: Manage OVH API for DNS, monitoring and Dedicated servers
description:
    - Add/Delete/Modify entries in OVH DNS.
    - Add reverse on OVH dedicated servers.
    - Install new dedicated servers from a template (both OVH and personal ones).
    - Create a personal OVH template from a file (with h/w and s/w raid support).
    - Monitor installation status on dedicated servers.
    - Add/Remove OVH Monitoring on dedicated servers.
    - Add/Remove a dedicated server from a OVH vrack.
    - Restart a dedicate server on debian rescue or disk.
    - List dedicated servers, personal templates.
    - Create a template from a yml file inside an ansible role (see README).
    - Terminate a dedicated server (doesn't confirm termination, has to be done manually).
author: Francois BRUNHES and Synthesio SRE Team
notes:
    - "In /etc/ovh.conf (on host that executes module), you should add your
      OVH API credentials like:
      [default]
      ; general configuration: default endpoint
      endpoint=ovh-eu

      [ovh-eu]
      ; configuration specific to 'ovh-eu' endpoint
      application_key=<YOUR APPLICATION KEY>
      application_secret=<YOUR APPLICATIOM SECRET>
      consumer_key=<YOUR CONSUMER KEY>

    Or you can provide these values as module's attributes."
requirements:
    - ovh >= 0.4.8
options:
    endpoint:
            required: false
            description: The API endpoint to use
    application_key:
            required: false
            description: The application key to use to connect to the API
    application_secret:
            required: false
            description: The application secret to use to connect to the API
    consumer_key:
            required: false
            description: The consumer key to use to connect to the API
    name:
        required: true
        description: The name of the service (dedicated, dns)
    state:
        required: false
        default: present
        choices: ['present', 'absent']
        description:
            - Determines whether the dedicated/dns is to be created/updated
              or deleted
    service:
        required: true
        choices: ['boot', 'dns', 'vrack', 'reverse', 'monitoring', 'install',
                  'status', 'list', 'template', 'terminate', 'get_mac']
        description:
            - Determines the service you want to use in the module.
            - boot, change the bootid and can reboot the dedicated server.
            - dns, manage A entries in your domain.
            - vrack, add or remove a dedicated from a vrack.
            - reverse, add/modify a reverse on a dedicated server.
            - monitoring, add/removing a dedicated server from OVH monitoring.
            - install, install from a template.
            - status, used after install to know install status.
            - list, get a list of personal dedicated servers, personal templates.
            - template, create/delete an ovh template from a yaml file.
            - terminate, give back a dedicated server to OVH.
            - get_mac, get mac address.
    domain:
        required: false
        default: None
        description:
            - The domain used in dns and reverse services
    ip:
        required: false
        default: None
        description:
            - The public IP used in reverse and dns services
    vrack:
        required: false
        default: None
        description:
            - The vrack ID used in vrack service
    boot:
        required: false
        default: harddisk
        choices: ['harddisk','rescue']
        description:
            - Which way you want to boot your dedicated server
    force_reboot:
        required: false
        default: no
        choices: ['yes','no','true','false']
        description:
            - When you want to restart a dedicated server without changing his boot mode
    template:
        required: false
        default: None
        description:
            - One of your personal template on OVH
    hostname:
        required: false
        default: None
        description:
            - The hostname you want to replace in /etc/hostname when applying a template
    link_type:
        required: false
        default: private
        description:
            - The interface type you want to detect
    max_retry:
        required: false
        default: 10
        description:
            - Number of tries for the operation to suceed. OVH api can be lazy.
    post_installation_script_link:
        required: false
        default: None
        description:
            - Indicate the URL where your postinstall customisation script is located
    sleep:
        required: false
        default: 10
        description:
            - seconds between two tries
'''  # noqa

EXAMPLES = '''
- name: Add server to vrack
  ovh:
    service: vrack
    vrack: "{{ vrackid }}"
    name: "{{ ovhname }}"

- name: Add server IP to DNS
  ovh:
    service: dns
    domain: "example.com"
    ip: "192.0.2.1"
    name: "internal.bar"

- name: Refresh domain
  ovh:
    service: dns
    name: refresh
    domain: "example.com"

- name: Change Reverse on server
  ovh:
    service: reverse
    name: "internal.bar"
    ip: "192.0.2.1"
    domain: "example.com"

- name: Install the dedicated server
  ovh:
    service: install
    name: "{{ ovhname }}"
    hostname: "{{ inventory_hostname }}.{{ domain }}"
    template: "{{ template }}"

- name: Wait until installation is finished
  ovh:
    service: status
    name: "{{ ovhname }}"
'''

RETURN = ''' # '''

try:
    import ovh
    import ovh.exceptions
    from ovh.exceptions import APIError
    HAS_OVH = True
except ImportError:
    HAS_OVH = False

display = Display()


def main():
    argument_spec = dict(
        endpoint=dict(required=False, default=None),
        application_key=dict(required=False, default=None),
        application_secret=dict(required=False, default=None),
        consumer_key=dict(required=False, default=None),
        state=dict(default='present', choices=['present', 'absent']),
        name=dict(required=True),
        service=dict(choices=['boot', 'dns', 'vrack', 'reverse', 'monitoring',
                              'install', 'status', 'list', 'template',
                              'terminate', 'getmac'], required=True),
        domain=dict(required=False, default=None),
        ip=dict(required=False, default=None),
        vrack=dict(required=False, default=None),
        boot=dict(default='harddisk', choices=['harddisk', 'rescue']),
        force_reboot=dict(required=False, type='bool', default=False),
        template=dict(required=False, default=None),
        post_installation_script_link=dict(required=False, default=None),
        hostname=dict(required=False, default=None),
        max_retry=dict(required=False, default='10'),
        sleep=dict(required=False, default='10'),
        ssh_key_name=dict(required=False, default=None),
        use_distrib_kernel=dict(required=False, type='bool', default=False),
        link_type=dict(required=False, default='private',
                       choices=['public', 'private'])
    )

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True
    )

    om = OVHModule(module, module.check_mode, module.params)
    error, changed, result = om.run()
    if error is None:
        module.exit_json(changed=changed, **result)
    else:
        module.fail_json(msg=error, **result)


class OVHModule:

    def __init__(self, module, check_mode, params):
        self.module = module
        self.check_mode = check_mode
        self.params = params
        self.client = None

    def run(self):
        """Return error, changed, result"""
        if not HAS_OVH:
            return self.fail('OVH Api wrapper not installed')

        credentials = ['endpoint', 'application_key',
                       'application_secret', 'consumer_key']
        credentials_in_parameters = [
            cred in self.params for cred in credentials]
        try:
            if all(credentials_in_parameters):
                self.client = ovh.Client(
                    **{credential: self.params[credential] for credential in credentials})  # noqa
            else:
                self.client = ovh.Client()
        except APIError as api_error:
            return self.fail("Failed to call OVH API: {0}".format(api_error))

        choice_map = dict(
            dns=self.change_dns,
            getmac=self.get_mac,
            terminate=self.terminate_server,
            status=self.get_status_install,
            install=self.launch_install,
            monitoring=self.change_monitoring,
            reverse=self.change_reverse,
            list=self.list_service,
            boot=self.change_boot_dedicated,
            template=self.generate_template,
            vrack=self.change_vrack,
        )

        return choice_map.get(self.params['service'])()

    def fail(self, message):
        return message, False, {}

    def succeed(self, message, changed=True, contents=None, objects=None):
        result = {}
        if message is not None:
            result['msg'] = message
        if contents is not None:
            result['contents'] = contents
        if objects is not None:
            result['objects'] = objects

        return None, changed, result

    def change_dns(self):
        domain = self.params['domain']
        ip = self.params['ip']
        name = self.params['name']
        state = self.params['state']

        msg = ''

        if not domain:
            return self.fail("Please give a domain to add your target")

        if name == 'refresh':
            if self.check_mode:
                return self.succeed(
                    "Domain {} succesfully refreshed! - (dry run mode)".format(
                        domain),
                    changed=True)

            try:
                self.client.post(
                    '/domain/zone/%s/refresh' % domain
                )
                return self.succeed(
                    "Domain {} succesfully refreshed !".format(domain),
                    changed=True)
            except APIError as api_error:
                return self.fail(
                    "Failed to call OVH API: {0}".format(api_error))

        if self.check_mode:
            return self.succeed(
                "DNS succesfully {} on {}s - (dry run mode)".format(
                    state, name),
                changed=True)

        try:
            existing_records = self.client.get(
                '/domain/zone/%s/record' % domain,
                fieldType='A',
                subDomain=name
            )
        except APIError as api_error:
            return self.fail("Failed to call OVH API: {0}".format(api_error))

        if state == 'present':
            if not ip:
                return self.fail("Please give an IP to add your target")

            # At least one record already exists
            if existing_records:
                for ind in existing_records:
                    try:
                        record = self.client.get(
                            '/domain/zone/%s/record/%s' % (domain, ind)
                        )
                        # The record alredy exist
                        if record.get('subDomain') == name and record.get('target') == ip:  # noqa
                            return self.succeed(
                                "{} is already registered in domain {}".format(
                                    name, domain),
                                changed=False)
                    except APIError as api_error:
                        return self.fail(
                            "Failed to call OVH API: {0}".format(api_error))

                # Gatekeeper: if more than one record match the query,
                # don't update anything and fail
                if len(existing_records) > 1:
                    return self.fail(
                        "More than one record match the name {} in domain {}, this module won't update all of these records.".format(name, domain))  # noqa

                # Update the record if needed:
                # Was only done before when state=='modified'
                try:
                    ind = existing_records[0]
                    self.client.put(
                        '/domain/zone/%s/record/%s' % (domain, ind),
                        subDomain=name,
                        target=ip
                    )
                    msg = ('{ "fieldType": "A", "id": "%s", "subDomain": "%s", "target": "%s", "zone": "%s" } '  # noqa
                           % (ind, name, ip, domain))
                    return self.succeed(msg, changed=True)
                except APIError as api_error:
                    return self.fail(
                        "Failed to call OVH API: {0}".format(api_error))

            # The record does not exist yet
            try:
                result = self.client.post(
                    '/domain/zone/%s/record' % domain,
                    fieldType='A',
                    subDomain=name,
                    target=ip
                )
                return self.succeed(message=None,
                                    contents=result,
                                    changed=True)
            except APIError as api_error:
                return self.fail(
                    "Failed to call OVH API: {0}".format(api_error))

        elif state == 'absent':
            if not existing_records:
                return self.succeed(
                    "Target {} doesn't exist on domain {}".format(
                        name, domain),
                    changed=False)

            record_deleted = []
            try:
                for ind in existing_records:
                    record = self.client.get(
                        '/domain/zone/%s/record/%s' % (domain, ind)
                    )
                    self.client.delete(
                        '/domain/zone/%s/record/%s' % (domain, ind)
                    )
                    record_deleted.append("%s IN A %s" % (
                        record.get('subDomain'), record.get('target')))
                return self.succeed(
                    ",".join(record_deleted) +
                    " successfuly deleted from domain {}".format(domain),
                    changed=True)
            except APIError as api_error:
                return self.fail(
                    "Failed to call OVH API: {0}".format(api_error))

    def get_mac(self):
        name = self.params['name']
        link_type = self.params['link_type']
        result = self.client.get(
            '/dedicated/server/%s/networkInterfaceController?linkType=%s' % (
                name, link_type)
        )
        return self.succeed(result, changed=False)

    def terminate_server(self):
        name = self.params['name']

        if not name:
            return self.fail("Please give a dedicated name to terminate")

        if self.check_mode:
            return self.succeed(
                "Terminate {} is done, please confirm via the email sent - (dry run mode)".format(name),  # noqa
                changed=True)

        try:
            self.client.post(
                '/dedicated/server/%s/terminate' % name
            )
            return self.succeed(
                "Terminate {} is done, please confirm via the email sent".format(name),  # noqa
                changed=True)
        except APIError as api_error:
            return self.fail("Failed to call OVH API: {0}".format(api_error))

    def get_status_install(self):
        name = self.params['name']
        max_retry = self.params['max_retry']
        sleep = self.params['sleep']

        if not name:
            return self.fail("Please provide 'ns' server name from which installation status will be check")  # noqa

        if self.check_mode:
            return self.succeed("done - (dry run mode)", changed=False)

        for i in range(1, int(max_retry)):
            # Messages cannot be displayed in real time (yet)
            # https://github.com/ansible/proposals/issues/92
            display.display("%i out of %i" %
                            (i, int(max_retry)), constants.COLOR_VERBOSE)
            try:
                tasklist = self.client.get(
                    '/dedicated/server/%s/task' % name,
                    function='reinstallServer')
                result = self.client.get(
                    '/dedicated/server/%s/task/%s' % (name, max(tasklist)))
            except APIError as api_error:
                return self.fail(
                    "Failed to call OVH API: {0}".format(api_error))

            message = ""
            # Get more details in installation progression
            if "done" in result['status']:
                return self.succeed("%s: %s" % (result['status'], message),
                                    changed=False)

            progress_status = self.client.get(
                '/dedicated/server/%s/install/status' % name
            )
            if 'message' in progress_status and progress_status['message'] == 'Server is not being installed or reinstalled at the moment':  # noqa
                message = progress_status['message']
            else:
                for progress in progress_status['progress']:
                    if progress["status"] == "doing":
                        message = progress['comment']
            display.display("%s: %s" % (
                result['status'], message), constants.COLOR_VERBOSE)
            time.sleep(float(sleep))
        return self.fail(
            "Max wait time reached, about %i x %i seconds" % (i, int(sleep)))

    def launch_install(self):
        name = self.params['name']
        template = self.params['template']
        hostname = self.params['hostname']
        ssh_key_name = self.params.get('ssh_key_name')
        use_distrib_kernel = self.params.get('use_distrib_kernel', False)
        post_installation_script_link = self.params['post_installation_script_link']

        if not name:
            return self.fail(
                "Please give the service's name you want to install")
        if not template:
            return self.fail("Please give a template to install")
        if not hostname:
            return self.fail("Please give a hostname for your installation")

        try:
            compatible_templates = self.client.get(
                '/dedicated/server/%s/install/compatibleTemplates' % name
            )
            compatible_templates = set(
                [tpl
                 for template_type in compatible_templates.keys()
                 for tpl in compatible_templates[template_type]])
            if template not in compatible_templates:
                return self.fail(
                    "%s doesn't exist in compatibles templates" % template)
        except APIError as api_error:
            return self.fail("Failed to call OVH API: {0}".format(api_error))

        if self.check_mode:
            return self.succeed(
                "Installation in progress on {} ! - (dry run mode)".format(name),  # noqa
                changed=True)

        details = {"details": {"language": "en",
                               "customHostname": hostname},
                   "templateName": template}
        if ssh_key_name:
            try:
                result = self.client.get('/me/sshKey')
                if ssh_key_name not in result:
                    return self.fail(
                        "%s doesn't exist in public SSH keys" % ssh_key_name)
                else:
                    details['details']['sshKeyName'] = ssh_key_name
            except APIError as api_error:
                return self.fail(
                    "Failed to call OVH API: {0}".format(api_error))
        if use_distrib_kernel:
            details['details']['useDistribKernel'] = use_distrib_kernel

        if post_installation_script_link:
            details['details']['postInstallationScriptLink'] = post_installation_script_link

        try:
            self.client.post(
                '/dedicated/server/%s/install/start' % name, **details)
            # TODO
            # check if details are still properly formed,
            # even for a HW Raid config.
            # For instance:
            # {'details': {'customHostname': 'test01.test.synthesio.net',
            #              'diskGroupId': None,
            #              'installSqlServer': False,
            #              'language': 'en',
            #              'noRaid': False,
            #              'postInstallationScriptLink': None,
            #              'postInstallationScriptReturn': None,
            #              'resetHwRaid': False,
            #              'softRaidDevices': None,
            #              'sshKeyName': 'deploy',
            #              'useDistribKernel': True,
            #              'useSpla': False},
            #  'templateName': 'test'}
            return self.succeed(
                "Installation in progress on {} !".format(name), changed=True)
        except APIError as api_error:
            return self.fail("Failed to call OVH API: {0}".format(api_error))

    def change_monitoring(self):
        name = self.params['name']
        state = self.params['state']
        max_retry = self.params['max_retry']
        sleep = self.params['sleep']

        if not name:
            return self.fail("Please give a name to change monitoring state")
        if not state:
            return self.fail("Please give a state for your monitoring")

        if state == 'present':
            shouldbe = True
        elif state == 'absent':
            shouldbe = False
        else:
            return self.fail(
                "State %s does not match 'present' or 'absent'" % state)

        if self.check_mode:
            return self.succeed(
                "Monitoring %s on %s - (dry run mode)" % (state, name),
                changed=True)

        for i in range(1, int(max_retry)):
            server_state = self.client.get(
                '/dedicated/server/%s' % name
            )

            if server_state['monitoring'] == shouldbe:
                if shouldbe:
                    return self.succeed(
                        "Monitoring activated on {} after {} time(s)".format(
                            name, i),
                        changed=True)
                else:
                    return self.succeed(
                        "Monitoring deactivated on {} after {} time(s)".format(
                            name, i),
                        changed=True)

            try:
                self.client.put(
                    '/dedicated/server/%s' % name, monitoring=shouldbe
                )
            except APIError as api_error:
                return self.fail(
                    "Failed to call OVH API: {0}".format(api_error))
            time.sleep(float(sleep))
        return self.fail("Could not change monitoring flag")

    def change_reverse(self):
        name = self.params['name']
        domain = self.params['domain']
        ip = self.params['ip']

        if not domain:
            return self.fail("Please give a domain to add your target")
        if not ip:
            return self.fail("Please give an IP to add your target")

        fqdn = name + '.' + domain + '.'
        result = {}
        try:
            result = self.client.get('/ip/%s/reverse/%s' % (ip, ip))
        except ovh.exceptions.ResourceNotFoundError:
            result['reverse'] = ''

        if result['reverse'] == fqdn:
            return self.succeed("Reverse already set", changed=False)

        if self.check_mode:
            return self.succeed(
                "Reverse {} to {} succesfully set ! - (dry run mode)".format(
                    ip, fqdn),
                changed=True)
        try:
            self.client.post(
                '/ip/%s/reverse' % ip,
                ipReverse=ip,
                reverse=fqdn
            )
            return self.succeed(
                "Reverse {} to {} succesfully set !".format(ip, fqdn),
                changed=True)
        except APIError as api_error:
            return self.fail("Failed to call OVH API: {0}".format(api_error))

    def list_service(self):
        name = self.params['name']

        if name == 'dedicated':
            return self.list_dedicated()
        elif name == 'templates':
            return self.list_templates()
        else:
            return self.fail("%s not supported for 'list' service" % name)

    def list_dedicated(self):
        customlist = []
        try:
            result = self.client.get(
                '/dedicated/server'
            )
        except APIError as api_error:
            return self.fail("Failed to call OVH API: {0}".format(api_error))

        try:
            for i in result:
                test = self.client.get(
                    '/dedicated/server/%s' % i
                )
                customlist.append('%s=%s' % (test['reverse'], i))
        except APIError as api_error:
            return self.fail("Failed to call OVH API: {0}".format(api_error))

        return self.succeed(message=None, changed=False, objects=customlist)

    def list_templates(self):
        customlist = []
        try:
            result = self.client.get(
                '/me/installationTemplate'
            )
        except APIError as api_error:
            return self.fail("Failed to call OVH API: {0}".format(api_error))

        try:
            for i in result:
                if 'tmp-mgr' not in i:
                    customlist.append(i)
        except APIError as api_error:
            return self.fail("Failed to call OVH API: {0}".format(api_error))

        return self.succeed(message=None, changed=False, objects=customlist)

    def change_boot_dedicated(self):
        name = self.params['name']
        boot = self.params['boot']
        force_reboot = self.params['force_reboot']

        bootid = {'harddisk': 1, 'rescue': 1122}
        if self.check_mode:
            return self.succeed(
                "{} is now set to boot on {}. Reboot in progress... - (dry run mode)".format(name, boot),  # noqa
                changed=True)

        try:
            check = self.client.get(
                '/dedicated/server/%s' % name
            )
        except APIError as api_error:
            return self.fail("Failed to call OVH API: {0}".format(api_error))

        if bootid[boot] != check['bootId']:
            try:
                self.client.put(
                    '/dedicated/server/%s' % name,
                    bootId=bootid[boot]
                )
            except APIError as api_error:
                return self.fail(
                    "Failed to call OVH API: {0}".format(api_error))
            return self.succeed(
                "{} is now set to boot on {}.".format(name, boot),
                changed=True)

        if force_reboot:
            try:
                self.client.post(
                    '/dedicated/server/%s/reboot' % name
                )
            except APIError as api_error:
                return self.fail(
                    "Failed to call OVH API: {0}".format(api_error))
            return self.succeed("%s is now rebooting on %s" % (name, boot))

        return self.succeed(
            "{} already configured for boot on {}".format(name, boot),
            changed=False)

    def generate_template(self):
        name = self.params['name']
        template = self.params['template']
        state = self.params['state']

        if not template:
            return self.fail("No template parameter given")

        if self.check_mode:
            return self.succeed(
                "%s succesfully %s on ovh API - (dry run mode)".format(
                    template, state),
                changed=True)

        if state not in ['present', 'absent']:
            return self.fail(
                "State %s not supported. Only present/absent" % state)

        src = template
        with open(src, 'r') as stream:
            content = yaml.load(stream)
        conf = {}
        for i, j in content.items():
            conf[i] = j

        if state == 'absent':
            try:
                self.client.delete(
                    '/me/installationTemplate/%s' % conf['templateName']
                )
            except APIError as api_error:
                return self.fail(
                    "Failed to call OVH API: {0}".format(api_error))
            return self.succeed(
                "Template {} succesfully deleted".format(conf['templateName']),
                changed=True)

        # state == 'present'
        try:
            result = self.client.post(
                '/me/installationTemplate',
                baseTemplateName=conf['baseTemplateName'],
                defaultLanguage=conf['defaultLanguage'],
                name=conf['templateName']
            )
        except APIError as api_error:
            return self.fail("Failed to call OVH API: {0}".format(api_error))

        templates = {
            'customization': {
                "customHostname": conf['customHostname'],
                "postInstallationScriptLink": conf['postInstallationScriptLink'],  # noqa
                "postInstallationScriptReturn": conf['postInstallationScriptReturn'],  # noqa
                "sshKeyName": conf['sshKeyName'],
                "useDistributionKernel": conf['useDistributionKernel']},
            'defaultLanguage': conf['defaultLanguage'],
            'templateName': conf['templateName']}
        try:
            result = self.client.put(
                '/me/installationTemplate/{}'.format(conf['templateName']),
                **templates
            )
        except APIError as api_error:
            return self.fail("Failed to call OVH API: {0}".format(api_error))

        try:
            result = self.client.post(
                '/me/installationTemplate/{}/partitionScheme'.format(
                    conf['templateName']),
                name=conf['partitionScheme'],
                priority=conf['partitionSchemePriority']
            )
        except APIError as api_error:
            return self.fail("Failed to call OVH API: {0}".format(api_error))

        if conf['isHardwareRaid']:
            result = self.client.get(
                '/dedicated/server/%s/install/hardwareRaidProfile' % name
            )

            if len(result['controllers']) != 1:
                return self.fail(
                    "Failed to call OVH API: {0} Code can't handle more than one controller when using Hardware Raid setups")  # noqa

            # XXX: Only works with a server who has one controller.
            # All the disks in this controller are taken to form one raid
            # In the future, some of our servers could have more than one controller  # noqa
            # so we will have to adapt this code
            disks = result['controllers'][0]['disks'][0]['names']

            # if 'raid 1' in conf['raidMode']:
            # TODO : create a list of disks like this
            # {'disks': ['[c0:d0,c0:d1]',
            #            '[c0:d2,c0:d3]',
            #            '[c0:d4,c0:d5]',
            #            '[c0:d6,c0:d7]',
            #            '[c0:d8,c0:d9]',
            #            '[c0:d10,c0:d11]'],
            #  'mode': 'raid10',
            #  'name': 'managerHardRaid',
            #  'step': 1}
            # else:
            # TODO : for raid 0, it's assumed that
            # a simple list of disks would be sufficient
            try:
                result = self.client.post(
                    '/me/installationTemplate/%s/partitionScheme/%s/hardwareRaid' % (  # noqa
                        conf['templateName'], conf['partitionScheme']),
                    disks=disks,
                    mode=conf['raidMode'],
                    name=conf['partitionScheme'],
                    step=1)
            except APIError as api_error:
                return self.fail(
                    "Failed to call OVH API: {0}".format(api_error))

        partition = {}
        for k in conf['partition']:
            partition = ast.literal_eval(k)
            try:
                if 'raid' in partition.keys():
                    self.client.post(
                        '/me/installationTemplate/%s/partitionScheme/%s/partition' % (  # noqa
                            conf['templateName'], conf['partitionScheme']),
                        filesystem=partition['filesystem'],
                        mountpoint=partition['mountpoint'],
                        raid=partition['raid'],
                        size=partition['size'],
                        step=partition['step'],
                        type=partition['type'])
                else:
                    self.client.post(
                        '/me/installationTemplate/%s/partitionScheme/%s/partition' % (  # noqa
                            conf['templateName'], conf['partitionScheme']),
                        filesystem=partition['filesystem'],
                        mountpoint=partition['mountpoint'],
                        size=partition['size'],
                        step=partition['step'],
                        type=partition['type'])
            except APIError as api_error:
                return self.fail(
                    "Failed to call OVH API: {0}".format(api_error))
        try:
            self.client.post(
                '/me/installationTemplate/%s/checkIntegrity' % conf['templateName'])  # noqa
        except APIError as api_error:
            return self.fail("Failed to call OVH API: {0}".format(api_error))

        return self.succeed(
            "Template {} succesfully created".format(conf['templateName']),
            changed=True)

    def change_vrack(self):
        name = self.params['name']
        state = self.params['state']
        vrack = self.params['vrack']

        if not vrack:
            return self.fail(
                "Please give a vrack name to add/remove your server")

        if state not in ['present', 'absent']:
            return self.succeed(
                "Vrack service only uses present/absent state", changed=False)

        if self.check_mode:
            return self.succeed(
                "{} succesfully {} on {} - (dry run mode)".format(
                    name, state, vrack),
                changed=True)

        if state == 'present':
            try:
                # There is no easy way to know if the server is
                # on an old or new network generation.
                # So we need to call this new route
                # to ask for virtualNetworkInterface
                # and if the answer is empty, it's on a old generation.
                # The /vrack/%s/allowedServices route used previously
                # has availability and scaling problems.
                result = self.client.get(
                    '/dedicated/server/%s/virtualNetworkInterface' % name,
                    mode='vrack'
                )
            except APIError as api_error:
                return self.fail(
                    "Failed to call OVH API: {0}".format(api_error))

# XXX: In a near future, OVH will add the possibility to add
# multiple interfaces to the same VRACK or another one
# This code may break at this moment because
# each server will have a list of dedicatedServerInterface

            # New generation
            if len(result):
                try:
                    is_already_registered = self.client.get(
                        '/vrack/%s/dedicatedServerInterfaceDetails' % vrack
                    )
                except APIError as api_error:
                    return self.fail(
                        "Failed to call OVH API: {0}".format(api_error))

                for new_server in is_already_registered:
                    if new_server['dedicatedServer'] == name:
                        return self.succeed(
                            "{} is already registered on {}".format(
                                name, vrack),
                            changed=False)
                try:
                    server_interface = "".join(result)
                    result2 = self.client.post(
                        '/vrack/%s/dedicatedServerInterface' % vrack,
                        dedicatedServerInterface=server_interface
                    )
                    return self.succeed(None, contents=result2, changed=True)
                except APIError as api_error:
                    return self.fail(
                        "Failed to call OVH API: {0}".format(api_error))
            # Old generation
            else:
                try:
                    is_already_registered = self.client.get(
                        '/vrack/%s/dedicatedServer' % vrack
                    )
                except APIError as api_error:
                    return self.fail(
                        "Failed to call OVH API: {0}".format(api_error))

                for old_server in is_already_registered:
                    if old_server == name:
                        return self.succeed(
                            "{} is already registered on {}".format(
                                name, vrack),
                            changed=False)

                try:
                    result2 = self.client.post(
                        '/vrack/%s/dedicatedServer' % vrack,
                        dedicatedServer=name
                    )
                    return self.succeed(None, contents=result2, changed=True)
                except APIError as api_error:
                    return self.fail(
                        "Failed to call OVH API: {0}".format(api_error))

        elif state == 'absent':
            try:
                result_new = self.client.get(
                    '/vrack/%s/dedicatedServerInterfaceDetails' % vrack
                )
                result_old = self.client.get(
                    '/vrack/%s/dedicatedServer' % vrack
                )
            except APIError as api_error:
                return self.fail(
                    "Failed to call OVH API: {0}".format(api_error))

            for new_server in result_new:
                if new_server['dedicatedServer'] == name:
                    try:
                        result = self.client.delete(
                            '/vrack/%s/dedicatedServerInterface/%s' % (
                                vrack, new_server['dedicatedServerInterface'])
                        )
                        return self.succeed(None, contents=result,
                                            changed=True)
                    except APIError as api_error:
                        return self.fail(
                            "Failed to call OVH API: {0}".format(api_error))

            for old_server in result_old:
                if old_server == name:
                    try:
                        result = self.client.delete(
                            '/vrack/%s/dedicatedServer/%s' % (vrack, name)
                        )
                        return self.succeed(None, contents=result,
                                            changed=True)
                    except APIError as api_error:
                        return self.fail(
                            "Failed to call OVH API: {0}".format(api_error))

            return self.succeed("No %s in %s" % (name, vrack), changed=False)


if __name__ == '__main__':
    main()
