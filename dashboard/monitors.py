#!/usr/bin/env python
"""Add and run scheduled jobs.

Each scheduled job requires two pieces:
    1) A 'check' function that will run at the scheduled time and that does
       the actual work.
    2) A 'monitor' function that packages up the check function, any arguments
       it needs, and a date/time and submits it to the server.

Database queries can be made from within the check function to reduce the
number of arguments that must be passed. Remember also to use the check
function to verify that the scheduled task still makes sense to run at the
time it is executed. i.e. make sure data hasn't been deleted, notifications are
still relevant, etc.

.. warning:: Any inputs submitted to the scheduler must be
    `JSON serializable. <https://docs.python.org/3/library/json.html#json.JSONEncoder>`_
    Check functions, therefore, must only accept these types as input.

"""  # noqa: E501
import logging
from uuid import uuid4
from datetime import datetime, timedelta

from dashboard import scheduler
from .models import db, Session
from .emails import missing_redcap_email
from .exceptions import MonitorException, SchedulerException

logger = logging.getLogger(__name__)


def add_monitor(check_function,
                input_args,
                input_kwargs=None,
                job_id=None,
                days=None,
                hours=None,
                minutes=None):
    """Add a job to be run on the server at a scheduled time.

    Args:
        check_function (:obj:`function`): The function that will run at the
            scheduled day and time.
        input_args (Any): Arguments to pass to check_function at runtime
        input_kwargs (Any, optional): Optional args to pass to check_function
            at runtime.
        job_id (:obj:`str`, optional): A unique identifier for the job
        days (int, optional): Number of days to add to the current time when
            setting the run date.
        hours (int, optional): Number of hours to add to the current time when
            setting the run date
        minutes (int, optional): Number of minutes to add to the current time
            when setting the run date

    Raises:
        :obj:`dashboard.exceptions.SchedulerException`: If the job cannot be
            added to the server.

    Returns:
        :obj:`str`: The HTTP reply sent by the server
    """

    scheduled_time = datetime.now()
    if days:
        scheduled_time = scheduled_time + timedelta(days=days)
    if hours:
        scheduled_time = scheduled_time + timedelta(hours=hours)
    if minutes:
        scheduled_time = scheduled_time + timedelta(minutes=minutes)

    extra_args = {
        'trigger': 'date',
        'run_date': scheduled_time,
        'args': input_args
    }
    if input_kwargs:
        extra_args['kwargs'] = input_kwargs

    if not job_id:
        job_id = uuid4().hex

    try:
        job = scheduler.add_job(job_id, check_function, **extra_args)
    except SchedulerException as e:
        raise MonitorException(f"Adding monitor failed - {e}")
    return job


def get_emails(users):
    """Retrieve a list of emails for the given users (without duplicates).

    Args:
        users (:obj:`list` of :obj:`dashboard.models.User`): A list of users
            to extract email addresses for.

    Returns:
        list: A :obj:`str` email address for each user.
    """
    recipients = []
    for user in users:
        if not user.email:
            logger.error("No email configured for user {} - {}. Cannot enable "
                         "email notification.".format(user.id, user))
            continue
        if user.email in recipients:
            continue
        recipients.append(user.email)
    return recipients


def monitor_redcap_import(name, num, users=None, study=None):
    """Add a scheduled job to run :py:func:`check_redcap`.

    This adds a scheduled job that will run :obj:`check_redcap` two days
    after job submission and notify either the given list of users or all staff
    contacts and study RAs if a redcap record has not found at that time.

    Args:
        name (:obj:`str`): A session name
        num (int): A session number
        users (:obj:`list` of :obj:`dashboard.models.User`, optional):
            A list of users to notify
        study (:obj:`dashboard.models.Study`, optional): The study to monitor
            if the session belongs to more than one.

    Raises:
        :obj:`dashboard.exceptions.MonitorException`: If the 'users' argument
            was not set and no users are set as a staff contact or RA for the
            session's study
        :obj:`dashboard.exceptions.SchedulerException`: If the job cannot
            be added to the server
    """
    session = db.session.get(Session, (name, num))

    if not session.timepoint.expects_redcap() or session.redcap_record:
        return

    db_study = session.get_study(study_id=study)

    if not users:
        users = db_study.get_staff_contacts()
        site = session.timepoint.site.name
        users.extend(db_study.get_RAs(site=site))
        if not users:
            raise MonitorException("No users found to receive redcap import "
                                   "notifications for {}".format(session))

    if not isinstance(users, list):
        users = [users]

    recipients = get_emails(users)
    if not recipients:
        raise MonitorException("None of the expected users {} have an email "
                               "address configured. Cannot send redcap import "
                               "notifications for {}".format(users, session))

    args = [session.name, session.num]
    kwargs = {'recipients': recipients}
    add_monitor(check_redcap, args, input_kwargs=kwargs, days=2)


def check_redcap(name, num, recipients=None):
    """Emails a notification if the given session doesnt have a redcap record.

    Args:
        name (:obj:`str`): A session name
        num (int): A session number
        recipients (:obj:`list` of :obj:`str`, optional): A list of email
            address to notify.

    Raises:
        :obj:`dashboard.exceptions.MonitorException`: If a matching session
            can't be found.
    """
    session = db.session.get(Session, (name, num))
    if not session:
        raise MonitorException("Monitored session {}_{:02d} is no longer in "
                               "database. Cannot verify whether redcap record "
                               "was received.".format(name, num))

    if session.redcap_record:
        return

    missing_redcap_email(str(session),
                         session.get_study().id,
                         dest_emails=recipients)
