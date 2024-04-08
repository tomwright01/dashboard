"""Monitors used by the redcap blueprint.

Any scheduler jobs that the redcap blueprint needs will require a monitor
function and a check function here. See dashboard.monitors for more information
on monitors and check functions.
"""
from datetime import datetime, timedelta

from .emails import missing_session_data
from dashboard.monitors import add_monitor, get_emails
from dashboard.models import Session, User, db
from dashboard.exceptions import MonitorException
from dashboard.queue import submit_job


def monitor_scan_import(session, users=None):
    """Add a scheduler job to track whether a session's data is imported.

    This creates a scheduler job that will run :obj:`check_scans` two days
    after job submission.

    Args:
        session (:obj:`dashboard.models.Session`): The session to track
        users (:obj:`list` of :obj:`dashboard.models.User` or
            :obj:`dashboard.models.User`, optional): The user(s) to email. If
            none are provided, dashboard admins will be emailed.

    Raises:
        :obj:`dashboard.exceptions.MonitorException`: if a
            :obj:`dashboard.models.Session` object is not given, or users
            can't be found to send the notification to, or none of the found
            users have an email defined.
        :obj:`dashboard.exceptions.SchedulerException`: if the job can't be
            added to the server.
    """
    if not isinstance(session, Session):
        raise MonitorException("Must provide an instance of "
                               "dashboard.models.Session to add a scan "
                               "import monitor. Received type {}".format(
                                   type(session)))

    if not session.missing_scans():
        return

    if not users:
        users = User.query.filter(User.dashboard_admin == True).all()  # noqa: E712, E501
        if not users:
            raise MonitorException("No users given and no dashboard admins "
                                   "found, cant add scan import monitor for "
                                   "{}".format(session))

    if not isinstance(users, list):
        users = [users]

    recipients = get_emails(users)
    if not recipients:
        raise MonitorException("None of the users {} expected to receive scan "
                               "import notifications for {} have an email "
                               "address configured.".format(users, session))

    args = [session.name, session.num]
    kwargs = {'recipients': recipients}

    add_monitor(check_scans, args, input_kwargs=kwargs, days=2)


def check_scans(name, num, recipients=None):
    """Sends an email if the given session does not have data.

    Args:
        name (:obj:`str`): The session name
        num (int): The repeat number
        recipients (:obj:`list` of :obj:`str`, optional): A list of email
            addresses to contact if no data exists. If not set, dashboard
            admins will receive the notification.

    Raises:
        :obj:`dashboard.exceptions.MonitorException`: If a matching session
            can't be found.
    """
    session = db.session.get(Session, (name, num))
    if not session:
        raise MonitorException("Monitored session {}_{:02d} is no "
                               "longer in database. Cannot verify whether "
                               "scan data was received".format(name, num))
    if session.scans:
        return
    # dest emails are not set until we decide we're ok with RAs receiving
    # emails about scans not being imported in time.
    missing_session_data(str(session),
                         study=session.get_study().id,
                         dest_emails=None)


def monitor_scan_download(session, end_time=None):
    """Add a job to download a session.

    Note: This one directly downloads a subject while monitor_scan_import
    just notifies users if download doesnt occur within a time window.

    Args:
        session (:obj:`dashboard.models.Session`): The session to download.
        end_time (:obj:`datetime.datetime`): The date and time for when
            to stop download attempts. If not set, attempts will stop two days
            from the first time the function is called. Defaults to None.

    Raises:
        :obj:`dashboard.exceptions.MonitorException`: if a
            :obj:`dashboard.models.Session` object is not given for session or
            a :obj:`datetime.datetime` object is not given for end_time, if
            end_time is provided.
        :obj:`dashboard.exceptions.SchedulerException`: if a job to retry
            download can't be added to the scheduler server.
    """
    if not isinstance(session, Session):
        raise MonitorException("Must provide an instance of "
                               "dashboard.models.Session to add a scan "
                               "download monitor. Received type {}".format(
                                   type(session)))

    if end_time and not isinstance(end_time, datetime):
        raise MonitorException("End time must be an instance of datetime. "
                               "Received type {}".format(type(end_time)))

    study = session.get_study()

    if not session.missing_scans():
        settings = study.sites[session.site.name]
        if settings.post_download_script:
            submit_job(
                settings.post_download_script,
                [study.id, str(session)]
            )
        return

    if not end_time:
        end_time = datetime.now() + timedelta(days=2)
        download_session(session.name, session.num, str(end_time.timestamp()))
        return

    if datetime.now() >= end_time:
        # Download failed + out of time
        return

    add_monitor(
        download_session,
        # .timestamp needed for py3.5
        [str(session.name), str(session.num), str(end_time.timestamp())],
        hours=1
    )


def download_session(name, num, end_time):
    session = db.session.get(Session, (name, num))
    if not session:
        raise MonitorException(
            "Monitored session {}_{} is no longer in database, aborting "
            "download attempt.".format(name, str(num).zfill(2)))

    study = session.get_study()
    site_settings = study.sites[session.site.name]

    args = [study.id, str(session)]

    submit_job(site_settings.download_script, args)
    monitor_scan_download(session, datetime.fromtimestamp(float(end_time)))
