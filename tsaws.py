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
from datetime import datetime
from datetime import timedelta
from configlib import getConfig, OptionParser
from logging.handlers import SysLogHandler
from pythonjsonlogger import jsonlogger
from dateutil.parser import parse
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
                logger.info('Instances: id: {0} state: {1} image_id: {2} root_device: {3} tags: {4}'.format(i.id, i.state, i.image_id,i.root_device_type,i.tags))

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
    logger.debug('looking for {0} in {1}'.format(instances, region))
    try:
        for i in ec2_conn.get_only_instances(instance_ids=instances):
            print(i.id)
            #m = get_instance_metadata()
            volumes = [v for v in ec2_conn.get_all_volumes() if v.attach_data.instance_id == i.id]
            print('Instance volumes:{0}'.format(volumes))

    except boto.exception.EC2ResponseError as e:
        # instance not found in this region, move on.
        # print('boto exception: {0}'.format(e))
        pass
    except Exception as e:
        logger.error('Exception: {0}'.format(e))
        pass


def snapshot_volumes(region):
    ec2_conn = boto.ec2.connect_to_region(region)
    volumes = [v for v in ec2_conn.get_all_volumes() if v.id in options.volumes]
    for v in volumes:
        s = v.create_snapshot(description='forensic snapshot of {0} taken {1}'.format(v.attach_data.instance_id, toUTC(datetime.now()).isoformat()))
        print('created {0}'.format(s))


def main():
    if options.regions or options.instances:
        for region in options.regions:
            if options.instances is None or len(options.instances) == 0:
                get_ec2_instances(region)
            else:
                get_instance_info(region, options.instances)

            if options.volumes is not None and len(options.volumes) > 0:
                snapshot_volumes(region)



if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option("-c", "--conf", dest='configfile', default=sys.argv[0].replace('.py', '.conf'), help="configuration file to use")
    parser.add_option("-o", "--output", dest='output', default='text', help="output format, json or text")
    parser.add_option("-r", "--regions", dest='regions', default=None, help="comma delimited list of regions to target")
    parser.add_option("-i", "--instances", dest='instances', default=None, help="comma delimited list of instance IDs to target")
    parser.add_option("-v", "--volumes", dest='volumes', default=None, help="comma delimited list of volume IDs to snapshot")
    (options, args) = parser.parse_args()
    initConfig()
    initLogger()
    main()
