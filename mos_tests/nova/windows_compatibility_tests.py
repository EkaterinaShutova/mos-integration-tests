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
        pass

    def tearDown(self):
        """

        :return:
        """
        pass

    def test_542825_CreateInstanceWithWindowsImage(self):
        """

        :return: Nothing
        """
        amount_of_images_before = len(list(self.glance.images.list()))
        # creating of the image
        image = self.glance.images.create(name='MyTestSystem',
                                          disk_format='qcow2',
                                          container_format='bare')
        self.glance.images.upload(
                image.id,
                open('/tmp/trusty-server-cloudimg-amd64-disk1.img', 'rb'))
        # check that required image in active state
        is_activated = False
        while not is_activated:
            for image_object in self.glance.images.list():
                if image_object.id == image.id:
                    print "Image in the {} state".format(image_object.status)
                    if image_object.status == 'active':
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
        expected_flavor_id = self.nova.flavors.get(3)
        our_own_flavor_was_created = False
        for flavor in self.nova.flavors.list():
            if 'medium' in flavor.name:
                expected_flavor = self.nova.flavors.create(
                    name="copy.of." + flavor.name,
                    ram=flavor.ram,
                    vcpus=1,  # Only one VCPU
                    disk=flavor.disk
                )
                expected_flavor_id = expected_flavor.id
                our_own_flavor_was_created = True
                break
        print "Starting with flavor {}".format(
                self.nova.flavors.get(expected_flavor_id))
        boot_node = self.nova.servers.create(
                name="MyTestSystemWithNova",
                image=image,
                flavor=self.nova.flavors.get(expected_flavor_id),
                nics=network_interfaces)
        is_created = False
        while not is_created:
            for server_object in self.nova.servers.list():
                if server_object.id == boot_node.id:
                    boot_node = server_object
                    print "Node in the {} state".format(boot_node.status)
                    if boot_node.status != 'BUILD':
                        is_created = True
                        break
            time.sleep(5)
        # TODO: Temporary disabling clean-up process
        if False:
            # attempt to delete the image at the end
            self.nova.servers.delete(boot_node.id)
            self.glance.images.delete(image.id)
            if our_own_flavor_was_created:
                self.nova.flavors.delete(expected_flavor_id)
            amount_of_images_after = len(list(self.glance.images.list()))
            self.assertEqual(amount_of_images_before, amount_of_images_after,
                             "Length of list with images should be the same")

    @unittest.skip("Unimplemented")
    def test_542826_PauseAndUnpauseInstanceWithWindowsImage(self):
        """

        :return: Nothing
        """
        pass

    @unittest.skip("Unimplemented")
    def test_542826_SuspendAndResumeInstanceWithWindowsImage(self):
        """

        :return: Nothing
        """
        pass
