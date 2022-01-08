import os
import time
import argparse
import sys
import logging
import re
from configparser import ConfigParser

from cloudsigma import errors
import cloudsigma.resource as cr

logging.basicConfig(level=logging.INFO, filename='output.log',
                    format='%(asctime)s %(message)s',
                    datefmt='%m/%d/%Y %I:%M:%S %p')


class NDTestBase:

    def __init__(self, gpus=None, gpu_model=None, grey=False, server_amount=None,
                 server_cpu=None, cpu_type=None, server_mem=None, drive=None):
        self.drives = cr.Drive()
        self.gpus = gpus
        self.gpu_model = gpu_model
        self.grey = grey
        self.server_amount = server_amount
        self.server_cpu = server_cpu * 1000 if server_cpu else server_cpu
        self.server_mem = server_mem * 1073741824 if server_mem else server_mem
        self.cpu_type = cpu_type
        self.drive = drive
        self.pubkey = None
        self.unique_name = None
        self.private_network = None
        self.public_network = None
        self.vlan_uuid = None
        self.max_per_host = None
        self.auto_adjust_amount = None
        self.iteration_pause_sec = None

    def set_from_config(self):
        config = ConfigParser()
        config.read('config.ini')
        self.gpus = int(config.get('main', 'gpus'))
        self.gpu_model = config.get('main', 'gpu_model')
        self.grey = config.getboolean('main', 'grey')
        self.server_cpu = int(config.get('main', 'server_cpu')) * 1000
        self.server_mem = int(config.get('main', 'server_mem')) * 1073741824
        self.cpu_type = config.get('main', 'cpu_type')
        self.drive = config.get('main', 'drive', fallback=None)
        self.pubkey = config.get('main', 'pubkey', fallback=None)
        self.unique_name = config.get('main', 'unique_name')
        self.public_network = config.getboolean('main', 'public_network')
        self.private_network = config.getboolean('main', 'private_network')
        self.vlan_uuid = config.get('main', 'vlan_uuid', fallback=None)
        self.auto_adjust_amount = config.getboolean('main',
                                                    'auto_adjust_max_gpus')
        self.iteration_pause_sec = config.get('main', 'iteration_pause_sec')
        return config

    def create_and_start_gpu_servers(self):
        if self.grey and not self.server_amount:
            self.calculate_max_backfilling_servers()
            logging.info('Maximum creatable servers: {}'.format(
                self.server_amount))
        else:
            self.set_max_per_host()
            self.server_amount = 1
        for i in range(0, self.server_amount):
            self.cleanup(stopped_only=True)
            guest = self.create_server()
            self.start_guest(guest)
            self.server_amount = None

    def calculate_max_backfilling_servers(self):
        capacity = self.fetch_capacity()
        max_guests_cpu = capacity['most_free_cpu'] / self.server_cpu
        max_guests_mem = capacity['most_free_mem'] / self.server_mem
        max_guests_gpu = capacity['total_gpus'] / self.gpus
        max_guests = min(max_guests_gpu, max_guests_cpu, max_guests_mem)
        self.server_amount = int(max_guests)
        self.max_per_host = int(capacity['max_per_host'])

    def fetch_capacity(self):
        caps_client = cr.Capabilites()
        capabilities = caps_client.get()
        result_dict = dict()
        gpu_section = capabilities.get('gpus', None)
        if gpu_section:
            model_section = gpu_section.get(self.gpu_model)
            if model_section:
                result_dict['total_gpus'] = model_section.get(
                    'available_backfill', 0)
                result_dict['max_per_host'] = model_section['max_per_host']
        if not result_dict.get('max_per_host', None):
            logging.info('No GPUs currently available, pausing for 5min')
            time.sleep(300)
            self.fetch_capacity()
        result_dict['smp_size'] = \
            capabilities['hosts'][self.cpu_type]['cpu_per_smp']['max']
        result_dict['most_free_cpu'] = \
            capabilities['hosts'][self.cpu_type]['free_resources']['total']['cpu']
        result_dict['most_free_mem'] = \
            capabilities['hosts'][self.cpu_type]['free_resources']['total']['mem']
        return result_dict

    def set_max_per_host(self):
        capacity = self.fetch_capacity()
        self.max_per_host = int(capacity['max_per_host'])

    def create_server(self):
        guest_def = self.generate_gpu_server_def()
        if self.grey:
            created_server = cr.BServer().create(guest_def)
        else:
            created_server = cr.Server().create(guest_def)
        return created_server

    def generate_gpu_server_def(self):
        gpus_list = list()
        if self.auto_adjust_amount and self.max_per_host < self.gpus:
            gpu_count = self.max_per_host
        else:
            gpu_count = self.gpus
        for i in range(0, gpu_count):
            gpus_list.append({"model": "{}".format(self.gpu_model)})
        guest_def = {
            'name': self.generate_name(),
            'vnc_password': 'testservers3123131',
            'gpus': gpus_list,
            'cpu': self.server_cpu,
            'mem': self.server_mem,
            'cpu_type': self.cpu_type,
            'nics': self.generate_nics_definition(),
        }
        if self.drive:
            cloned_uuid = self.clone_drive(self.drive)
            guest_def['drives'] = [{
                "device": "virtio",
                "dev_channel": "0:0",
                "drive": cloned_uuid,
                "boot_order": 1
            }]
        if self.pubkey:
            guest_def['pubkeys'] = [self.pubkey]
        return guest_def

    def generate_name(self):
        last_number = self.get_last_server()
        return '{}-{}-{}'.format('grey' if self.grey else 'white',
                                 last_number + 1, self.unique_name)

    def get_last_server(self):
        servers = cr.Server().list()
        last_number = 0
        for server in servers:
            name_match = re.match('(grey|white)-(\d+)-(.*)', server['name'])
            if name_match:
                current_number = int(name_match.group(2))
                if current_number > last_number:
                    last_number = current_number
        return last_number

    def generate_nics_definition(self):
        nics = list()
        if self.public_network:
            nics.append(
                {
                    "ip_v4_conf": {
                        "ip": None,
                        "conf": "dhcp"
                    },
                    "model": "virtio",
                }
            )
        if self.private_network and self.vlan_uuid:
            nics.append(
                {'vlan': self.vlan_uuid}
            )
        return nics

    def clone_drive(self, uuid):
        clone_drive_def = {
            'name': 'test_clone_{}'.format(uuid),
        }
        cloned_drive = cr.Drive().clone(uuid, clone_drive_def)
        self.wait_for_status(cloned_drive['uuid'], 'unmounted',
                             client=cr.Drive())
        return cloned_drive['uuid']

    def start_guest(self, guest):
        success = False
        try:
            cr.Server().start(guest['uuid'])
        except errors.ServerError as e:
            logging.info('Guest {} failed to '
                         'start with error: {}'.format(guest['uuid'],
                                                       e.message))
            return success
        guest, seconds, success = self.wait_for_status(guest['uuid'],
                                                       'running',
                                                       client=cr.Server())
        if success:
            logging.info('Guest {} started in {} seconds'.format(
                guest['name'], seconds))

        return success

    def cleanup(self, stopped_only=False):
        self.cleanup_servers(stopped_only=stopped_only)
        self.cleanup_drives()

    def cleanup_servers(self, stopped_only=False):
        server_list = cr.Server().list_detail()
        stopping = list()
        deleting = list()
        intermediate = list()
        for server in server_list:
            if any(x in server['name'] for x in ['grey', 'white']):
                status = server['status']
                if status == 'running' and not stopped_only:
                    cr.Server().stop(server['uuid'])
                    stopping.append(server['uuid'])
                elif status == 'stopped':
                    cr.Server().delete(server['uuid'])
                    deleting.append(server['uuid'])
                elif not stopped_only:
                    intermediate.append(server['uuid'])
        
        for uuid in stopping:
            success = False
            try:
                guest, timeout, success = self.wait_for_status(uuid,
                                                               'stopped',
                                                               client=cr.Server())
            except:
                logging.info('Server {} did not stop in time'.format(uuid))
            if success:
                cr.Server().delete(uuid)
                deleting.append(uuid)

        for uuid in deleting:
            try:
                self.wait_deleted(uuid, cr.Server())
            except:
                logging.info('Server {} did not delete in time'.format(uuid))

        if len(intermediate) != 0:
            logging.info('Servers {} stuck in '
                         'intermediate states'.format(intermediate))

    def cleanup_drives(self):
        mounted = list()
        deleting = list()
        inter = list()

        drives_list = cr.Drive().list_detail()

        for drive in drives_list:
            if 'test' in drive['name']:
                status = drive['status']
                if status == 'mounted':
                    mounted.append(drive['uuid'])
                elif status in ('unmounted', 'uploading'):
                    cr.Drive().delete(drive['uuid'])
                    deleting.append(drive['uuid'])
                else:
                    inter.append(drive['uuid'])

        for uuid in deleting:
            try:
                self.wait_deleted(uuid, client=cr.Drive())
            except:
                logging.info("Drive {} did not delete in time".format(uuid))

        if inter:
            logging.info('The drives {} are stuck in intermediate '
                         'states and cannot be deleted.'.format(inter))

    def wait_for_status(self, uuid, status, client, timeout=40):
        WAIT_STEP = 1 

        count_waited = 0
        resource = None
        success = False
        while True:
            resource = client.get(uuid)
            if resource['status'] == status:
                success = True
                break
            if count_waited >= timeout / WAIT_STEP:
                logging.info('Resource with uuid {} didn\'t reach '
                              'state "{}" for {} seconds, still in '
                              'state "{}"'.format(uuid, status, timeout,
                                                  resource['status']))
                success = False
                break
            time.sleep(WAIT_STEP)
            count_waited += 1
        return resource, count_waited, success

    def wait_deleted(self, uuid, client, timeout=40):
        WAIT_STEP = 1 

        count_waited = 0
        while True:
            try:
                client.get(uuid)
            except errors.ClientError as exc:
                if exc.status_code == 404:
                    break
                else:
                    raise
            if count_waited >= timeout / WAIT_STEP:
                logging.info('Resource did not delete in {} seconds'.format(timeout))
            time.sleep(WAIT_STEP)
            count_waited += 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Create and start '
                                                 'grey and white servers')
    parser.add_argument('--servers', metavar='n', type=int,
                        help='number of servers to create and start (optional)')
    parser.add_argument('--gpus', metavar='n', type=int,
                        help='number of GPUs per server')
    parser.add_argument('--grey', action='store_true',
                        help='grey or white server (optional)')
    parser.add_argument('--cleanup', action='store_true',
                        help='stops and removes servers on demand')
    parser.add_argument('--server-cpu', type=int,
                        help='define the CPU size of a server (in GHz)')
    parser.add_argument('--server-mem', type=int,
                        help='define the memory size of a server (in GB)')
    parser.add_argument('--drive-uuid', type=str,
                        help='UUID of an image to use for server '
                             'creation (optional)')
    parser.add_argument('--cpu-type', type=str, default='amd',
                        help='CPU type to use for server creation')
    parser.add_argument('--gpu-model', type=str,
                        help='GPU model id to use')

    args = parser.parse_args()
    if len(sys.argv) > 1:
        ndt = NDTestBase(gpus=args.gpus, gpu_model=args.gpu_model,
                         grey=args.grey, server_amount=args.servers,
                         server_cpu=args.server_cpu, cpu_type=args.cpu_type,
                         server_mem=args.server_mem, drive=args.drive_uuid)
        if args.cleanup:
            ndt.cleanup()
            sys.exit()
        ndt.create_and_start_gpu_servers()
    elif os.path.isfile('config.ini'):
        ndt = NDTestBase()
        while True:
            ndt.set_from_config()
            ndt.create_and_start_gpu_servers()
            time.sleep(int(ndt.iteration_pause_sec) if
                       ndt.iteration_pause_sec else 120)
    else:
        parser.print_help(sys.stderr)
