#    Copyright 2015 Mirantis, Inc.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


import os
import unittest
import time

from heatclient.v1.client import Client as heat_client
from keystoneclient.v2_0 import client as keystone_client
from neutronclient.v2_0 import client as neutron_client
from novaclient import client as nova_client
from glanceclient.v2 import client as glance_client


class WindowCompatibilityIntegrationTests(unittest.TestCase):
    """ Basic automated tests for OpenStack Windows Compatibility verification.
    """

    @classmethod
    def setUpClass(cls):
        OS_AUTH_URL = os.environ.get('OS_AUTH_URL')
        OS_USERNAME = os.environ.get('OS_USERNAME')
        OS_PASSWORD = os.environ.get('OS_PASSWORD')
        OS_TENANT_NAME = os.environ.get('OS_TENANT_NAME')
        OS_PROJECT_NAME = os.environ.get('OS_PROJECT_NAME')

        cls.keystone = keystone_client.Client(auth_url=OS_AUTH_URL,
                                              username=OS_USERNAME,
                                              password=OS_PASSWORD,
                                              tenat_name=OS_TENANT_NAME,
                                              project_name=OS_PROJECT_NAME)
        services = cls.keystone.service_catalog
        heat_endpoint = services.url_for(service_type='orchestration',
                                         endpoint_type='internalURL')

        cls.heat = heat_client(endpoint=heat_endpoint,
                               token=cls.keystone.auth_token)

        # Get path on node to 'templates' dir
        cls.templates_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'templates')
        # Get path on node to 'images' dir
        cls.images_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                'images')

        # Neutron connect
        cls.neutron = neutron_client.Client(username=OS_USERNAME,
                                            password=OS_PASSWORD,
                                            tenant_name=OS_TENANT_NAME,
                                            auth_url=OS_AUTH_URL,
                                            insecure=True)

        # Nova connect
        OS_TOKEN = cls.keystone.get_token(cls.keystone.session)
        RAW_TOKEN = cls.keystone.get_raw_token_from_identity_service(
                auth_url=OS_AUTH_URL,
                username=OS_USERNAME,
                password=OS_PASSWORD,
                tenant_name=OS_TENANT_NAME)
        OS_TENANT_ID = RAW_TOKEN['token']['tenant']['id']

        cls.nova = nova_client.Client('2',
                                      auth_url=OS_AUTH_URL,
                                      username=OS_USERNAME,
                                      auth_token=OS_TOKEN,
                                      tenant_id=OS_TENANT_ID,
                                      insecure=True)

        # Glance connect
        glance_endpoint = services.url_for(service_type='image',
                                           endpoint_type='publicURL')
        cls.glance = glance_client.Client(endpoint=glance_endpoint,
                                          token=OS_TOKEN,
                                          insecure=True)
        cls.uid_list = []

    def setUp(self):
        """

        :return: Nothing
        """
        self.amount_of_images_before = len(list(self.glance.images.list()))
        self.image = None
        self.our_own_flavor_was_created = False
        self.expected_flavor_id = 3
        self.node_to_boot = None
        self.security_group_name = "ms_compatibility"
        self.the_security_group = self.nova.security_groups.create(
                name=self.security_group_name,
                description="Windows Compatibility")
        # Add rules for ICMP, TCP/22
        self.nova.security_group_rules.create(
                self.the_security_group.id,
                ip_protocol="icmp",
                from_port=-1,
                to_port=-1,
                cidr="0.0.0.0/0")
        self.nova.security_group_rules.create(
                self.the_security_group.id,
                ip_protocol="tcp",
                from_port=80,
                to_port=80,
                cidr="0.0.0.0/0")
        # adding floating ip
        self.floating_ip = self.nova.floating_ips.create(
                self.nova.floating_ip_pools.list()[0].name)

    def tearDown(self):
        """

        :return:
        """
        if self.node_to_boot is not None:
            self.nova.servers.delete(self.node_to_boot.id)
        if self.image is not None:
            self.glance.images.delete(self.image.id)
        if self.our_own_flavor_was_created:
            self.nova.flavors.delete(self.expected_flavor_id)
        # delete the security group
        self.nova.security_groups.delete(self.the_security_group)
        # delete the floating ip
        self.nova.floating_ips.delete(self.floating_ip)
        self.assertEqual(self.amount_of_images_before,
                         len(list(self.glance.images.list())),
                         "Length of list with images should be the same")

    def test_542825_CreateInstanceWithWindowsImage(self):
        """

        :return: Nothing
        """
        # creating of the image
        self.image = self.glance.images.create(
                name='MyTestSystem',
                disk_format='qcow2',
                container_format='bare')
        self.glance.images.upload(
                self.image.id,
                open('/tmp/trusty-server-cloudimg-amd64-disk1.img', 'rb'))
        # check that required image in active state
        is_activated = False
        while not is_activated:
            for image_object in self.glance.images.list():
                if image_object.id == self.image.id:
                    self.image = image_object
                    print "Image in the {} state".format(self.image.status)
                    if self.image.status == 'active':
                        is_activated = True
                        break
            time.sleep(1)

        # Default - the first
        network_interfaces = \
            [{"net-id": self.nova.networks.list()[0].id}]
        # More detailed check of network list
        for network in self.nova.networks.list():
            if 'internal' in network.label:
                network_interfaces = [{"net-id": network.id}]
        print "Starting with network interface(s) {}".format(network_interfaces)

        # TODO: add check flavor parameters vs. vm parameters
        # Collect information about the medium flavor and modify it to our needs
        for flavor in self.nova.flavors.list():
            if 'medium' in flavor.name:
                expected_flavor = self.nova.flavors.create(
                        name="copy.of." + flavor.name,
                        ram=flavor.ram,
                        vcpus=1,  # Only one VCPU
                        disk=flavor.disk
                )
                self.expected_flavor_id = expected_flavor.id
                self.our_own_flavor_was_created = True
                break
        print "Starting with flavor {}".format(
                self.nova.flavors.get(self.expected_flavor_id))
        # nova boot
        self.node_to_boot = self.nova.servers.create(
                name="MyTestSystemWithNova",
                image=self.image,
                flavor=self.nova.flavors.get(self.expected_flavor_id),
                nics=network_interfaces)
        # waiting while the build process will be completed
        is_created = False
        while not is_created:
            for server_object in self.nova.servers.list():
                if server_object.id == self.node_to_boot.id:
                    self.node_to_boot = server_object
                    print "Node in the {} state".format(self.node_to_boot.status)
                    if self.node_to_boot.status != 'BUILD':
                        is_created = True
                        break
            time.sleep(5)
        # check that boot returns expected results
        self.assertEqual(self.node_to_boot.status, 'ACTIVE',
                         "The node not in active state!")

        # adding security group
        self.node_to_boot.add_security_group(self.the_security_group.name)

        print "Using following floating ip {}".format(
                self.floating_ip.ip)

        self.node_to_boot.add_floating_ip(self.floating_ip)

        # TODO: test is here
        ping = os.system("ping -c 4 -i 4 {}".format(
                self.floating_ip.ip))
        self.assertEqual(ping, 0, "Instance is not reachable")

    @unittest.skip("Not Implemented")
    def test_542826_PauseAndUnpauseInstanceWithWindowsImage(self):
        """

        :return: Nothing
        """
        pass

    @unittest.skip("Not Implemented")
    def test_542826_SuspendAndResumeInstanceWithWindowsImage(self):
        """

        :return: Nothing
        """
        pass
