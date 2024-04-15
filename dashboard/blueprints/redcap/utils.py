#!/usr/bin/env python

import re
import logging

from flask import url_for, flash
from werkzeug.routing import RequestRedirect
import redcap as REDCAP

from .monitors import monitor_scan_import, monitor_scan_download
from dashboard.models import Session, Timepoint, RedcapRecord, RedcapConfig, db
from dashboard.queries import get_studies
from dashboard.exceptions import RedcapException
import datman.scanid

logger = logging.getLogger(__name__)


def get_redcap_record(record_id, fail_url=None):
    if not fail_url:
        fail_url = url_for('main.index')

    record = db.session.get(RedcapRecord, record_id)

    if record is None:
        logger.error("Tried and failed to retrieve RedcapRecord with "
                     "ID {}".format(record_id))
        flash("Record not found.")
        raise RequestRedirect(fail_url)

    return record


def create_from_request(request):
    try:
        record = request.form['record']
        project = request.form['project_id']
        url = request.form['redcap_url']
        instrument = request.form['instrument']
        version = re.search('redcap_v(.*)/index',
                            request.form['project_url']).group(1)
    except KeyError:
        raise RedcapException('Redcap data entry trigger request missing a '
                              'required key. Found keys: {}'.format(
                                  list(request.form.keys())))

    try:
        cfg = RedcapConfig.get_config(
            url=url, project=project, instrument=instrument
        )
    except Exception as e:
        logger.info(
            "Failed to find redcap config for record {} in project {} on "
            "server {} with instrument {}. Exception - {}".format(
                record, project, url, instrument, e
            )
        )
        return

    if isinstance(cfg.completed_value, list):
        completed = cfg.completed_value
    else:
        completed = list(cfg.completed_value)

    if (cfg.completed_field in request.form and
            request.form[cfg.completed_field] not in completed):
        # Check if complete before pulling whole record
        logger.info("Record {} not completed. Ignoring".format(record))
        return

    if 'redcap_event_name' in request.form:
        event_name = request.form['redcap_event_name']
        event_id = (
            cfg.event_ids.get(event_name) if cfg.event_ids else None
        )
    else:
        event_name = None
        event_id = None

    rc = REDCAP.Project(url + 'api/', cfg.token)
    server_record = rc.export_records([record])

    if event_name:
        server_record = [item for item in server_record
                         if item['redcap_event_name'] == event_name]

    if len(server_record) == 0:
        raise RedcapException('Record {} not found on redcap server {}'.format(
            record, url))
    elif len(server_record) > 1:
        raise RedcapException('Found {} records matching {} on redcap server '
                              '{}'.format(len(server_record), record, url))

    server_record = server_record[0]

    if (cfg.completed_field not in request.form and
            server_record[cfg.completed_field] not in completed):
        # Check when the 'completed' field wasnt present in the DET
        logger.info("Record {} not completed. Ignoring".format(record))
        return

    try:
        date = server_record[cfg.date_field]
        comment = server_record[cfg.comment_field]
        session_name = server_record[cfg.session_id_field]
        redcap_user = (
            server_record[cfg.user_id_field] if cfg.user_id_field else None
        )
    except KeyError:
        raise RedcapException(f'Redcap record {record} missing required field.'
                              f' Found keys: {list(server_record.keys())}')

    try:
        session = set_session(session_name)
    except Exception as e:
        raise RedcapException(
            "Failed finding session for record {} from project {} on server "
            "{}. Reason: {}".format(record, project, url, e)
        )

    try:
        new_record = session.add_redcap(
            record, date, config=cfg.id, rc_user=redcap_user, comment=comment,
            redcap_version=version, event_id=event_id
        )
    except Exception as e:
        raise RedcapException("Failed adding record {} from project {} on "
                              "server {}. Reason: {}".format(
                                  record, project, url, e))

    monitor_scan_import(session)

    study = session.get_study()
    site_settings = study.sites[session.site.name]

    if site_settings.download_script:
        monitor_scan_download(session)

    return new_record


def set_session(name):
    name = name.strip().upper()
    try:
        ident = datman.scanid.parse(name)
    except datman.scanid.ParseException:
        raise RedcapException("Invalid session ID {}".format(name))

    name = ident.get_full_subjectid_with_timepoint()
    num = datman.scanid.get_session_num(ident)

    session = db.session.get(Session, (name, num))
    if not session:
        timepoint = get_timepoint(ident)
        session = timepoint.add_session(num)

    return session


def find_study(ident):
    study = get_studies(tag=ident.study, site=ident.site)
    if not study:
        raise RedcapException("Invalid study/site combination: {} {}"
                              "".format(ident.study, ident.site))
    return study


def get_timepoint(ident):
    timepoint = db.session.get(
        Timepoint, ident.get_full_subjectid_with_timepoint())
    if not timepoint:
        study = find_study(ident)[0]
        timepoint = study.add_timepoint(ident)
    return timepoint
