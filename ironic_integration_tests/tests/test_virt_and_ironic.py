"""
Copyright 2017 Rackspace

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

    http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.
"""
from ironic_integration_tests.tests.base import BaseTest
from ironic_integration_tests.common import output_parser as parser
from ironic_integration_tests.common.config import get_config


class VirtIronicTests(BaseTest):

    def setUp(self):
        super(VirtIronicTests, self).setUp()

    def test_mixed_ironic_and_virt_network(self):
        # Get tftp private network ID
        net_cmd = "neutron net-show tftp"
        result = self.cli.execute_cmd(net_cmd)
        tftp_network = parser.details(result)
        net_id = tftp_network.get("id")

        # Create a ironic server and a virtual server
        pubkey = self._create_keypair()
        ironic_name = self._random_name("test_network_ironic_")
        ironic_server = self._create_instance(
            image=get_config("ironic", "image"),
            flavor=get_config("ironic", "flavor"),
            pubkey=pubkey, name=ironic_name, network=net_id,
            wait_for_active=False)

        virt_name = self._random_name("test_network_virt_")
        virt_server = self._create_instance(
            image=get_config("virt", "image"),
            flavor=get_config("virt", "flavor"),
            pubkey=pubkey, name=virt_name, network=net_id,
            wait_for_active=False)

        # Wait for virtual server to go to ACTIVE
        server_id = virt_server.get("id")
        show_cmd = "nova show {0}".format(server_id)
        virt_server = self._wait_for_status(show_cmd, "status", "ACTIVE")
        self.assertEqual(virt_server.get("status"), "ACTIVE")

        # Wait for ironic server to go to ACTIVE
        server_id = ironic_server.get("id")
        show_cmd = "nova show {0}".format(server_id)
        ironic_server = self._wait_for_status(show_cmd, "status", "ACTIVE")
        self.assertEqual(ironic_server.get("status"), "ACTIVE")
        self.hv_id = ironic_server.get("OS-EXT-SRV-ATTR:hypervisor_hostname")

        # Log onto each server and ping the other server
        ironic_ip = self._get_ip_address(ironic_server)
        virt_ip = self._get_ip_address(virt_server)

        user = get_config("ironic", "user")
        ssh_cmd = "ssh -o StrictHostKeyChecking=no -i /tmp/{0} " \
                  "-t {1}@{2} ping {3} -c 5".format(
                    pubkey, user, ironic_ip, virt_ip)
        self.cli.execute_w_retry(ssh_cmd)

        user = get_config("virt", "user")
        ssh_cmd = "ssh -o StrictHostKeyChecking=no -i /tmp/{0} " \
                  "-t {1}@{2} ping {3} -c 5".format(
                    pubkey, user, virt_ip, ironic_ip)
        self.cli.execute_w_retry(ssh_cmd)

    def test_ironic_virt_region(self):
        region_cmd = "openstack region list"
        result = self.cli.execute_cmd(region_cmd)
        regions = parser.listing(result)
        self.assertEqual(len(regions), 1, "Multiple regions deployed")

        ironic_hosts = []
        virtual_hosts = []
        cmd = "nova hypervisor-list"
        result = self.cli.execute_cmd(cmd)
        hypervisors = parser.listing(result)
        for hv in hypervisors:
            cmd = "nova hypervisor-show {0}".format(
                hv.get("Hypervisor hostname"))
            result = self.cli.execute_cmd(cmd)
            hypervisor = parser.details(result)
            if hypervisor.get("hypervisor_type") == "ironic":
                ironic_hosts.append(hypervisor.get("service_host"))
            else:
                virtual_hosts.append(hypervisor.get("service_host"))
        self.assertGreater(len(ironic_hosts), 0, "No ironic hosts found")
        self.assertGreater(len(virtual_hosts), 0, "No virtual hosts found")

        pubkey = self._create_keypair()
        virt_name = self._random_name("test_region_virt_")
        virt_server = self._create_instance(
            image=get_config("virt", "image"),
            flavor=get_config("virt", "flavor"),
            pubkey=pubkey, name=virt_name)

        cmd = "nova flavor-show {0}".format(get_config("virt", "flavor"))
        result = self.cli.execute_cmd(cmd)
        flavor = parser.details(result)
        virt_ram = flavor.get("ram")

        available_ironic = None
        for ironic_host in ironic_hosts:
            cmd = "openstack host show {0}".format(ironic_host)
            result = self.cli.execute_cmd(cmd)
            projects = parser.listing(result)
            total = 0
            used = 0
            for project in projects:
                if project.get("Project") == "(total)":
                    total = project.get("Memory MB")
                if project.get("Project") == "(used_now)":
                    used = project.get("Memory MB")
            available_ram = int(total) - int(used)
            if available_ram >= virt_ram:
                available_ironic = ironic_host
                break

        self.assertIsNotNone(
            available_ironic, "No available ironic host to attempt to migrate")
        migrate_cmd = "openstack server migrate {0} --live {1}"
        virt_to_ironic = migrate_cmd.format(virt_server.get("id"),
                                            available_ironic)
        result = self.cli.execute_cmd(cmd=virt_to_ironic, fail_ok=True)
        self.assertIn("The supplied hypervisor type of is invalid", result)
        cmd = "nova delete {0}".format(virt_name)
        self.cli.execute_cmd(cmd, fail_ok=True)

        ironic_name = self._random_name("test_region_ironic_")
        ironic_server = self._create_instance(
            image=get_config("ironic", "image"),
            flavor=get_config("ironic", "flavor"),
            pubkey=pubkey, name=ironic_name)
        self.hv_id = ironic_server.get("OS-EXT-SRV-ATTR:hypervisor_hostname")

        cmd = "nova flavor-show {0}".format(get_config("ironic", "flavor"))
        result = self.cli.execute_cmd(cmd)
        flavor = parser.details(result)
        ironic_ram = flavor.get("ram")

        available_virt = None
        for virt_host in virtual_hosts:
            cmd = "openstack host show {0}".format(virt_host)
            result = self.cli.execute_cmd(cmd)
            projects = parser.listing(result)
            total = 0
            used = 0
            for project in projects:
                if project.get("Project") == "(total)":
                    total = project.get("Memory MB")
                if project.get("Project") == "(used_now)":
                    used = project.get("Memory MB")
            available_ram = int(total) - int(used)
            if available_ram >= ironic_ram:
                available_virt = virt_host
                break

        self.assertIsNotNone(
            available_virt, "No available virtual host to attempt to migrate")
        ironic_to_virt = migrate_cmd.format(ironic_server.get("id"),
                                            available_virt)
        result = self.cli.execute_cmd(cmd=ironic_to_virt, fail_ok=True)
        self.assertIn("The supplied hypervisor type of is invalid", result)

    def tearDown(self):
        super(VirtIronicTests, self).tearDown()
