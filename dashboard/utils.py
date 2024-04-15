#!/usr/bin/env python
"""Helper functions for views.

"""
import logging
from functools import wraps

from urllib.parse import urlparse, urljoin
from flask_login import current_user
from flask import flash, url_for, request, redirect
from werkzeug.routing import RequestRedirect

from .models import Timepoint, Scan, db

logger = logging.getLogger(__name__)


def read_bool(value):
    """Converts a value to boolean.

    bool(value) misreads "false"/"False" as True, so we use this instead
    when parsing booleans from JSON requests.
    """
    if value in [False, None, "false", "False"]:
        return False
    return True

def report_form_errors(form):
    for field_name, errors in form.errors.items():
        try:
            label = getattr(form, field_name).label.text
        except AttributeError:
            logger.error("Form {} reported an error for a field, but "
                         "field was not found. field_name: {} error(s): "
                         "{}".format(form, field_name, errors))
            continue
        for error in errors:
            flash('ERROR - {} {}'.format(label, error))


def get_timepoint(study_id, timepoint_id, current_user):
    timepoint = db.session.get(Timepoint, timepoint_id)

    if timepoint is None:
        flash("Timepoint {} does not exist".format(timepoint_id))
        raise RequestRedirect(url_for("main.index"))

    if (not current_user.has_study_access(study_id, timepoint.site_id) or
            not timepoint.belongs_to(study_id)):
        flash("Not authorised to view {}".format(timepoint_id))
        raise RequestRedirect(url_for("main.index"))

    return timepoint


def get_session(timepoint, session_num, fail_url):
    try:
        session = timepoint.sessions[session_num]
    except KeyError:
        flash("Session {} does not exist for {}.".format(session_num,
                                                         timepoint))
        raise RequestRedirect(fail_url)
    return session


def get_scan(scan_id, study_id, current_user, fail_url=None):
    if not fail_url:
        fail_url = url_for('main.index')

    scan = db.session.get(Scan, scan_id)

    if scan is None:
        logger.error("User {} attempted to retrieve scan with ID {}. "
                     "Retrieval failed.".format(current_user, scan_id))
        flash("Scan does not exist.")
        raise RequestRedirect(fail_url)

    timepoint = scan.session.timepoint
    if (not current_user.has_study_access(study_id, timepoint.site_id) or
            not timepoint.belongs_to(study_id)):
        flash("Not authorized to view {}".format(scan.name))
        raise RequestRedirect(fail_url)

    return scan


def dashboard_admin_required(f):
    """
    Verifies a user is a dashboard admin before granting access
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.dashboard_admin:
            flash("Not authorized")
            return redirect(prev_url())
        return f(*args, **kwargs)

    return decorated_function


def study_admin_required(f):
    """
    Verifies a user is a study admin or a dashboard admin. Any view function
    this wraps must have 'study_id' as an argument
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_study_admin(kwargs['study_id']):
            flash("Not authorized.")
            return redirect(prev_url())
        return f(*args, **kwargs)

    return decorated_function


def prev_url():
    """
    Returns the referring page if it is safe to do so, otherwise directs
    the user to the index.
    """
    if request.referrer and is_safe_url(request.referrer):
        return request.referrer
    return url_for('main.index')


def is_safe_url(target):
    ref_url = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return (test_url.scheme in ('http', 'https')
            and ref_url.netloc == test_url.netloc)
