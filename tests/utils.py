"""Re-usable functions to help with testing.
"""
from collections import namedtuple
import sqlalchemy

from dashboard import models

Session = namedtuple("Session", "name site num is_phantom", defaults=[False])
Scan = namedtuple("Scan", "name series tag review",
                  defaults=[None])
QcReview = namedtuple("QcReview", "uid sign_off comment", defaults=[None])


def add_studies(study_conf):
    """Add studies to the test database.

    Args:
        study_conf (:obj:`dict`): A dictionary containing study IDs as
            keys, each of which has its own dictionary of sites mapped to
            the scan types for the site. E.g.
                {"STUDY1": {
                    "CMH": ["T1", "T2"]
                    "UTO": ["DTI60-1000"]
                  },
                  "STUDY2": {
                    "ABC": ["T1", "ASL"]
                  }
                }

    Returns:
        list: a list of dashboard.models.Study records for each created
            study.
    """
    studies = []
    for study_id in study_conf:
        study = models.Study(study_id)
        models.db.session.add(study)
        studies.append(study)

        for site in study_conf[study_id]:
            study.update_site(site, create=True)

            for tag in study_conf[study_id][site]:
                if not models.db.session.get(models.Scantype, tag):
                    models.db.session.add(models.Scantype(tag))
                study.update_scantype(site, tag, create=True)

    return studies


def add_scans(study, scans):
    """Add scans (and their timepoint + session records) to the test database.

    Args:
        study (:obj:`dashboard.models.Study`): A study record from the
            database. All created scans will be added to this study.
        scans (:obj:`dict`): A dictionary of Session named tuples mapped
            to a list of Scan named tuples. E.g.
                {
                  Session("STUDY1_CMH_0001_01", "CMH", 1): [
                      Scan("STUDY1_CMH_0001_01_01_T1_03", 3, "T1")
                ]}
            All scans and their parent sessions and timepoints will be
            created.

    Returns:
        list: A list of :obj:`dashboard.models.Scan` objects that have
            been created in the test database.
    """
    output = []
    for session in scans:
        timepoint = models.Timepoint(session.name, session.site)
        study.add_timepoint(timepoint)
        timepoint.add_session(session.num)

        for item in scans[session]:
            scan = timepoint.sessions[session.num].add_scan(
                item.name, item.series, item.tag)
            if item.review:
                review = item.review
                scan.add_checklist_entry(
                    review.uid, review.comment, review.sign_off)
            output.append(scan)

    return output


def query_db(sql_query):
    """Submit a raw sql query to the database.

    Args:
        sql_query (str): The sql query to submit.

    Result:
        list: A list of tuples containing the result.
    """
    try:
        records = models.db.session.execute(
            sqlalchemy.text(sql_query)).fetchall()
    except sqlalchemy.exc.ProgrammingError:
        models.db.session.rollback()
        raise
    return records
