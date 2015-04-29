#!/usr/bin/env python

# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.
# Copyright (c) 2014 Mozilla Corporation

# Contributor: jbryner@mozilla.com

import boto.ec2
import boto.exception
import json
import logging
import os
import pytz
import sys
from configlib import getConfig, OptionParser
from datetime import datetime
from datetime import timedelta
from dateutil.parser import parse
from logging.handlers import SysLogHandler
from pythonjsonlogger import jsonlogger
from time import sleep

logger = logging.getLogger(sys.argv[0])


def loggerTimeStamp(self, record, datefmt=None):
    return toUTC(datetime.now()).isoformat()


def initLogger():
    logger.level = logging.DEBUG
    if options.output == 'json':
        formatter = jsonlogger.JsonFormatter()
    else:
        formatter = logging.Formatter('%(asctime)s - %(message)s')
        formatter.formatTime = loggerTimeStamp

    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(formatter)
    logger.addHandler(sh)


def toUTC(suspectedDate, localTimeZone=None):
    '''make a UTC date out of almost anything'''
    utc = pytz.UTC
    objDate = None
    if localTimeZone is None:
        localTimeZone=options.defaulttimezone
    if type(suspectedDate) == str:
        objDate = parse(suspectedDate, fuzzy=True)
    elif type(suspectedDate) == datetime:
        objDate = suspectedDate

    if objDate.tzinfo is None:
        objDate = pytz.timezone(localTimeZone).localize(objDate)
        objDate = utc.normalize(objDate)
    else:
        objDate = utc.normalize(objDate)
    if objDate is not None:
        objDate = utc.normalize(objDate)

    return objDate


def initConfig():
    # change this to your default zone for when it's not specified
    options.defaulttimezone = getConfig('defaulttimezone',
                                        'UTC',
                                        options.configfile)

    #json or text output?
    options.output = getConfig('output',
                               options.output,
                               options.configfile)

    # set to a comma delimited list of AWS regions
    options.regions = getConfig('regions',
                                options.regions,
                                options.configfile)
    if options.regions is not None:
        options.regions = [x for x in list(options.regions.split(',')) if len(x)>0 ]
    else:
        options.regions = list()
        for r in boto.ec2.regions():
            options.regions.append(r.name)

    #target instance
    #anything in the conf file?
    options.instances = getConfig('instances',
                                  options.instances,
                                  options.configfile)
    if options.instances is not None:
        options.instances = [x for x in list(options.instances.split(',')) if len(x)>0 ]

    #target volumes?
    #anything in the conf file?
    options.volumes = getConfig('instances',
                                  options.volumes,
                                  options.configfile)
    if options.volumes is not None:
        options.volumes = [x for x in list(options.volumes.split(',')) if len(x)>0 ]


def get_ec2_instances(region):
    ec2_conn = boto.ec2.connect_to_region(region)
    try:
        reservations = ec2_conn.get_all_reservations()
        for r in reservations:
            logger.info('Region: {0} {1} {2} instances'.format(region, r, len(r.instances)))
            for i in r.instances:
                logger.info('Instances: id: {0} state: {1} image_id: {2} root_device: {3} tags: {4} zone: {5}'.format(i.id, i.state, i.image_id,i.root_device_type,i.tags, i.placement))

        #for vol in ec2_conn.get_all_volumes():
        #    print region+':',vol.id
    except boto.exception.EC2ResponseError as e:
        # no access in this region, move on.
        # print('boto exception: {0}'.format(e))
        pass
    except Exception as e:
        logger.error('Exception: {0}'.format(e))
        pass


def get_instance_info(region, instances):
    ec2_conn = boto.ec2.connect_to_region(region)
    logger.info('looking for {0} in {1}'.format(instances, region))
    try:
        for i in ec2_conn.get_only_instances(instance_ids=instances):
            volumes = [v for v in ec2_conn.get_all_volumes() if v.attach_data.instance_id == i.id]
            logger.info('Instance volumes:{0}'.format(volumes))

    except boto.exception.EC2ResponseError as e:
        # instance not found in this region, move on.
        # print('boto exception: {0}'.format(e))
        pass
    except Exception as e:
        logger.error('Exception: {0}'.format(e))
        pass


def list_volumes(region):
    ec2_conn = boto.ec2.connect_to_region(region)
    volumes = [v for v in ec2_conn.get_all_volumes()]
    for v in volumes:
        logger.info('volume {0} created: {1} size: {2} state:{3} tags:{4}'.format(v.id, v.create_time, v.size, v.volume_state(), v.tags))


def list_snapshots(region):
    ec2_conn = boto.ec2.connect_to_region(region)
    snapshots = [s for s in ec2_conn.get_all_snapshots()]
    for s in snapshots:
        logger.info('snapshots {0} created: {1} size: {2} description: {3} '.format(s.id, s.start_time, s.volume_size, s.description))
        logger.debug(s.zone)


def snapshot_volumes(region):
    ec2_conn = boto.ec2.connect_to_region(region)
    volumes = [v for v in ec2_conn.get_all_volumes() if v.id in options.volumes]
    for v in volumes:
        s = v.create_snapshot(description='forensic snapshot of {0} taken {1}'.format(v.attach_data.instance_id, datetime.utcnow().isoformat()))
        logger.info('created {0}'.format(s))


def attach_snapshot(region):
    ec2_conn = boto.ec2.connect_to_region(region)
    # get the forensic instance first to
    # get the availability zone to use when creating the volume
    if options.forensic:
        for i in ec2_conn.get_only_instances(instance_ids=options.forensic):
            logger.debug('Using forensic image: {0} zone:{1}'.format(i.id, i.placement))

            if i.state not in ['stopped']:
                logger.info('Instance not stopped..stopping')
                i.stop()
                logger.info('Finished the ask to stop...monitoring')
                while i.state not in ['stopped']:
                    sleep(2)
                    i.update(True)
                logger.info('State:{0}'.format(i.state))
            logger.debug('Using forensic image: {0} zone:{1}'.format(i.id, i.placement))
            snapshots = [s for s in ec2_conn.get_all_snapshots() if s.id in options.snapshots]
            for s in snapshots:
                logger.debug('Creating volume for  forensic image: {0} zone:{1}'.format(i.id, i.placement))
                snapshot_volume = s.create_volume(i.placement)
                while snapshot_volume.volume_state() not in ['available']:
                    sleep(2)
                    snapshot_volume.update(True)

                logger.debug(snapshot_volume)

                if snapshot_volume.attach(i.id, '/dev/sdf'):
                    logger.info('Attached {0} to instance {1}'.format(snapshot_volume.id, i.id))


def main():
    if options.regions:
        for region in options.regions:

            # list instances in a region?
            if (options.instances is None  and options.volumes is None) \
               or (options.instances and 'list' in options.instances):
                get_ec2_instances(region)

            # target a specific instance?
            if options.instances \
               and len(options.instances) > 0 \
               and options.action == "info":
                get_instance_info(region, options.instances)

            # target a specific volume
            if options.volumes and len(options.volumes) > 0:
                if options.action == "snapshot":
                    snapshot_volumes(region)
                if options.action == "list":
                    list_volumes(region)

            # target a specific snapshot
            if options.snapshots and len(options.snapshots) > 0:
                # attach a snapshot to forensics?
                if options.action == 'attach' and \
                   options.snapshots and \
                   options.forensic :
                    attach_snapshot(region)
                if options.action == 'list':
                    list_snapshots(region)



if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option("-c", "--conf", dest='configfile', default=sys.argv[0].replace('.py', '.conf'), help="configuration file to use")
    parser.add_option("-o", "--output", dest='output', default='text', help="output format, json or text")
    parser.add_option("-r", "--regions", dest='regions', default=None, help="comma delimited list of regions to target")
    parser.add_option("-i", "--instances", dest='instances', default=None, help="comma delimited list of instance IDs to target")
    parser.add_option("-f", "--forensic", dest='forensic', default=None, help="instance IDs to use as the forensic workstation")
    parser.add_option("-v", "--volumes", dest='volumes', default=None, help="comma delimited list of volume IDs to target")
    parser.add_option("-s", "--snapshots", dest='snapshots', default=None, help="comma delimited list of snapshot IDs to attach to the forensic instance")
    parser.add_option("-a", "--action", dest='action', default='list', type="choice", choices=["list", "info", "snapshot", "attach"], help="Action to perform, defaults to list")
    (options, args) = parser.parse_args()
    initConfig()
    initLogger()
    main()
