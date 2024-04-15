import logging

from github import Github

from flask import current_app, flash
from ...models import Study, db

logger = logging.getLogger(__name__)


def search_issues(token, timepoint):
    github_owner = current_app.config['GITHUB_OWNER']
    github_repo = current_app.config['GITHUB_REPO']
    search_string = "{} repo:{}/{}".format(
        timepoint, github_owner, github_repo)
    try:
        issues = Github(token).search_issues(search_string)
    except Exception:
        return None
    result = sorted(issues, key=lambda x: x.created_at)
    return result


def handle_issue(token, issue_form, study_id, timepoint):
    title = clean_issue_title(issue_form.title.data, timepoint)
    study = db.session.get(Study, study_id)

    staff_member = study.choose_staff_contact()
    if staff_member:
        assigned_user = staff_member.username
    else:
        assigned_user = None

    try:
        make_issue(token, title, issue_form.body.data, assign=assigned_user)
    except Exception as e:
        logger.error("Failed to create a GitHub issue for {}. "
                     "Reason: {}".format(timepoint, e))
        flash("Failed to create issue '{}'".format(title))
    else:
        flash("Issue '{}' created!".format(title))


def clean_issue_title(title, timepoint):
    title = title.rstrip()
    if not title:
        title = timepoint
    elif title.endswith('-'):
        title = title[:-1].rstrip()
    elif timepoint not in title:
        title = timepoint + " - " + title
    return title


def make_issue(token, title, body, assign=None):
    try:
        repo = get_issues_repo(token)
        if assign:
            issue = repo.create_issue(title, body, assignee=assign)
        else:
            # I thought a default of None would be a clever way to avoid
            # needing an if/else here but it turns out 'assignee' will raise a
            # mysterious exception when set to None :( So... here we are
            issue = repo.create_issue(title, body)
    except Exception as e:
        raise Exception("Can't create new issue '{}'. Reason: {}".format(
            title, e))
    return issue


def get_issues_repo(token):
    owner = current_app.config['GITHUB_OWNER']
    repo = current_app.config['GITHUB_REPO']
    try:
        repo = Github(token).get_user(owner).get_repo(repo)
    except Exception as e:
        raise Exception("Can't retrieve github issues repo. {}".format(e))
    return repo
