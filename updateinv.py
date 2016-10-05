"""Get and update or create inventory on a resource provider.

An example of calling is:

    df -BG --output=size / |tail -1  | \
        python updateinv.py -r myrp4 -c DISK_GB --reserved 2

This reports the size (in GB) of the device hosting / to the resource
provider 'myrp4' with a reserved of 2 GB.

Note: This does an update of a single class of inventory not a set of
all the inventory associated with one resource provider. This is because
doign just one is more aligned with the information gathering processes:
pipe df to the script with certain args to do disk capacity. We'd pipe
something else to the script with different args to do some other kind
of capacity, perhaps with a different set of filters in the pipeline.

For the time being this does not deal with generation conflicts. If a
409 happens, the way to fix that right now is to run the script again.

If there are other errors they will be reported to the console and the
process exit code will be non-zero.
"""

from __future__ import print_function

import argparse
import os
import string
import sys

import requests

# Die quickly when these values cannot be set.
# auth to an admin role and then:
# export TOKEN=$(openstack token issue -f value -c id)
# export PLACEMENT_API=$(openstack endpoint show placement \
#                        -f value -c publicurl)
# NOTE(cdent): We could replace all this with keystoneauth but meh;
# the point here is to demonstrate a form of low overhead scripting.
TOKEN = os.environ['TOKEN']
PLACEMENT_BASE = os.environ['PLACEMENT_API']

SESSION = requests.Session()
SESSION.headers.update({
    'x-auth-token': TOKEN,
    'accept': 'application/json'
})


def _inventory_url(resource_uuid, resource_class=None):
    base_url = '%s/resource_providers/%s/inventories' % (
        PLACEMENT_BASE, resource_uuid)
    if resource_class:
        base_url = '%s/%s' % (base_url, resource_class)
    return base_url


def _read_stdin_for_total():
    data = sys.stdin.read()
    # Get rid of whitespace and letters
    return int(data.strip().strip(string.letters))


def create_inventory(resource_provider, resource_class, total, reserved):
    url = _inventory_url(resource_provider['uuid'])
    data = {'resource_provider_generation': resource_provider['generation'],
            'total': total, 'reserved': reserved,
            'resource_class': resource_class}
    resp = SESSION.post(url, json=data)
    if resp.status_code != 200:
        resp.raise_for_status()


def get_resource_provider(resource_name):
    # XXX: encode
    url = '%s/resource_providers?name=%s' % (PLACEMENT_BASE, resource_name)
    resp = SESSION.get(url)
    if resp.status_code >= 400:
        resp.raise_for_status()
    try:
        return resp.json()['resource_providers'][0]
    # Other exceptions are much more dire and we just let them
    # raise because what matters is that we had an error, not making
    # it pretty.
    except IndexError:
        raise ValueError(
            'unable to find a resource provider with that name: %s' %
            resource_name)


def get_inventory(resource_uuid, resource_class):
    url = _inventory_url(resource_uuid, resource_class)
    resp = SESSION.get(url)
    if resp.status_code == 404:
        # We haven't got inventory of this sort yet, so we'll create
        # it.
        return None
    if resp.status_code >= 400:
        resp.raise_for_status()
    return resp.json()


def update_inventory(resource_provider, inventory, resource_class,
                     total, reserved):
    url = _inventory_url(resource_provider['uuid'], resource_class)
    inventory.update({'total': total, 'reserved': reserved})
    resp = SESSION.put(url, json=inventory)
    if resp.status_code != 200:
        resp.raise_for_status()


def run():
    parser = argparse.ArgumentParser(
        description='Update resource provider inventory from stdin')
    parser.add_argument(
        '-r', '--resource_provider',
        dest='resource_provider_name',
        required=True,
        help='The name of the resource providing with the inventory being '
             'updated')
    parser.add_argument(
        '-c', '--resource_class',
        dest='resource_class',
        required=True,
        help='The resource class of the inventory being updated')
    parser.add_argument(
        '--reserved',
        dest='reserved', default=0, type=int,
        help='The amount of inventory to reserve')
    args = parser.parse_args()

    total = _read_stdin_for_total()
    resource_provider = get_resource_provider(args.resource_provider_name)
    inventory = get_inventory(resource_provider['uuid'], args.resource_class)
    if inventory is None:
        print('Creating inventory for %s, total: %s, reserved: %s' %
              (args.resource_class, total, args.reserved))
        create_inventory(resource_provider, args.resource_class, total,
                         args.reserved)
    elif inventory['total'] != total or inventory['reserved'] != args.reserved:
        print('Updating inventory for %s, total: %s, reserved: %s' %
              (args.resource_class, total, args.reserved))
        update_inventory(resource_provider, inventory, args.resource_class,
                         total, args.reserved)
    else:
        print('No updates required for %s' % args.resource_class)


if __name__ == '__main__':
    run()
