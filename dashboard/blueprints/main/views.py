import json
import csv
import io
import logging

from flask import session as flask_session
from flask import (current_app, render_template, flash, url_for, redirect,
                   request, jsonify, make_response, send_file)
from flask_login import current_user, login_required

from dashboard import db
from . import main_bp as main
from .utils import get_run_log
from ...queries import (query_metric_values_byid, query_metric_types,
                        query_metric_values_byname, find_subjects,
                        find_sessions, find_scans)
from ...models import Study, Site, Timepoint, Analysis
from ...forms import (SelectMetricsForm, StudyOverviewForm, AnalysisForm)

logger = logging.getLogger(__name__)


@main.route('/')
@main.route('/index')
@login_required
def index():
    """
    Main landing page
    """
    studies = current_user.get_studies()

    timepoint_count = Timepoint.query.count()
    study_count = Study.query.count()
    site_count = Site.query.count()
    return render_template('index.html',
                           studies=studies,
                           timepoint_count=timepoint_count,
                           study_count=study_count,
                           site_count=site_count)


@main.route('/search_data')
@main.route('/search_data/<string:search_string>', methods=['GET', 'POST'])
@login_required
def search_data(search_string=None):
    """
    Implements the site's search bar.
    """
    if not search_string:
        # We need the URL endpoint without a search string to enable the use of
        # 'url_for' in the javascript for the 'search' button, but no one
        # should ever actually access the page this way
        flash('Please enter a search term.')
        return redirect('index')

    subjects = find_subjects(search_string)
    if len(subjects) == 1:
        study = subjects[0].accessible_study(current_user)
        if study:
            return redirect(
                url_for('timepoints.timepoint',
                        study_id=study.id,
                        timepoint_id=subjects[0].name))
    subjects = [
        url_for('timepoints.timepoint',
                study_id=sub.accessible_study(current_user),
                timepoint_id=sub.name) for sub in subjects
        if sub.accessible_study(current_user)
    ]

    sessions = find_sessions(search_string)
    if len(sessions) == 1:
        study = sessions[0].timepoint.accessible_study(current_user)
        if study:
            return redirect(
                url_for('timepoints.timepoint',
                        study_id=study.id,
                        timepoint_id=sessions[0].timepoint.name,
                        _anchor="sess" + str(sessions[0].num)))

    sessions = [
        url_for('timepoints.timepoint',
                study_id=sess.timepoint.accessible_study(current_user),
                timepoint_id=sess.timepoint.name,
                _anchor="sess" + str(sess.num)) for sess in sessions
        if sess.timepoint.accessible_study(current_user)
    ]

    scans = find_scans(search_string)
    if len(scans) == 1:
        study = scans[0].session.timepoint.accessible_study(current_user)
        if study:
            return redirect(
                url_for('scans.scan', study_id=study.id, scan_id=scans[0].id))

    scans = [
        url_for('scans.scan',
                study_id=scan.session.timepoint.accessible_study(current_user),
                scan_id=scan.id) for scan in scans
        if scan.session.timepoint.accessible_study(current_user)
    ]

    return render_template('search_results.html',
                           user_search=search_string,
                           subjects=subjects,
                           sessions=sessions,
                           scans=scans)


@main.route('/study/<string:study_id>', methods=['GET', 'POST'])
@main.route('/study/<string:study_id>/<active_tab>', methods=['GET', 'POST'])
@login_required
def study(study_id=None, active_tab=None):
    """
    This is the main view for a single study.
    The page is a tabulated view, I would have done this differently given
    another chance.
    """
    if not current_user.has_study_access(study_id):
        flash('Not authorised')
        return redirect(url_for('main.index'))

    # get the list of metrics for to graph from the study config
    display_metrics = current_app.config['DISPLAY_METRICS']

    # get the study object from the database
    study = db.session.get(Study, study_id)

    # this is used to update the readme text file
    form = StudyOverviewForm()

    if form.validate_on_submit():
        # form has been submitted check for changes
        # simple MD seems to replace \n with \r\n
        form.readme_txt.data = form.readme_txt.data.replace('\r', '')

        # also strip blank lines at the start and end as these are
        # automatically stripped when the form is submitted
        if not form.readme_txt.data.strip() == study.read_me:
            study.read_me = form.readme_txt.data
            study.save()

    form.readme_txt.data = study.read_me
    form.study_id.data = study_id

    nightly_log = get_run_log(
        current_app.config['RUN_LOG_DIR'],
        study_id,
        current_app.config['RUN_COMPLETE_REGEX'],
        current_app.config['RUN_ERROR_REGEX'])

    return render_template('study.html',
                           study=study,
                           form=form,
                           active_tab=active_tab,
                           nightly_log=nightly_log,
                           display_metrics=display_metrics)


@main.route('/metricData', methods=['GET', 'POST'])
@login_required
def metricData():
    """
    This is a generic view for querying the database and allows selection of
    any combination of metrics and returns the data.

    The form is submitted on any change, this allows dynamic updating of the
    selection boxes displayed in the html (i.e. if SPINS study is selected
    the sites selector is filtered to only show sites relevent to SPINS).

    We only actually query and return the data if the query_complete is defined
    as true - this is done by client-side javascript.

    A lot of this could have been done client side but I think we all prefer
    writing python to javascript.
    """
    form = SelectMetricsForm()
    data = None
    csv_data = None
    csvname = 'dashboard/output.csv'
    w_file = open(csvname, 'w')

    if form.query_complete.data == 'True':
        data = metricDataAsJson()
        # convert the json object to csv format
        # Need the data field of the response object (data.data)
        temp_data = json.loads(data.data)["data"]
        if temp_data:

            testwrite = csv.writer(w_file)

            csv_data = io.BytesIO()
            csvwriter = csv.writer(csv_data)
            csvwriter.writerow(list(temp_data[0].keys()))
            testwrite.writerow(list(temp_data[0].keys()))
            for row in temp_data:
                csvwriter.writerow(list(row.values()))
                testwrite.writerow(list(row.values()))

    w_file.close()

    # anything below here is for making the form boxes dynamic
    if any([
            form.study_id.data, form.site_id.data, form.scantype_id.data,
            form.metrictype_id.data
    ]):
        form_vals = query_metric_types(studies=form.study_id.data,
                                       sites=form.site_id.data,
                                       scantypes=form.scantype_id.data,
                                       metrictypes=form.metrictype_id.data)

    else:
        form_vals = query_metric_types()

    study_vals = []
    site_vals = []
    scantype_vals = []
    metrictype_vals = []

    for res in form_vals:
        study_vals.append((res[0].id, res[0].name))
        site_vals.append((res[1].name, res[1].name))
        scantype_vals.append((res[2].tag, res[2].tag))
        metrictype_vals.append((res[3].id, res[3].name))
        # study_vals.append((res.id, res.name))
        # for site in res.sites:
        #     site_vals.append((site.id, site.name))
        # for scantype in res.scantypes:
        #     scantype_vals.append((scantype.id, scantype.name))
        #     for metrictype in scantype.metrictypes:
        #         metrictype_vals.append((metrictype.id, metrictype.name))

    # sort the values alphabetically
    study_vals = sorted(set(study_vals), key=lambda v: v[1])
    site_vals = sorted(set(site_vals), key=lambda v: v[1])
    scantype_vals = sorted(set(scantype_vals), key=lambda v: v[1])
    metrictype_vals = sorted(set(metrictype_vals), key=lambda v: v[1])

    flask_session['study_name'] = study_vals
    flask_session['site_name'] = site_vals
    flask_session['scantypes_name'] = scantype_vals
    flask_session['metrictypes_name'] = metrictype_vals

    # this bit actually updates the valid selections on the form
    form.study_id.choices = study_vals
    form.site_id.choices = site_vals
    form.scantype_id.choices = scantype_vals
    form.metrictype_id.choices = metrictype_vals

    reader = csv.reader(open(csvname, 'r'))
    csvList = [row for row in reader]

    if csv_data:
        csv_data.seek(0)
        return render_template('getMetricData.html', form=form, data=csvList)
    else:
        return render_template('getMetricData.html', form=form, data="")


def _checkRequest(request, key):
    # Checks a post request, returns none if key doesn't exist
    try:
        return (request.form.getlist(key))
    except KeyError:
        return (None)


@main.route('/DownloadCSV')
@login_required
def downloadCSV():

    output = make_response(send_file('output.csv', as_attachment=True))
    output.headers["Content-Disposition"] = "attachment; filename=output.csv"
    output.headers["Content-type"] = "text/csv"
    output.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    output.headers['Pragma'] = 'no-cache'
    return output


@main.route('/metricDataAsJson', methods=['Get', 'Post'])
@login_required
def metricDataAsJson(output='http'):
    """
    Query the database for metrics. Handles both GET (generated by client side
    javascript for creating graphs) and POST (generated by the metricData
    form view) requests

    Can be accessed at:
       http://srv-dashboard.camhres.ca/metricDataAsJson

    This will return all data in the database (probs not what you want).

    Filters can be defined in the http request object
    (http://flask.pocoo.org/docs/0.12/api/#incoming-request-data)
    this is a global flask object that is automatically created whenever a URL
    is requested. e.g.:

    <url>/metricDataAsJson?studies=15&sessions=1739,1744&metrictypes=84
    creates a request object
            request.args = {studies: 15,
                            sessions: [1739, 1744],
                            metrictypes: 84}
    If byname is defined (and evaluates True) in the request.args then filters
    can be defined by name instead of by database id e.g.
    <url>/metricDataAsJson?byname=True&studies=ANDT&sessions=ANDT_CMH_101_01

    Function works slightly differently if the request method is POST
    (such as that generated by metricData()). In that case the field names are
    expected to be the primary keys from the database as these are used to
    create the form.
    """
    # Define the mapping from GET field names to POST field names
    # it's going to get replaced either by the requested values (if defined in
    # the request object) or by None if not set as a filter
    fields = {
        'studies': 'study_id',
        'sites': 'site_id',
        'sessions': 'session_id',
        'scans': 'scan_id',
        'scantypes': 'scantype_id',
        'metrictypes': 'metrictype_id'
    }

    byname = False  # switcher to allow getting values byname instead of id

    try:
        if request.method == 'POST':
            byname = request.form['byname']
        else:
            byname = request.args.get('byname')
    except KeyError:
        pass

    # extract the values from the request object and populate
    for k, v in fields.items():
        if request.method == 'POST':
            fields[k] = _checkRequest(request, v)
        else:
            if request.args.get(k):
                fields[k] = [x.strip() for x in request.args.get(k).split(',')]
            else:
                fields[k] = None

    # remove None values from the dict
    fields = dict((k, v) for k, v in fields.items() if v)

    # make the database query
    if byname:
        data = query_metric_values_byname(**fields)
    else:
        # convert from strings to integers
        for k, vals in fields.items():
            try:
                fields[k] = int(vals)
            except TypeError:
                fields[k] = [int(v) for v in vals]

        data = query_metric_values_byid(**fields)

    # the database query returned a list of sqlachemy record objects.
    # convert these into a standard list of dicts so we can jsonify it
    objects = []

    for metricValue in data:
        session = [
            session_link.session for session_link in metricValue.scan.sessions
            if session_link.is_primary
        ][0]
        objects.append({
            'value': metricValue.value,
            'metrictype': metricValue.metrictype.name,
            'metrictype_id': metricValue.metrictype_id,
            'scan_id': metricValue.scan_id,
            'scan_name': metricValue.scan.name,
            'scan_description': metricValue.scan.description,
            'scantype': metricValue.scan.scantype.name,
            'scantype_id': metricValue.scan.scantype_id,
            'session_id': session.id,
            'session_name': session.name,
            # 'session_date':     metricValue.scan.session.date,
            'site_id': session.site_id,
            'site_name': session.site.name,
            'study_id': session.study_id,
            'study_name': session.study.name
        })

    if output == 'http':
        # spit this out in a format suitable for client side processing
        return (jsonify({'data': objects}))
    else:
        # return a pretty object for human readable
        return (json.dumps(objects, indent=4, separators=(',', ': ')))


@main.route('/analysis', methods=['GET', 'POST'])
@main.route('/analysis/<analysis_id>')
@login_required
def analysis(analysis_id=None):
    """
    Default view for analysis
    """
    form = AnalysisForm()
    if form.validate_on_submit():
        try:
            analysis = Analysis()
            analysis.name = form.name.data
            analysis.description = form.description.data
            analysis.software = form.software.data

            db.session.add(analysis)
            db.session.commit()
            flash('Analysis added')
        except Exception:
            flash('Failed adding analysis')

    if not analysis_id:
        analyses = Analysis.query.all()
    else:
        analyses = db.session.get(Analysis, analysis_id)

    for analysis in analyses:
        # format the user objects for display on page
        users = analysis.get_users()
        analysis.user_names = ' '.join([user.realname for user in users])

    return render_template('analyses.html', analyses=analyses, form=form)
